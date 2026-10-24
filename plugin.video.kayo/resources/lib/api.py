import base64
import binascii
import json
import os
import re
import uuid
from time import time

from six.moves.urllib_parse import parse_qsl, urlencode, urlparse, urlunparse
from slyguy import mem_cache, userdata
from slyguy.exceptions import Error
from slyguy.log import log
from slyguy.session import Session

from .constants import (
    BRAND,
    CONFIG_PARAMS,
    CONFIG_TTL,
    CONFIG_URL,
    COUNTRY,
    DEFAULT_ENTITLEMENT,
    HEADERS,
    LANGUAGE,
    LIVE_CHANNELS_RAIL,
    LOCK_URL,
    PLAYBACK_URL,
    PLAYER_PARAMS,
    QR_PAYLOAD,
    QR_SIGN_IN_URL,
    QR_STATUS_URL,
    QR_URL,
    RAIL_SERVICE,
    RAIL_URL,
    RAILS_SERVICE,
    RAILS_URL,
    REFRESH_URL,
    RESUME_URL,
    RULESET_RAIL_URL,
    SEARCH_URL,
    SIGN_IN_URL,
    SIGN_OUT_URL,
    SWITCH_PROFILE_URL,
    USER_PROFILE_URL,
)
from .language import _
from .settings import settings

# Playback error codes
CONCURRENCY_LIMIT = 10801
DEVICE_NOT_ALLOWED = 10802


class APIError(Error):
    pass


def uncap_manifest(url):
    # Lift the upper bound of the video_height filter, keeping any other filter clauses
    parsed = urlparse(url)
    query = [
        (k, re.sub(r"(video_height:\d+)-\d+", r"\1-32767", v) if k == "aws.manifestfilter" else v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunparse(parsed._replace(query=urlencode(query)))


def jwt_data(token):
    b64_string = token.split(".")[1]
    b64_string += "=" * ((4 - len(b64_string) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(b64_string))


def _json(resp):
    try:
        return resp.json()
    except ValueError:
        return None


def _error_message(data):
    try:
        error = data["odata.error"]
        return "{} ({})".format(error["message"]["value"], error["code"])
    except (KeyError, TypeError):
        pass

    if isinstance(data, dict):
        return data.get("message") or data.get("code")
    return None


def _error_code(data):
    try:
        return data["odata.error"]["code"]
    except (KeyError, TypeError):
        return None


class API:
    def new_session(self):
        self.logged_in = False
        self._session = Session(headers=HEADERS)
        self._set_authentication(userdata.get("access_token"))

    def _set_authentication(self, token):
        if not token:
            return

        self._session.headers.update({"Authorization": f"Bearer {token}"})
        self._session.headers.update({"X-DAZNID": userdata.get("dazn_id", "")})
        self.logged_in = True

    def _device_id(self):
        device_id = userdata.get("device_id")
        if not device_id:
            device_id = binascii.hexlify(os.urandom(5)).decode()
            userdata.set("device_id", device_id)
        return device_id

    def config(self, force=False):
        config = userdata.get("config")
        if config and not force and userdata.get("config_expires", 0) > time():
            return config

        try:
            data = self._session.get(CONFIG_URL, params=CONFIG_PARAMS).json()
            services = data["ServiceDictionary"]
        except Exception as e:
            # A stale copy still has working URLs
            if config:
                log.warning(f"Kayo config refresh failed, using the cached copy: {e}")
                return config
            raise APIError(_(_.CONFIG_ERROR, error=str(e)[:200])) from None

        config = {
            "services": {
                k: {ver: x.get("ServicePath") for ver, x in (v.get("Versions") or {}).items()}
                for k, v in services.items()
            },
            "region": data.get("Region") or {},
        }
        userdata.set("config", config)
        userdata.set("config_expires", int(time()) + CONFIG_TTL)
        return config

    def _service_url(self, service, default):
        name, version = service
        try:
            url = self.config()["services"].get(name, {}).get(version)
        except APIError as e:
            log.warning(str(e))
            url = None
        return url or default

    def _region_allowed(self):
        # Fetched fresh, as the answer changes with the connection (eg. a VPN turned on)
        try:
            return self.config(force=True)["region"].get("isAllowed") is not False
        except Exception:
            return True

    def _check(self, resp, data, error):
        # Turn the failures Kayo explains in its own codes into messages that say what to do; error is the
        # fallback message, with an {error} placeholder for whatever Kayo said.
        code = _error_code(data)
        if code == CONCURRENCY_LIMIT:
            raise APIError(_(_.TOO_MANY_STREAMS, max=self._max_streams()))
        if code == DEVICE_NOT_ALLOWED:
            raise APIError(_.LICENSE_DENIED)
        if resp.status_code == 403:
            if not self._region_allowed():
                raise APIError(_.GEO_BLOCKED)
            if data is None:
                # CloudFront's WAF answers with an HTML page before the request reaches the API
                raise APIError(_(_.REQUEST_BLOCKED, url=urlparse(resp.url).netloc))
        raise APIError(_(error, error=_error_message(data) or f"HTTP {resp.status_code}"))

    def _max_streams(self):
        try:
            features = jwt_data(userdata.get("access_token"))["entitlements"]["features"]["CONCURRENCY"]
            return features.get("kayo_max_devices") or features["max_devices"]
        except Exception:
            return "?"

    def _save_token(self, token, result=None):
        if not token:
            raise APIError(_(_.LOGIN_FAILED, result=result or ""))

        # Result reflects the DAZN brand (eg. SignedInInactive), so check the Kayo product status instead
        jwt = jwt_data(token)
        status = (jwt.get("productStatus") or {}).get(BRAND, "")
        log.debug(f"Kayo sign in result: {result} product status: {status}")
        if not status.startswith("Active"):
            raise APIError(_(_.SUBSCRIPTION_INACTIVE, status=status or result or ""))

        userdata.set("access_token", token)
        userdata.set("expires", int(jwt["exp"]) - 300)
        userdata.set("dazn_id", jwt.get("user", ""))
        userdata.set("entitlements", [x["id"] for x in jwt.get("entitlements", {}).get("entitlementSets", [])])
        self._set_authentication(token)

    def _save_auth(self, data):
        data = data or {}
        token = (data.get("AuthToken") or {}).get("Token")
        self._save_token(token, data.get("Result") or _error_message(data))

    def _refresh_token(self, force=False):
        if not self.logged_in or (not force and userdata.get("expires", 0) > time()):
            return

        log.debug("Refreshing Kayo access token")
        data = self._session.post(REFRESH_URL, json={"DeviceId": self._device_id()}).json()
        if "AuthToken" not in data:
            self.logout()
            raise APIError(_(_.REFRESH_FAILED, error=_error_message(data) or ""))

        self._save_auth(data)

    def login(self, username, password):
        self.logout()

        payload = {
            "Email": username,
            "Password": password,
            "Platform": "web",
            "DeviceId": self._device_id(),
            "Brand": BRAND,
        }

        resp = self._session.post(SIGN_IN_URL, json=payload, headers={"brand": BRAND})
        data = _json(resp)
        if data is None:
            self._check(resp, data, _(_.LOGIN_FAILED, result="{error}"))
        self._save_auth(data)

    def device_code(self):
        # Start a QR sign in; the caller shows url as a QR and polls device_login(id) until it is approved
        self.logout()

        resp = self._session.post(QR_URL, json=dict(QR_PAYLOAD, deviceId=self._device_id()))
        data = _json(resp)
        session_id = (data or {}).get("secondScreenId")
        if not session_id:
            self._check(resp, data, _(_.LOGIN_FAILED, result="{error}"))
        return {"id": session_id, "url": QR_SIGN_IN_URL.format(session_id)}

    def device_login(self, session_id):
        # Returns True once the QR is approved, False while it is still pending (204 No Content)
        resp = self._session.get(QR_STATUS_URL + session_id)
        if resp.status_code in (202, 204, 404):
            return False

        data = _json(resp)
        if not isinstance(data, dict):
            log.debug(f"Kayo QR sign in pending: HTTP {resp.status_code}")
            return False

        token = data.get("token") or data.get("Token") or (data.get("AuthToken") or {}).get("Token")
        if not token:
            log.debug(f"Kayo QR sign in pending: {_error_message(data) or data}")
            return False

        self._save_token(token, data.get("Result"))
        return True

    def profiles(self):
        resp = self._session.get(USER_PROFILE_URL)
        data = _json(resp)
        if not resp.ok:
            self._check(resp, data, _.PROFILE_ERROR)
        return [x for x in (data or {}).get("profiles") or [] if x.get("profileId")]

    def profile(self):
        # The profile the session token is for, as last stored by switch_profile
        profile = userdata.get("profile") or {}
        try:
            token_profile = jwt_data(userdata.get("access_token")).get("profileId")
        except Exception:
            token_profile = None
        return profile if profile.get("id") == token_profile else {}

    def switch_profile(self, profile):
        resp = self._session.post(SWITCH_PROFILE_URL, json={"brand": BRAND.lower(), "profileId": profile["profileId"]})
        data = _json(resp)
        if not (data or {}).get("AuthToken"):
            self._check(resp, data, _.PROFILE_ERROR)

        self._save_auth(data)
        userdata.set(
            "profile", {"id": profile["profileId"], "name": profile.get("profileName"), "avatar": profile.get("avatar")}
        )
        # Rails can be personalised per profile
        mem_cache.empty()

    def _entitlements(self):
        return ",".join(userdata.get("entitlements") or [DEFAULT_ENTITLEMENT])

    @mem_cache.cached(60 * 5)
    def rails(self, group, params):
        query = {
            "groupId": group,
            "params": params,
            "country": COUNTRY,
            "openBrowse": "false",
            "userEntitlements": self._entitlements(),
            "brand": BRAND.lower(),
        }
        resp = self._session.get(self._service_url(RAILS_SERVICE, RAILS_URL), params=query)
        data = _json(resp)
        if not isinstance(data, dict) or "Rails" not in data:
            self._check(resp, data, "{error}")
        return data["Rails"]

    @mem_cache.cached(60 * 2)
    def rail(self, id, params="", service="Rail"):
        query = {"platform": "web", "id": id, "country": COUNTRY, "brand": BRAND.lower(), "languageCode": LANGUAGE}
        if params:
            query["params"] = params

        url = RULESET_RAIL_URL if service == "RulesetRail" else self._service_url(RAIL_SERVICE, RAIL_URL)
        data = self._session.get(url, params=query).json()
        if "odata.error" in data:
            log.warning(f"Rail {id} failed: {_error_message(data)}")
            return {"Id": id, "Tiles": []}
        return data

    def live_channels(self):
        return self.rail(LIVE_CHANNELS_RAIL).get("Tiles", [])

    def search(self, query):
        params = {
            "searchTerm": query,
            "langCode": LANGUAGE,
            "country": COUNTRY,
            "openBrowse": "false",
            "brand": BRAND.lower(),
        }
        return self._session.get(SEARCH_URL, params=params).json().get("Results", [])

    def _capabilities(self):
        # mta (multi-track audio) lists every commentary/language track in the one manifest. hevc moves a stream
        # onto its HEVC ladder; dd and ddp offer Dolby Digital (Plus) audio where a stream has it.
        capabilities = ["mta"]
        if settings.H265.value:
            capabilities.append("hevc")
        if settings.AC3.value:
            capabilities.append("dd")
        if settings.EC3.value:
            capabilities.append("ddp")
        return ",".join(capabilities)

    def _cdn_works(self, details):
        # Kayo lists several CDNs in varying order, and one can refuse this connection (eg. 401 Forbidden-680)
        token = details.get("CdnToken") or {}
        params = {token["Name"]: token["Value"]} if token.get("Name") else {}
        try:
            # The CDN doesn't need the Kayo session, so it isn't sent
            resp = self._session.get(
                details["ManifestUrl"],
                params=params,
                headers={"Authorization": None, "X-DAZNID": None},
                timeout=10,
            )
            return resp.ok
        except Exception as e:
            log.debug("CDN {} failed: {}".format(details.get("CdnName"), e))
            return False

    def play(self, asset_id):
        self._refresh_token()
        # A lock left by playback that didn't stop cleanly (eg. Kodi was killed) still holds a stream slot
        self.release_lock()

        params = dict(PLAYER_PARAMS, AssetId=asset_id, Capabilities=self._capabilities())

        def request():
            headers = {"x-dazn-device": self._device_id(), "x-correlation-id": str(uuid.uuid4())}
            return self._session.post(PLAYBACK_URL, params=params, json={}, headers=headers)

        resp = request()
        if resp.status_code == 401:
            # The token was revoked before its expiry
            self._refresh_token(force=True)
            resp = request()

        data = _json(resp)
        if not (data or {}).get("PlaybackDetails"):
            self._check(resp, data, _.PLAYBACK_ERROR)

        lock = data.get("PlaybackLock") or {}
        userdata.set("lock_id", lock.get("LockId"))

        # Move the first CDN that answers to the front; the last is used untested, as there's nothing to fall back to
        details = data["PlaybackDetails"]
        index = next((i for i, cdn in enumerate(details[:-1]) if self._cdn_works(cdn)), len(details) - 1)
        if index:
            log.warning("Kayo CDNs {} failed".format(", ".join(x.get("CdnName", "") for x in details[:index])))
            data["PlaybackDetails"] = [details[index], *details[:index], *details[index + 1 :]]

        return data

    def refresh_lock(self):
        lock_id = userdata.get("lock_id")
        if not lock_id:
            return

        self._refresh_token()
        data = self._session.put(LOCK_URL + "refresh/" + lock_id).json()
        if data.get("LockId"):
            userdata.set("lock_id", data["LockId"])
        else:
            log.warning(f"Lock refresh failed: {_error_message(data) or data}")

    def release_lock(self):
        lock_id = userdata.get("lock_id")
        if not lock_id:
            return

        userdata.delete("lock_id")
        try:
            self._session.delete(LOCK_URL + lock_id)
        except Exception as e:
            log.debug(f"Lock release failed: {e}")

    def resume_point(self, asset_id, position, length, video_type, event_id=None, asset_type_id=None):
        # Kayo's own resume point, shared with its apps; Playback returns it as ResumePoints
        payload = {
            "assetId": asset_id,
            "position": int(position),
            "contentLength": int(length),
            "videoType": video_type,
        }
        if event_id:
            payload["eventId"] = event_id
        if asset_type_id:
            payload["articleTypeId"] = asset_type_id

        self._refresh_token()
        try:
            resp = self._session.post(RESUME_URL, json=payload)
            if not resp.ok:
                log.warning(f"Resume point failed: HTTP {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            log.debug(f"Resume point failed: {e}")

    def logout(self):
        if userdata.get("access_token"):
            try:
                self._session.post(SIGN_OUT_URL, json={"DeviceId": self._device_id()})
            except Exception as e:
                log.debug(f"Sign out failed: {e}")

        userdata.delete("access_token")
        userdata.delete("expires")
        userdata.delete("dazn_id")
        userdata.delete("entitlements")
        userdata.delete("profile")
        userdata.delete("lock_id")
        # Resume positions were stored locally before Kayo's resume points were used
        userdata.delete("resume")
        mem_cache.empty()
        self.new_session()

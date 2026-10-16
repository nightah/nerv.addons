import base64
import binascii
import json
import os
import uuid
from time import time

from slyguy import mem_cache, userdata
from slyguy.exceptions import Error
from slyguy.log import log
from slyguy.session import Session

from .constants import (
    BRAND,
    COUNTRY,
    DEFAULT_ENTITLEMENT,
    HEADERS,
    LANGUAGE,
    LIVE_CHANNELS_RAIL,
    LOCK_URL,
    PLAYBACK_URL,
    PLAYER_PARAMS,
    RAIL_URL,
    RAILS_URL,
    REFRESH_URL,
    RULESET_RAIL_URL,
    SEARCH_URL,
    SIGN_IN_URL,
    SIGN_OUT_URL,
)
from .language import _


class APIError(Error):
    pass


def jwt_data(token):
    b64_string = token.split(".")[1]
    b64_string += "=" * ((4 - len(b64_string) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(b64_string))


def _error_message(data):
    try:
        error = data["odata.error"]
        return "{} ({})".format(error["message"]["value"], error["code"])
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

    def _save_token(self, data):
        token = (data.get("AuthToken") or {}).get("Token")
        if not token:
            raise APIError(_(_.LOGIN_FAILED, result=data.get("Result") or _error_message(data) or ""))

        # Result reflects the DAZN brand (eg. SignedInInactive), so check the Kayo product status instead
        jwt = jwt_data(token)
        status = (jwt.get("productStatus") or {}).get(BRAND, "")
        log.debug("Kayo sign in result: {} product status: {}".format(data.get("Result"), status))
        if not status.startswith("Active"):
            raise APIError(_(_.SUBSCRIPTION_INACTIVE, status=status or data.get("Result") or ""))

        userdata.set("access_token", token)
        userdata.set("expires", int(jwt["exp"]) - 300)
        userdata.set("dazn_id", jwt.get("user", ""))
        userdata.set("entitlements", [x["id"] for x in jwt.get("entitlements", {}).get("entitlementSets", [])])
        self._set_authentication(token)

    def _refresh_token(self, force=False):
        if not self.logged_in or (not force and userdata.get("expires", 0) > time()):
            return

        log.debug("Refreshing Kayo access token")
        data = self._session.post(REFRESH_URL, json={"DeviceId": self._device_id()}).json()
        if "AuthToken" not in data:
            self.logout()
            raise APIError(_(_.REFRESH_FAILED, error=_error_message(data) or ""))

        self._save_token(data)

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
        try:
            data = resp.json()
        except ValueError:
            raise APIError(_(_.LOGIN_FAILED, result=f"HTTP {resp.status_code}")) from None

        self._save_token(data)

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
        data = self._session.get(RAILS_URL, params=query).json()
        if "Rails" not in data:
            raise APIError(_error_message(data) or _.NO_DATA)
        return data["Rails"]

    @mem_cache.cached(60 * 2)
    def rail(self, id, params="", service="Rail"):
        query = {"platform": "web", "id": id, "country": COUNTRY, "brand": BRAND.lower(), "languageCode": LANGUAGE}
        if params:
            query["params"] = params

        url = RULESET_RAIL_URL if service == "RulesetRail" else RAIL_URL
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

    def play(self, asset_id):
        self._refresh_token()

        params = dict(PLAYER_PARAMS)
        params["AssetId"] = asset_id

        headers = {"x-dazn-device": self._device_id(), "x-correlation-id": str(uuid.uuid4())}

        resp = self._session.post(PLAYBACK_URL, params=params, json={}, headers=headers)
        data = resp.json()
        if not data.get("PlaybackDetails"):
            raise APIError(_(_.PLAYBACK_ERROR, error=_error_message(data) or f"HTTP {resp.status_code}"))

        lock = data.get("PlaybackLock") or {}
        userdata.set("lock_id", lock.get("LockId"))
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
        userdata.delete("lock_id")
        userdata.delete("resume")
        mem_cache.empty()
        self.new_session()

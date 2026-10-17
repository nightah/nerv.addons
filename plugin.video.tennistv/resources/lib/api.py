import base64
import json
import re
from time import time

from slyguy import mem_cache, userdata
from slyguy.exceptions import Error
from slyguy.log import log
from slyguy.session import Session

from .constants import (
    ACCOUNT,
    API_KEY_RE,
    BUNDLE_RE,
    CLIENT_ID,
    CONTENT_URL,
    DEVICE_GRANT,
    DEVICE_URL,
    ENTITLEMENT_URL,
    HEADERS,
    LANG,
    LOGOUT_URL,
    PAGE_SIZE,
    PLAYBACK_API,
    PLAYERS_URL,
    SEARCH_URL,
    SITE_URL,
    STREAMAMG_API_KEY,
    TOKEN_URL,
    TOURNAMENTS_URL,
    WATCHLIST_URL,
)
from .language import _


class APIError(Error):
    pass


def jwt_data(token):
    b64_string = token.split(".")[1]
    b64_string += "=" * ((4 - len(b64_string) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(b64_string))


class API:
    def new_session(self):
        self.logged_in = False
        self._session = Session(headers=HEADERS)
        self._set_authentication(userdata.get("access_token"))

    def _set_authentication(self, token):
        if not token:
            return

        self._session.headers.update({"Authorization": f"Bearer {token}"})
        self.logged_in = True

    def _save_token(self, data):
        token = data.get("access_token")
        if not token:
            raise APIError(_(_.LOGIN_FAILED, result=data.get("error_description") or data.get("error") or ""))

        try:
            expires = int(jwt_data(token)["exp"]) - 30
        except Exception:
            expires = int(time()) + int(data.get("expires_in", 300)) - 30

        userdata.set("access_token", token)
        userdata.set("refresh_token", data.get("refresh_token", ""))
        userdata.set("expires", expires)
        self._set_authentication(token)

    def _refresh_token(self, force=False):
        if not self.logged_in or (not force and userdata.get("expires", 0) > time()):
            return

        refresh_token = userdata.get("refresh_token")
        if not refresh_token:
            return

        log.debug("Refreshing TennisTV access token")
        data = self._session.post(
            TOKEN_URL,
            data={"client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": refresh_token},
        ).json()
        if "access_token" not in data:
            self.logout()
            raise APIError(_(_.REFRESH_FAILED, error=data.get("error_description") or data.get("error") or ""))

        self._save_token(data)

    def device_code(self):
        # Start the device-code flow; the caller shows user_code at verification_uri and polls device_login().
        data = self._session.post(DEVICE_URL, data={"client_id": CLIENT_ID}).json()
        if "device_code" not in data:
            raise APIError(_(_.LOGIN_FAILED, result=data.get("error_description") or data.get("error") or ""))
        return data

    def device_login(self, device_code):
        # Returns True once the user has authorised, False while still pending, and raises on a fatal error.
        data = self._session.post(
            TOKEN_URL,
            data={"client_id": CLIENT_ID, "grant_type": DEVICE_GRANT, "device_code": device_code},
        ).json()

        error = data.get("error")
        if error in ("authorization_pending", "slow_down"):
            return False
        if error:
            raise APIError(_(_.LOGIN_FAILED, result=data.get("error_description") or error))

        self._save_token(data)
        return True

    @mem_cache.cached(60 * 5)
    def content(self, tag=None, references=None, page=0, page_size=PAGE_SIZE):
        # tagNames filters by namespaced tag (video-type, year, live); references filters by ATP_PLAYER/ATP_TOURNAMENT.
        params = {"page": page, "pageSize": page_size}
        if tag:
            params["tagNames"] = tag
        if references:
            params["references"] = references
        data = self._session.get(CONTENT_URL, params=params, headers={"account": ACCOUNT}).json()
        return data.get("content", []), data.get("pageInfo", {})

    @mem_cache.cached(60 * 60)
    def players(self):
        # BIO content lists the featured players; each carries an ATP_PLAYER reference used to filter their videos.
        data = self._session.get(PLAYERS_URL, params={"pageSize": 200}, headers={"account": ACCOUNT}).json()
        players = []
        for bio in data.get("content", []):
            refs = bio.get("references") or []
            sid = next((r.get("sid") for r in refs if r.get("type") == "ATP_PLAYER" and r.get("sid")), None)
            if not sid:
                continue
            name = re.sub(r"\s+biography$", "", bio.get("title") or "", flags=re.IGNORECASE)
            players.append({"name": name, "sid": sid, "thumb": bio.get("thumbnailUrl") or bio.get("imageUrl")})
        players.sort(key=lambda p: p["name"].lower())
        return players

    @mem_cache.cached(60 * 60)
    def tournaments(self, year):
        # The calendar lists a season's tournaments by date range. Grand Slams are not ATP-owned, so TennisTV never
        # carries their footage - drop them so the menu has no permanently empty folders.
        params = {"from": f"{year}-01-01", "to": f"{year}-12-31", "size": 250, "page": 0}
        data = self._session.get(TOURNAMENTS_URL, params=params, headers={"account": ACCOUNT}).json()
        items = data if isinstance(data, list) else data.get("content", [])
        return [t for t in items if t.get("id") and t.get("type") != "GS"]

    def watchlist(self):
        self._refresh_token()
        # favoritemedia returns HTTP 415 without an explicit JSON content type, even though the request has no body.
        resp = self._session.get(
            WATCHLIST_URL,
            params={"account": ACCOUNT, "mediaType": "VIDEO", "size": 100, "page": 1},
            headers={"account": ACCOUNT, "Content-Type": "application/json"},
        )
        return resp.json().get("content", [])

    @mem_cache.cached(60 * 5)
    def content_by_id(self, video_id):
        # Resolve a numeric content id (eg. from a search hit) to its full item, including the mediaGuid.
        return self._session.get(f"{CONTENT_URL}/{video_id}", headers={"account": ACCOUNT}).json()

    def search(self, query):
        params = {"searchTerm": query, "langCode": LANG}
        data = self._session.get(SEARCH_URL, params=params, headers={"account": ACCOUNT}).json()
        return [hit["data"] for hit in data.get("hits", []) if hit.get("contentType") == "VIDEO"]

    def _streamamg_key(self, refresh=False):
        # The X-Api-Key is a public client constant published in the site's JS bundle. It is cached, falls back to
        # the baked-in default, and is re-derived from the live site when a playback call rejects it (rotation).
        if not refresh:
            return userdata.get("streamamg_key") or STREAMAMG_API_KEY

        try:
            html = self._session.get(SITE_URL).text
            bundle = re.search(BUNDLE_RE, html).group(0)
            script = self._session.get("https://www.tennistv.com" + bundle).text
            key = re.search(API_KEY_RE, script).group(1)
            userdata.set("streamamg_key", key)
            log.debug("Re-derived StreamAMG API key from site bundle")
            return key
        except Exception as e:
            log.warning(f"Could not re-derive StreamAMG API key: {e}")
            return userdata.get("streamamg_key") or STREAMAMG_API_KEY

    def _entry(self, media_guid, entitlement, api_key):
        return self._session.get(
            PLAYBACK_API + "/entry/" + media_guid,
            headers={
                "X-Api-Key": api_key,
                "Accept": "application/json",
                "Authorization": f"Bearer {entitlement}",
            },
        )

    def play(self, media_guid):
        self._refresh_token()

        # 1) Entitlement: proves the subscription and returns a short-lived token scoped to this entry.
        resp = self._session.get(ENTITLEMENT_URL.format(guid=media_guid), headers={"account": ACCOUNT})
        entitlement = resp.json().get("access_token")
        if not entitlement:
            raise APIError(_(_.PLAYBACK_ERROR, error=resp.json().get("message") or f"HTTP {resp.status_code}"))

        # 2) StreamAMG entry: returns the manifest URLs. Retry once with a re-derived key if the key was rotated.
        api_key = self._streamamg_key()
        resp = self._entry(media_guid, entitlement, api_key)
        if resp.status_code in (401, 403):
            resp = self._entry(media_guid, entitlement, self._streamamg_key(refresh=True))

        # Highlights return a clear DASH manifest; full replays return only an HLS one. Either is DRM-free.
        data = resp.json()
        media = data.get("media") or {}
        if not (media.get("dash") or media.get("hls")):
            raise APIError(_(_.PLAYBACK_ERROR, error=data.get("message") or f"HTTP {resp.status_code}"))
        return data

    def logout(self):
        refresh_token = userdata.get("refresh_token")
        if refresh_token:
            try:
                self._session.post(LOGOUT_URL, data={"client_id": CLIENT_ID, "refresh_token": refresh_token})
            except Exception as e:
                log.debug(f"Logout failed: {e}")

        userdata.delete("access_token")
        userdata.delete("refresh_token")
        userdata.delete("expires")
        mem_cache.empty()
        self.new_session()

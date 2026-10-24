"""Exercise plugin.video.kayo's API module against the live Kayo/DAZN services outside Kodi.

    python plugin.video.kayo/tests/smoke.py            # public catalogue checks only
    python plugin.video.kayo/tests/smoke.py --login    # also sign in (prompts) and test playback for a live channel
    python plugin.video.kayo/tests/smoke.py --qr       # sign in with a QR code instead: approve the printed URL
    python plugin.video.kayo/tests/smoke.py --quality  # compare resolutions offered to different client profiles

Credentials are only sent to Kayo. The session token is kept in plugin.video.kayo/tests/.userdata.json (mode 600)
so later runs can skip --login; delete that file to sign out.
"""

import getpass
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "shim"))
sys.path.insert(0, os.path.join(ROOT, ".."))

import requests
from resources.lib.api import API, jwt_data, uncap_manifest
from resources.lib.constants import QR_POLL_INTERVAL, QR_TIMEOUT, RAIL_SERVICE, RAILS_SERVICE, USER_AGENT
from slyguy import userdata

DEFAULT_ASSET = "1tc0mhfzkbbti165v1rsuewtek"  # Fox League


def check(name, ok, detail=""):
    print("[{}] {} {}".format("PASS" if ok else "FAIL", name, detail))
    if not ok:
        sys.exit(1)


def public(api):
    config = api.config(force=True)
    check(
        "config",
        all(config["services"].get(name, {}).get(version) for name, version in (RAILS_SERVICE, RAIL_SERVICE)),
        "(geo-allowed: {})".format(config["region"].get("isAllowed")),
    )

    rails = api.rails("Home", "PageType:Home;ContentType:None")
    check("home rails", len(rails) > 3, f"({len(rails)} rails)")

    channels = api.live_channels()
    check("live channels", len(channels) > 3, ", ".join(x["Title"] for x in channels))

    results = api.search("afl")
    check("search", sum(len(x["Tiles"]) for x in results) > 0)


def qr_login(api):
    data = api.device_code()
    print(f"Approve this device at {data['url']} (waiting up to {QR_TIMEOUT // 60} minutes)")
    for _ in range(QR_TIMEOUT // QR_POLL_INTERVAL):
        time.sleep(QR_POLL_INTERVAL)
        if api.device_login(data["id"]):
            return
    check("qr login", False, "timed out")


def profiles(api):
    rows = api.profiles()
    current = api.profile().get("id") or jwt_data(userdata.get("access_token")).get("profileId")
    check("profiles", any(x["profileId"] == current for x in rows), f"({len(rows)} profiles)")


def playback(api, asset_id):
    data = api.play(asset_id)
    details = data["PlaybackDetails"][0]
    check(
        "playback",
        True,
        "{} ({}), CDNs: {}".format(
            data["Asset"]["Title"], details.get("Resolution"), ", ".join(x["CdnName"] for x in data["PlaybackDetails"])
        ),
    )
    check("resume points", "ResumeFrom" in (data.get("ResumePoints") or {}), str(data.get("ResumePoints")))

    # Kayo returns several CDNs in varying order and the addon uses whichever is first, so check them all.
    # Segments are requested the way InputStream Adaptive does it: the addon's stream_params string appended as-is.
    headers = {"User-Agent": USER_AGENT}
    for cdn in data["PlaybackDetails"]:
        token = cdn["CdnToken"]
        stream_params = requests.compat.urlencode({token["Name"]: token["Value"]})
        resp = requests.get(cdn["ManifestUrl"], params={token["Name"]: token["Value"]}, headers=headers, timeout=30)
        check("{} manifest".format(cdn["CdnName"]), resp.ok and "<MPD" in resp.text, f"HTTP {resp.status_code}")

        init = re.search(r'initialization="([^"]+)"', resp.text).group(1)
        rep = re.search(r'<Representation[^>]*id="([^"]+)"', resp.text).group(1)
        seg_url = requests.compat.urljoin(cdn["ManifestUrl"], init.replace("$RepresentationID$", rep))
        no_token = requests.get(seg_url, headers=headers, timeout=30).status_code
        with_token = requests.get(
            seg_url + ("&" if "?" in seg_url else "?") + stream_params, headers=headers, timeout=30
        ).status_code
        check(
            "{} segment needs stream_params token".format(cdn["CdnName"]),
            no_token in (401, 403) and with_token == 200,
            f"without={no_token} with={with_token}",
        )

    # An empty challenge can't get a key, but proves the signed licence URL is accepted and reachable
    # Sent through the addon's session, as the licence host's WAF also rejects the default Python TLS fingerprint
    resp = api._session.post(
        details["LaUrl"],
        data=b"\x08\x04",
        headers={"Content-Type": "application/octet-stream", "X-BRAND": "KAYO"},
    )
    check(
        "licence endpoint reachable",
        resp.status_code not in (401, 403, 404),
        f"HTTP {resp.status_code} {resp.text[:200] if not resp.ok else ''}",
    )

    api.refresh_lock()
    check("lock refresh", True)
    api.release_lock()
    check("lock release", True)


CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

ANDROIDTV = {
    "PlayerId": "DAZN-androidtv",
    "Platform": "androidtv",
    "Model": "SHIELD Android TV",
    "Manufacturer": "NVIDIA",
}

QUALITY_VARIANTS = [
    ("addon (Dalvik UA, web player)", {"User-Agent": USER_AGENT}, {}),
    ("Dalvik UA, androidtv", {"User-Agent": USER_AGENT}, ANDROIDTV),
]


def quality(api, asset_id):
    """Compare the resolutions Kayo offers for different client profiles."""
    import uuid

    from resources.lib.constants import PLAYBACK_URL, PLAYER_PARAMS
    from slyguy import userdata

    for name, headers, overrides in QUALITY_VARIANTS:
        params = dict(PLAYER_PARAMS, AssetId=asset_id, **overrides)
        resp = api._session.post(
            PLAYBACK_URL,
            params=params,
            json={},
            headers=dict(headers, **{"x-dazn-device": api._device_id(), "x-correlation-id": str(uuid.uuid4())}),
        )
        try:
            data = resp.json()
        except ValueError:
            print(f"{name:40} HTTP {resp.status_code} (non-JSON)")
            continue

        if not data.get("PlaybackDetails"):
            print(
                "{:40} HTTP {} {}".format(
                    name, resp.status_code, data.get("odata.error", {}).get("message", {}).get("value")
                )
            )
            continue

        details = data["PlaybackDetails"][0]
        token = details.get("CdnToken") or {}
        token_params = {token["Name"]: token["Value"]} if token.get("Name") else {}
        query = requests.compat.urlparse(details["ManifestUrl"]).query
        print("{:40} Resolution={} filter={}".format(name, details.get("Resolution"), requests.compat.unquote(query)))

        # The addon lifts the manifest filter's height cap, check the CDN still serves it and what it then offers
        uncapped = uncap_manifest(details["ManifestUrl"])
        for label, url in (("as returned", details["ManifestUrl"]), ("uncapped", uncapped)):
            resp = requests.get(url, params=token_params, headers={"User-Agent": headers["User-Agent"]}, timeout=30)
            heights = sorted({int(x) for x in re.findall(r'height="(\d+)"', resp.text)})
            print("{:40}   {:12} HTTP {} heights={}".format("", label, resp.status_code, heights))

        lock = (data.get("PlaybackLock") or {}).get("LockId")
        if lock:
            userdata.set("lock_id", lock)
            api.release_lock()


def main():
    api = API()
    api.new_session()
    public(api)

    if "--login" in sys.argv:
        email = input("Kayo email: ").strip()
        password = getpass.getpass("Kayo password: ")
        api.login(email, password)
        check("login", api.logged_in)
    elif "--qr" in sys.argv:
        qr_login(api)
        check("qr login", api.logged_in)

    if api.logged_in:
        api._refresh_token(force=True)
        check("token refresh", api.logged_in)
        profiles(api)
        args = [x for x in sys.argv[1:] if not x.startswith("--")]
        if "--quality" in sys.argv:
            quality(api, args[0] if args else DEFAULT_ASSET)
        else:
            playback(api, args[0] if args else DEFAULT_ASSET)
    else:
        print("Not signed in; run with --login or --qr to test playback.")


if __name__ == "__main__":
    main()

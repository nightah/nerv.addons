"""Exercise plugin.video.tennistv's API module against the live Tennis TV / StreamAMG services outside Kodi.

    python plugin.video.tennistv/tests/smoke.py            # public catalogue checks only
    python plugin.video.tennistv/tests/smoke.py --login    # device-code sign in, then test playback + quality
    python plugin.video.tennistv/tests/smoke.py --quality  # also compare the resolutions offered to each User-Agent
    python plugin.video.tennistv/tests/smoke.py <mediaGuid> # playback test for a specific video

Sign in is the Keycloak device-code flow: the script prints a URL and a code, you authorise in a browser, and
the token is kept in plugin.video.tennistv/tests/.userdata.json (mode 600) so later runs can skip --login;
delete that file to sign out.
"""

import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "shim"))
sys.path.insert(0, os.path.join(ROOT, ".."))

import requests
from resources.lib.api import API
from resources.lib.constants import CATEGORIES, USER_AGENT

# The stream token is bound to the User-Agent; compare what resolutions each profile is offered.
USER_AGENTS = [
    ("configured (desktop)", USER_AGENT),
    ("Android TV", "Dalvik/2.1.0 (Linux; U; Android 12; SHIELD Android TV Build/SR1A.211012.001)"),
    ("Smart TV (Tizen)", "Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebKit/537.36 (KHTML, like Gecko) Version/6.0"),
]


def check(name, ok, detail=""):
    print("[{}] {} {}".format("PASS" if ok else "FAIL", name, detail))
    if not ok:
        sys.exit(1)


def public(api):
    for title, tag, _icon in CATEGORIES:
        items, info = api.content(tag)
        entries = info.get("numEntries", 0)
        check(f"category '{title}'", len(items) > 0 and entries > 0, f"({entries} entries)")
        check("  item has mediaGuid", all(x.get("mediaGuid") for x in items))


def device_login(api):
    data = api.device_code()
    print("\n  >>> Go to {} and enter code: {}\n".format(data["verification_uri"], data["user_code"]))
    sys.stdout.flush()
    interval = max(int(data.get("interval", 5)), 1)
    for _elapsed in range(0, int(data.get("expires_in", 600)), interval):
        if api.device_login(data["device_code"]):
            return
        time.sleep(interval)
    check("login", False, "timed out waiting for authorisation")


def _media_url(data):
    media = data["media"]
    if media.get("dash"):
        return media["dash"], "DASH"
    return media["hls"], "HLS"


def _manifest(url, user_agent):
    resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=30)
    text = resp.text
    if "<MPD" in text:  # DASH
        heights = sorted({int(h) for h in re.findall(r'height="(\d+)"', text)})
        bandwidths = sorted({int(b) for b in re.findall(r'bandwidth="(\d+)"', text)})
        drm = "ContentProtection" in text
    else:  # HLS
        heights = sorted({int(h) for _w, h in re.findall(r"RESOLUTION=(\d+)x(\d+)", text)})
        bandwidths = sorted({int(b) for b in re.findall(r"BANDWIDTH=(\d+)", text)})
        drm = bool(re.search(r"#EXT-X-KEY:(?!.*METHOD=NONE)", text))
    return resp, heights, bandwidths, drm


def playback(api, media_guid):
    data = api.play(media_guid)
    url, kind = _media_url(data)
    check("entry", True, "{} [{}]".format(data.get("name"), kind))

    resp, heights, bandwidths, drm = _manifest(url, USER_AGENT)
    check("manifest", resp.ok and bool(heights), f"HTTP {resp.status_code} {kind}")
    check("clear (no DRM)", not drm)
    top = max(bandwidths) / 1e6 if bandwidths else 0
    print(f"    quality: max {max(heights)}p, heights={heights}, top bitrate {top:.1f} Mbps")


def quality(api, media_guid):
    data = api.play(media_guid)
    url, kind = _media_url(data)
    print("  {} ({}) [{}]".format(data.get("name"), media_guid, kind))
    for label, user_agent in USER_AGENTS:
        resp, heights, bandwidths, _drm = _manifest(url, user_agent)
        top = max(bandwidths) / 1e6 if bandwidths else 0
        print(
            "    {:22} -> {:>6}  heights={} top={:.1f} Mbps".format(
                label, (f"{max(heights)}p" if heights else f"HTTP {resp.status_code}"), heights, top
            )
        )


def main():
    api = API()
    api.new_session()
    public(api)

    if "--login" in sys.argv:
        device_login(api)
        check("login", api.logged_in)

    if api.logged_in:
        api._refresh_token(force=True)
        check("token refresh", api.logged_in)

        args = [x for x in sys.argv[1:] if not x.startswith("--")]
        if args:
            media_guid = args[0]
        else:
            # A full replay exercises higher resolutions than a short highlight.
            replays = {title: tag for title, tag, _icon in CATEGORIES}
            tag = replays.get("Replays", CATEGORIES[0][1])
            media_guid = api.content(tag)[0][0]["mediaGuid"]

        if "--quality" in sys.argv:
            quality(api, media_guid)
        else:
            playback(api, media_guid)
    else:
        print("Not signed in; run with --login to test playback.")


if __name__ == "__main__":
    main()

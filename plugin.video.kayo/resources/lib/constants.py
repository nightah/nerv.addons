BRAND = "KAYO"
COUNTRY = "au"
LANGUAGE = "en"

# The CDN token returned by Playback is bound to the user-agent, so the same user-agent must be used for the API calls
# and for the stream itself. A browser user-agent is blocked by the WAF on the sign-in and Playback endpoints.
USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 12; SHIELD Android TV Build/SR1A.211012.001)"

HEADERS = {"User-Agent": USER_AGENT, "X-BRAND": BRAND}

# The licence server now refuses a desktop (L3) CDM's challenge with "Device not allowed to receive a license"
# (10802) when the request carries the Android TV user-agent, but grants it to the desktop Chrome user-agent that
# goes with that CDM. It judges the user-agent's OS family against the CDM's platform_name, and a user-agent for a
# different OS than the CDM is blocked by CloudFront (403), so the family follows the installed CDM. Systems not
# listed (Android) keep USER_AGENT.
_LICENSE_USER_AGENT = "Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
_LICENSE_CLIENT_HINTS = {
    "sec-ch-ua": '"Not:A-Brand";v="8", "Chromium";v="156", "Google Chrome";v="156"',
    "sec-ch-ua-mobile": "?0",
}

# User-agent platform token and sec-ch-ua-platform per OS family (None: no client hints, as a bare macOS Chrome
# user-agent already passes CloudFront).
LICENSE_UA_FAMILIES = {
    "Linux": ("X11; Linux {arch}", '"Linux"'),
    "ChromeOS": ("X11; CrOS {arch} 14541.0.0", '"Chrome OS"'),
    "Windows": ("Windows NT 10.0; Win64; x64", '"Windows"'),
    "Darwin": ("Macintosh; Intel Mac OS X 10_15_7", None),
}

# CDMs that are not from their host OS: the armv7 Widevine CDM is taken from a Chromebook and reports platform_name
# ChromeOS, so a 32-bit ARM Linux host has to present as Chrome OS.
LICENSE_UA_CDM_FAMILIES = {
    ("Linux", "armv7"): "ChromeOS",
}

# get_system_arch() normalises its arch (32-bit ARM userland becomes armv7, i686 becomes i386).
LICENSE_UA_ARCHS = {
    "x86_64": "x86_64",
    "i386": "i686",
    "arm64": "aarch64",
    "armv7": "armv7l",
    "armv6": "armv7l",
}


def license_headers(system, arch):
    family = LICENSE_UA_CDM_FAMILIES.get((system, arch), system)
    if family not in LICENSE_UA_FAMILIES:
        return {"User-Agent": USER_AGENT}

    platform, hint_platform = LICENSE_UA_FAMILIES[family]
    headers = {
        "User-Agent": _LICENSE_USER_AGENT.format(platform=platform.format(arch=LICENSE_UA_ARCHS.get(arch, "x86_64")))
    }
    if hint_platform:
        headers.update(_LICENSE_CLIENT_HINTS)
        headers["sec-ch-ua-platform"] = hint_platform

    return headers


SIGN_IN_URL = "https://authentication-prod.ar.indazn.com/v5/SignIn"
SWITCH_PROFILE_URL = "https://authentication-prod.ar.indazn.com/v1/SwitchProfile"
USER_PROFILE_URL = "https://user-profile.ar.indazn.com/v4/UserProfile"
REFRESH_URL = "https://ott-authz-bff-prod.ar.indazn.com/v5/RefreshAccessToken"
SIGN_OUT_URL = "https://ott-authz-bff-prod.ar.indazn.com/v1/SignOut"
PLAYBACK_URL = "https://api.playback.indazn.com/v5/Playback"
LOCK_URL = "https://concurrency-v2.playback.indazn.com/v3/concurrency/lock/"
RESUME_URL = "https://resume-points-v3.playback.indazn.com/v1/resumepoints"

# QR sign in: the second-screen service hands out a session that is approved at QR_SIGN_IN_URL on a signed-in
# device, then polled for the token. Without the oemTrackingDetails it fails with INVALID_OEM_TRACKING_DETAILS.
QR_URL = "https://second-screen.ar.indazn.com/v2/subscribe/qr"
QR_STATUS_URL = "https://second-screen.ar.indazn.com/v1/subscribed/"
QR_SIGN_IN_URL = "https://kayosports.com.au/signin/device/{}"
QR_PAYLOAD = {
    "brand": BRAND.lower(),
    "signIn": True,
    "country": COUNTRY.upper(),
    "language": LANGUAGE,
    "oemTrackingDetails": {
        "platform": "androidtv",
        "manufacturer": "NVIDIA",
        "partnerID": "NVIDIA",
        "isSignUpDisabled": True,
        "productGroup": BRAND,
        "content": BRAND,
        "isFreemium": False,
        "sourceRef": "landing-page",
        "store": "GOOGLE_TV",
    },
}
QR_POLL_INTERVAL = 5
QR_TIMEOUT = 600

LOGIN_QR = "qr"
LOGIN_EMAIL = "email"

# The apps look up their service URLs in this bootstrap response, which also reports whether the connection is
# geo-allowed. It only lists the discovery services; the defaults cover a service or version it doesn't list.
CONFIG_URL = "https://startup.core.indazn.com/v2/main/lrd"
CONFIG_PARAMS = {
    "Version": 2,
    "Languages": LANGUAGE,
    "Platform": "web",
    "Manufacturer": "unknown",
    "Brand": BRAND.lower(),
}
CONFIG_TTL = 60 * 60 * 6

RAILS_SERVICE = ("Rails", "v9")
RAIL_SERVICE = ("Rail", "v11")
RAILS_URL = "https://rails.discovery.indazn.com/jp/v9/rails"
RAIL_URL = "https://rail-router.discovery.indazn.com/jp/v11/Rail"
RULESET_RAIL_URL = "https://ruleset-rail-router.discovery.indazn.com/jp/v1/Rail"
SEARCH_URL = "https://search.discovery.indazn.com/v1/search"

IMAGE_URL = "https://image.discovery.indazn.com/jp/v3/{folder}/none/{id}/fill/none/top/none/80/{width}/{height}/{ext}/image?brand=kayo"
# Channel logos (LogoImage) and schedule artwork only resolve from this folder, the default returns a Kayo placeholder
LINEAR_IMAGES = "linear-channel"

LIVE_CHANNELS_RAIL = "Livetvschedule"

# IPTV Merge: Foxtel channel numbers, keyed by Kayo channel title (Kayo leaves ChannelNumber empty)
CHANNEL_NUMBERS = {
    "fox sports news": 500,
    "fox cricket": 501,
    "fox league": 502,
    "fox sports 503": 503,
    "fox footy": 504,
    "fox sports 505": 505,
    "fox sports 506": 506,
    "fox sports 507": 507,
    "espn": 509,
    "espn2": 510,
    "racing.com": 529,
}
DEFAULT_ENTITLEMENT = "tier_standard_kayo"

# Playback query params, matching the desktop web player (peng-html5-core). The Android TV profile's license server
# rejects software (L3) Widevine CDMs with "Device not allowed to receive a license" (10802), the web one does not.
# With an Android user-agent the web profile caps the manifest at 720p (aws.manifestfilter=video_height:100-720),
# so the cap is lifted on the manifest URL before playback.
PLAYER_PARAMS = {
    "AppVersion": "0.150.3",
    "DrmType": "WIDEVINE",
    "Format": "MPEG-DASH",
    "PlayerId": "@dazn/peng-html5-core/web/web",
    "Platform": "web",
    "Model": "unknown",
    "Secure": "true",
    "Manufacturer": "unknown",
    "PlayReadyInitiator": "false",
    "LanguageCode": LANGUAGE,
}

# Tile types that can be played straight away
PLAYABLE_TYPES = ("Live", "CatchUp", "Highlights", "OnDemand", "Condensed", "Replay")

# Resume points closer than this to the start (or end) of a stream aren't worth offering
RESUME_MIN = 60

# InputStream Adaptive truncates a live DASH timeline at its 4 hour default timeshift buffer, so for longer events
# (eg. a day of Test cricket) the start of the event drops out of the DVR window. Leave room for the event to overrun.
TIMESHIFT_DEFAULT = 4 * 60 * 60
TIMESHIFT_MARGIN = 2 * 60 * 60

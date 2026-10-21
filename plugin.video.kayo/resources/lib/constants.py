BRAND = "KAYO"
COUNTRY = "au"
LANGUAGE = "en"

# The CDN token returned by Playback is bound to the user-agent, so the same user-agent must be used for the API calls
# and for the stream itself. A browser user-agent is blocked by the WAF on the sign-in and Playback endpoints.
USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 12; SHIELD Android TV Build/SR1A.211012.001)"

HEADERS = {"User-Agent": USER_AGENT, "X-BRAND": BRAND}

SIGN_IN_URL = "https://authentication-prod.ar.indazn.com/v5/SignIn"
REFRESH_URL = "https://ott-authz-bff-prod.ar.indazn.com/v5/RefreshAccessToken"
SIGN_OUT_URL = "https://ott-authz-bff-prod.ar.indazn.com/v1/SignOut"
PLAYBACK_URL = "https://api.playback.indazn.com/v5/Playback"
LOCK_URL = "https://concurrency-v2.playback.indazn.com/v3/concurrency/lock/"

RAILS_URL = "https://rails.discovery.indazn.com/jp/v9/rails"
RAIL_URL = "https://rail-router.discovery.indazn.com/jp/v10/Rail"
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

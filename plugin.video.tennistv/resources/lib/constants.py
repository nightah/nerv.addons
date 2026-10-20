# TennisTV runs on StreamAMG (a Kaltura-based platform). VOD is clear (unencrypted) DASH, so unlike the
# DAZN-based Kayo addon there is no Widevine licence and no concurrency lock. Auth is a Keycloak device-code
# login; playback is a two-step chain keyed by each video's mediaGuid: an entitlement token from TennisTV is
# exchanged at the StreamAMG entry endpoint for a signed manifest URL.

ACCOUNT = "atpmedia"

# The StreamAMG manifest/segment tokens are bound to the User-Agent (and the request's country), so the same
# User-Agent must be used for the catalogue, entitlement and entry calls and for every manifest/segment request.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}

# Keycloak (OpenID Connect) - device-code login only. The web client blocks password and device grants; the
# native-app public client tennis-tv-app allows the device grant with no secret and no PKCE.
CLIENT_ID = "tennis-tv-app"
OIDC_BASE = "https://sso.tennistv.com/auth/realms/tennistv/protocol/openid-connect"
DEVICE_URL = OIDC_BASE + "/auth/device"
TOKEN_URL = OIDC_BASE + "/token"
LOGOUT_URL = OIDC_BASE + "/logout"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

# Catalogue (public, needs only the account header). Paginated, newest first; tagNames filters by namespaced tag.
CONTENT_URL = "https://api.tennistv.com/content/atpmedia/VIDEO/EN"
PAGE_SIZE = 30
LANG = "EN"

# Search returns hits carrying a numeric objectId; resolve it to a mediaGuid via CONTENT_URL/<id>.
SEARCH_URL = "https://api.tennistv.com/search/v2/atpmedia"

# Browse-by-year lists content tagged year:<YYYY>, from the current year back to this floor.
EARLIEST_YEAR = 2016

# Players: BIO content lists the featured players, each carrying an ATP_PLAYER reference; a player's videos come
# from CONTENT_URL filtered by references=ATP_PLAYER:<sid>.
PLAYERS_URL = "https://api.tennistv.com/content/atpmedia/BIO/EN"
# Tournaments: the calendar lists a season's events (date-range filtered); each id+year makes the
# references=ATP_TOURNAMENT:<id>_<year> filter for that tournament's videos.
TOURNAMENTS_URL = "https://api.tennistv.com/tennis/v1/tournaments"
# Watchlist: the account's saved videos. The endpoint returns HTTP 415 without an explicit JSON content type.
WATCHLIST_URL = "https://api.tennistv.com/favoritemedia"

# Match info overlay: the ATP data behind the web player's side panels, all public (account header only).
# A match video's references carry ATP_MATCH:<tid>_<year>_<matchId> and two ATP_PLAYER:<sid>, which key these.
MATCH_STATS_URL = "https://api.tennistv.com/tennis/v1/tournaments/{tid}/{year}/matches/{match_id}/stats"
DRAW_URL = "https://api.tennistv.com/tennis/v1/tournaments/{tid}/{year}/draws"
H2H_URL = "https://api.tennistv.com/tennis/v1/players/{p1}/headtohead/{p2}"
DAY = 60 * 60 * 24  # how long a finished match's data is kept: it never changes
# A live court feed has no ATP_MATCH reference, only its tournament and court; the matches in progress (with their
# CourtId) say which match is on that court now.
LIVE_MATCHES_URL = "https://api.tennistv.com/tennis/v1/matches?status=L"
# The web player's live panel (Ease Live): a public, time-stamped event timeline per match (score, point by point,
# serve, stats, insights, momentum), which the overlay replays in step with the video. See timeline.py.
# The bare /events URL can be a stale CDN copy (one cached mid-match was still served the next day), so, like the
# web overlay, ask for the program's last update first and request /events?to=<it>: a new URL whenever it changes.
TIMELINE_URL = "https://atptennis-cdn.cloud.easelive.tv/api/v1/programs/ATP-{year}-{tid}-{match_id}"
# Key Moments are PlayAnywhere video clips (in the same overlay): an anonymous token for the Tennis TV web app code,
# then the clips of the PlayAnywhere event that the timeline names.
PLAYANYWHERE_TOKEN_URL = "https://gwpa.prod.playanywhere.com/ws/api/v1/token"
PLAYANYWHERE_CLIPS_URL = "https://gwpa.prod.playanywhere.com/ws/api/v1/video/{event_id}"
PLAYANYWHERE_APP = "PA-TENNISTV-WEB"

# Playback: a per-video entitlement token, then the StreamAMG entry endpoint returns the manifest URL.
ENTITLEMENT_URL = "https://api.tennistv.com/entitlementcheck/v1/videoentitlements/{guid}"
PLAYBACK_API = "https://api.playback.streamamg.com/v1"
# Public web-app key embedded in tennistv.com's JS bundle; identifies the StreamAMG tenant. Baked in as a
# fallback only - api.py re-derives the live value from the site if the operator rotates it (see _streamamg_key).
STREAMAMG_API_KEY = "c5Oe6Cr857oLlsCFY8Bm3djiu4Cw8zo6ckD2ucI7"
# Where the key is published, used to self-heal on rotation: homepage -> current bundle URL -> playbackAPIKey.
SITE_URL = "https://www.tennistv.com/"
BUNDLE_RE = r"/resources/v[0-9.]+/scripts/bundle-es\.min\.js"
API_KEY_RE = r'playbackAPIKey:"([^"]+)"'

# Home menu: (title, tagNames filter, bundled icon). Each lists VOD newest first with pagination.
CATEGORIES = (
    ("Match Highlights", "video-type:match-highlights", "clips"),
    ("Extended Highlights", "video-type:extended-match-highlights", "clips"),
    ("Daily Highlights", "video-type:daily-highlights", "clips"),
    ("Short Highlights", "video-type:short-highlights", "clips"),
    ("Hot Shots", "video-type:hotshots", "clips"),
    ("Replays", "video-type:replay", "replays"),
    ("Features", "video-type:features", "shows"),
    ("Interviews", "video-type:interviews", "shows"),
    ("Doubles", "match-type:doubles", "sports"),
)

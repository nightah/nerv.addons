import os
from time import gmtime

import xbmc
import xbmcgui
from slyguy import gui, inputstream, plugin, signals, userdata
from slyguy.constants import ADDON_PATH, PLAY_FROM_ASK, PLAY_FROM_LIVE, PLAY_FROM_START
from slyguy.log import log

from . import timeline
from .api import API
from .constants import CATEGORIES, DAY, EARLIEST_YEAR, USER_AGENT
from .language import _
from .settings import settings

api = API()

# Resume a few seconds before the stop point, so the playback startup buffer plays back up to where it stopped
RESUME_BUFFER = 5
# "From start" seeks back from the live edge; a magnitude beyond any match length lands at the DVR window start
SEEK_TO_START = 86400


@signals.on(signals.BEFORE_DISPATCH)
def before_dispatch():
    api.new_session()
    plugin.logged_in = api.logged_in


@plugin.route("")
def home(**kwargs):
    folder = plugin.Folder(cacheToDisc=False)

    if not api.logged_in:
        folder.add_item(label=_(_.LOGIN, _bold=True), art=_icon("account"), path=plugin.url_for(login), bookmark=False)
    else:
        folder.add_item(label=_.LIVE, art=_icon("live"), path=plugin.url_for(category, tag="live", title=_.LIVE))
        folder.add_item(label=_.TOURNAMENTS, art=_icon("tournaments"), path=plugin.url_for(tournaments))
        folder.add_item(label=_.PLAYERS, art=_icon("players"), path=plugin.url_for(players))

        for title, tag, icon in CATEGORIES:
            folder.add_item(label=title, art=_icon(icon), path=plugin.url_for(category, tag=tag, title=title))

        folder.add_item(label=_.BROWSE_BY_YEAR, art=_icon("calendar"), path=plugin.url_for(years))
        folder.add_item(label=_.SEARCH, art=_icon("search"), path=plugin.url_for(search))
        folder.add_item(label=_.WATCHLIST, art=_icon("watchlist"), path=plugin.url_for(watchlist))
        folder.add_item(
            label=_.MATCH_INFO_BUTTON,
            art=_icon("settings"),
            path=plugin.url_for(match_info_button),
            _kiosk=False,
            bookmark=False,
        )

        folder.add_item(label=_.LOGOUT, art=_icon("account"), path=plugin.url_for(logout), _kiosk=False, bookmark=False)

    folder.add_item(
        label=_.SETTINGS,
        art=_icon("settings"),
        path=plugin.url_for(plugin.ROUTE_SETTINGS),
        _kiosk=False,
        bookmark=False,
    )
    return folder


@plugin.route()
def login(**kwargs):
    data = api.device_code()
    expires = int(data.get("expires_in", 600))
    interval = max(int(data.get("interval", 5)), 1)

    # Scanning the QR opens the verification page with the code already filled in.
    qr = data.get("verification_uri_complete") or data["verification_uri"]
    monitor = xbmc.Monitor()
    with gui.progress_qr(
        qr, _(_.DEVICE_CODE, url=data["verification_uri"], code=data["user_code"]), heading=_.LOGIN
    ) as progress:
        for elapsed in range(expires):
            # Wait through the monitor, not time.sleep: a raw sleep blocks the interpreter without yielding to
            # Kodi, which drops the dialog after a beat while this loop keeps polling (the code only flashes up).
            if progress.iscanceled() or monitor.waitForAbort(1):
                return

            progress.update(int(elapsed * 100 / expires))
            if elapsed % interval == 0 and api.device_login(data["device_code"]):
                break
        else:
            return

    gui.refresh()


@plugin.route()
def logout(**kwargs):
    if not gui.yes_no(_.LOGOUT_YES_NO):
        return

    api.logout()
    gui.refresh()


@plugin.route()
@plugin.login_required()
def category(tag=None, references=None, title=None, page=0, **kwargs):
    page = int(page)
    folder = plugin.Folder(title, content="videos")

    items, info = api.content(tag=tag, references=references, page=page)
    folder.add_items([x for x in (_parse_item(item) for item in items) if x])

    if page + 1 < int(info.get("numPages") or 0):
        nav = {"references": references} if references else {"tag": tag}
        folder.add_item(
            label=_(_.NEXT_PAGE, page=page + 2),
            art=_icon("folder"),
            path=plugin.url_for(category, title=title, page=page + 1, **nav),
        )

    return folder


@plugin.route()
@plugin.login_required()
def tournaments(**kwargs):
    folder = plugin.Folder(_.TOURNAMENTS)
    for year in range(gmtime().tm_year, EARLIEST_YEAR - 1, -1):
        folder.add_item(label=str(year), art=_icon("tournaments"), path=plugin.url_for(tournament_year, year=year))
    return folder


@plugin.route()
@plugin.login_required()
def tournament_year(year, **kwargs):
    year = int(year)
    folder = plugin.Folder(str(year))
    for tourn in api.tournaments(year):
        folder.add_item(
            label=tourn.get("name"),
            art=_icon("tournaments"),
            path=plugin.url_for(category, references=f"ATP_TOURNAMENT:{tourn['id']}_{year}", title=tourn.get("name")),
        )
    return folder


@plugin.route()
@plugin.login_required()
def players(**kwargs):
    folder = plugin.Folder(_.PLAYERS)
    for player in api.players():
        folder.add_item(
            label=player["name"],
            art=_player_art(player["sid"]),
            path=plugin.url_for(category, references="ATP_PLAYER:" + player["sid"], title=player["name"]),
        )
    return folder


@plugin.route()
@plugin.login_required()
def watchlist(**kwargs):
    folder = plugin.Folder(_.WATCHLIST, content="videos")
    folder.add_items([x for x in (_parse_item(item) for item in api.watchlist()) if x])
    return folder


@plugin.route()
@plugin.login_required()
def years(**kwargs):
    folder = plugin.Folder(_.BROWSE_BY_YEAR)
    for year in range(gmtime().tm_year, EARLIEST_YEAR - 1, -1):
        folder.add_item(
            label=str(year),
            art=_icon("calendar"),
            path=plugin.url_for(category, tag=f"year:{year}", title=str(year)),
        )
    return folder


@plugin.route()
@plugin.search()
def search(query, page, **kwargs):
    items = [x for x in (_search_item(data) for data in api.search(query)) if x]
    return items, False


def _search_item(data):
    other = data.get("otherFields") or {}
    info = {"plot": other.get("description") or "", "mediatype": "video"}
    duration = other.get("duration")
    if duration and duration.isdigit() and int(duration) > 0:
        info["duration"] = int(duration)

    return plugin.Item(
        label=data.get("title"),
        art={"thumb": data.get("imageUrl")},
        info=info,
        playable=True,
        path=plugin.url_for(play, video_id=data.get("objectId")),
    )


@plugin.route()
@plugin.login_required()
def play(media_guid=None, video_id=None, match=None, **kwargs):
    # Search results carry a numeric video_id; catalogue items carry a mediaGuid directly.
    if not media_guid and video_id:
        content = api.content_by_id(video_id)
        media_guid = content.get("mediaGuid")
        if not match:
            match = _match_ref(content)

    # Make the match this video belongs to available to the Match Info overlay (empty for non-match videos).
    _set_match_context(match)

    # Match feeds and alternate angles are live events that can be joined live, watched from the start, or resumed;
    # the live play action setting decides, or asks. The ask prompt comes before the playback calls so a cancel
    # costs nothing. (The 24/7 channel is linear, so it is not marked seekable and always joins live.)
    seekable = bool(kwargs.get("seekable"))
    choice = _live_choice(media_guid) if seekable else None
    if seekable and choice is None:
        return

    media = api.play(media_guid)["media"]
    is_dash = bool(media.get("dash"))
    # The overlay reads the HLS program date-times to follow the video (the DASH of a highlight has the same timing).
    xbmcgui.Window(10000).setProperty("tennistv.hls", _timing_playlist(media.get("hls")) if match else "")

    callback = None
    if match and not seekable:
        # SlyGuy's player runs an "interval" callback as soon as playback starts: it fetches what the Match Info
        # overlay needs into the shared cache, so the overlay opens (and follows a seek) without waiting. A live
        # feed's callback saves its resume point instead, and its live data is fetched when the overlay opens.
        callback = {"type": "interval", "interval": DAY, "callback": plugin.url_for(prefetch, match=match)}
    if seekable:
        # Remember the position so the event can be resumed if it is stopped and reopened
        callback = {
            "type": "interval_ts",
            "interval": 300,
            "callback": plugin.url_for(live_callback, resume_guid=media_guid),
        }

    item = plugin.Item(
        path=media["dash"] if is_dash else media["hls"],
        headers={"User-Agent": USER_AGENT},
        inputstream=inputstream.MPD() if is_dash else inputstream.HLS(),
        callback=callback,
    )

    if seekable:
        play_type, resume_target = choice
        if resume_target is not None:
            # SlyGuy forces no_resume on live items, which drops the resume point; clearing it (and force_resume,
            # to skip Kodi's own resume prompt) lets a positive resume_from through as an absolute Kodi ResumeTime.
            item.no_resume = False
            item.force_resume = True
            item.resume_from = resume_target
        elif play_type == PLAY_FROM_START:
            # A negative resume point seeks back from the live edge to the start of the DVR window
            item.resume_from = -SEEK_TO_START

    # On the first match played, offer to bind a button for the overlay (no global keymap is shipped).
    if match and not userdata.get("match_info_asked"):
        userdata.set("match_info_asked", True)
        from .keybind import prompt_first_run

        prompt_first_run()

    return item


def _live_choice(media_guid):
    # Returns (play_type, resume_target) for a live event, or None if the user cancelled the ask prompt.
    play_type = settings.LIVE_PLAY_TYPE.value

    saved = userdata.get("resume") or {}
    resume_pos = int(saved["pos"]) if saved.get("guid") == media_guid and saved.get("pos") else None

    if play_type != PLAY_FROM_ASK:
        return play_type, None

    options = [_.JOIN_LIVE, _.FROM_START]
    can_resume = resume_pos is not None and resume_pos > 0
    if can_resume:
        options.append(_.RESUME)

    index = gui.context_menu(options)
    if index == -1:
        return None
    if can_resume and index == 2:
        return PLAY_FROM_LIVE, max(resume_pos - RESUME_BUFFER, 0)
    return (PLAY_FROM_START if index == 1 else PLAY_FROM_LIVE), None


@plugin.route()
def live_callback(resume_guid=None, **kwargs):
    # Fired on an interval during live playback and once more when playback stops (with _time as the stop position),
    # so the last-watched position of a live event is kept for Resume.
    if not resume_guid:
        return

    player = xbmc.Player()
    if player.isPlaying():
        try:
            pos, total = int(player.getTime()), int(player.getTotalTime())
            # getTime can briefly misread while seeking, so ignore values outside the DVR window
            if 0 <= pos <= total + 30:
                userdata.set("resume", {"guid": resume_guid, "pos": pos})
        except Exception:
            pass
    else:
        stop_pos = int(kwargs.get("_time") or 0)
        if stop_pos > 0:
            userdata.set("resume", {"guid": resume_guid, "pos": stop_pos})


def _icon(name):
    # Bundled icons have a solid background so they stay visible on skin focus highlights
    path = os.path.join(ADDON_PATH, "resources", "media", f"{name}.png")
    return {"thumb": path, "icon": path}


def _player_art(sid):
    # Headshots are vendored by ATP sid (see tools/tennistv-headshots); fall back to the generic icon if missing.
    path = os.path.join(ADDON_PATH, "resources", "media", "players", f"{sid}.png")
    if os.path.exists(path):
        return {"thumb": path, "icon": path}
    return _icon("players")


def _parse_item(item):
    media_guid = item.get("mediaGuid")
    if not media_guid:
        return None

    is_live = (item.get("additionalInfo") or {}).get("islive") == "true"
    # The "Tennis TV 24/7" classics channel is a linear feed with no start to seek to; every other live entry is an
    # event stream (match feed or alternate angle) that supports Join Live / From Start / Resume.
    seekable = is_live and (item.get("metadata") or {}).get("court") != "CLASSICS_FEED"

    info = {"plot": item.get("description") or "", "mediatype": "video"}
    if item.get("duration"):
        info["duration"] = int(item["duration"])
    if item.get("date"):
        info["aired"] = item["date"][:10]

    match = _match_ref(item)

    return plugin.Item(
        label=item.get("title"),
        art={"thumb": item.get("thumbnailUrl") or item.get("imageUrl")},
        info=info,
        playable=True,
        path=plugin.url_for(
            play,
            media_guid=media_guid,
            match=match,
            _is_live=is_live,
            seekable=1 if seekable else None,
        ),
    )


def _timing_playlist(hls):
    # The master playlist's token expires within a minute of playback starting, but the variant it points to carries
    # a session token that lasts about a day, so resolve the variant now for the overlay to read later.
    if not hls:
        return ""
    try:
        return timeline.variant_url(api.playlist(hls), hls) or hls
    except Exception:  # playback does not depend on it; the overlay then falls back to its unsynced view
        return hls


def _match_ref(item):
    # A match video's references carry ATP_MATCH:<tid>_<year>_<matchId>. A live court feed only knows its tournament
    # and court, so it gets "court:<tid>_<year>:<court>", resolved to the match on that court when the overlay opens
    # (the match changes through the day).
    refs = item.get("references") or []
    match = next((r.get("sid") for r in refs if r.get("type") == "ATP_MATCH" and r.get("sid")), None)
    if match:
        return match
    tournament = next((r.get("sid") for r in refs if r.get("type") == "ATP_TOURNAMENT" and r.get("sid")), None)
    court = str((item.get("metadata") or {}).get("court") or "")
    return f"court:{tournament}:{court}" if tournament and court.isdigit() else None


def _set_match_context(match):
    # Stash the playing match on the home window so the Match Info overlay (a separate invocation) can read it.
    win = xbmcgui.Window(10000)
    if match:
        win.setProperty("tennistv.match", match)
    else:
        win.clearProperty("tennistv.match")


@plugin.route()
def prefetch(match=None, **kwargs):
    # Playback callback (start, and stop): warm the cache for the Match Info overlay.
    from .matchinfo import prefetch as warm

    warm(api, match, xbmcgui.Window(10000).getProperty("tennistv.hls"))


@plugin.route()
def match_info(**kwargs):
    # Opened by the user's Match Info key while a match is playing: the live stats, draw and key moments overlay.
    win = xbmcgui.Window(10000)
    match = win.getProperty("tennistv.match") if xbmc.Player().isPlaying() else ""
    if match.startswith("court:"):
        tid_year, court = match[len("court:") :].rsplit(":", 1)
        try:
            match = api.live_match(*tid_year.split("_", 1), court)
        except Exception as e:  # no lookup, no overlay: say so rather than raise an error dialog
            log.debug(f"Match Info: live match lookup failed ({e})")
            match = None
    if not match:
        gui.notification(_.NO_MATCH_INFO)
        return

    from .matchinfo import MatchInfo

    MatchInfo.show(api, match, win.getProperty("tennistv.hls"))


@plugin.route()
@plugin.login_required()
def match_info_button(**kwargs):
    # Bind, change or clear the button that opens the overlay during playback.
    from .keybind import bind, clear, is_bound

    if is_bound():
        index = gui.context_menu([_.BIND_CHANGE, _.BIND_CLEAR])
        if index == 0:
            bind()
        elif index == 1:
            clear()
    else:
        bind()

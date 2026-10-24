import codecs
import json
import os
import sys
from time import time
from xml.sax.saxutils import escape, quoteattr

import arrow
from kodi_six import xbmc
from six.moves.urllib_parse import parse_qsl, urlencode, urlparse, urlunparse
from slyguy import gui, inputstream, plugin, signals, userdata
from slyguy.constants import (
    ADDON_ICON,
    ADDON_PATH,
    NO_RESUME_TAG,
    PLAY_FROM_ASK,
    PLAY_FROM_LIVE,
    PLAY_FROM_START,
    ROUTE_LIVE_TAG,
    ROUTE_RESUME_TAG,
    ROUTE_SETTINGS,
    ROUTE_TAG,
)
from slyguy.log import log
from slyguy.util import async_tasks

from .api import API, uncap_manifest
from .constants import (
    BRAND,
    CHANNEL_NUMBERS,
    IMAGE_URL,
    LINEAR_IMAGES,
    LOGIN_EMAIL,
    QR_POLL_INTERVAL,
    QR_TIMEOUT,
    RESUME_MIN,
    TIMESHIFT_DEFAULT,
    TIMESHIFT_MARGIN,
    USER_AGENT,
)
from .language import _
from .settings import settings

api = API()

# Resume a few seconds before the last position, so the playback startup buffer plays back up to where it stopped
RESUME_BUFFER = 3


# SlyGuy gives items it builds itself (settings, search history) its default thumb, which is the addon icon
DEFAULT_THUMBS = {ROUTE_SETTINGS: "settings", "search": "search"}


@signals.on(signals.BEFORE_DISPATCH)
def before_dispatch():
    api.new_session()
    plugin.logged_in = api.logged_in

    route = dict(parse_qsl(urlparse(sys.argv[2] if len(sys.argv) > 2 else "").query)).get(ROUTE_TAG, "")
    icon = DEFAULT_THUMBS.get(route)
    plugin.default_thumb = _icon(icon)["thumb"] if icon else ADDON_ICON


@plugin.route("")
def home(**kwargs):
    folder = plugin.Folder(cacheToDisc=False)

    if not api.logged_in:
        folder.add_item(label=_(_.LOGIN, _bold=True), art=_icon("account"), path=plugin.url_for(login), bookmark=False)
    else:
        folder.add_item(
            label=_(_.LIVE_CHANNELS, _bold=True), art=_icon("live_channels"), path=plugin.url_for(live_channels)
        )
        folder.add_item(
            label=_(_.FEATURED, _bold=True),
            art=_icon("featured"),
            path=plugin.url_for(page, group="Home", params="PageType:Home;ContentType:None", title=_.FEATURED),
        )
        folder.add_item(
            label=_(_.SPORTS, _bold=True), art=_icon("sports"), path=plugin.url_for(rail, id="Sport", title=_.SPORTS)
        )
        folder.add_item(
            label=_(_.SHOWS, _bold=True),
            art=_icon("shows"),
            path=plugin.url_for(page, group="Shows", params="PageType:Shows;ContentType:None", title=_.SHOWS),
        )
        folder.add_item(label=_(_.SEARCH, _bold=True), art=_icon("search"), path=plugin.url_for(search))

        if settings.getBool("bookmarks", True):
            folder.add_item(
                label=_(_.BOOKMARKS, _bold=True),
                art=_icon("bookmarks"),
                path=plugin.url_for(plugin.ROUTE_BOOKMARKS),
                bookmark=False,
            )

        profile = api.profile()
        folder.add_item(
            label=_.SELECT_PROFILE,
            art={"thumb": profile["avatar"]} if profile.get("avatar") else _icon("account"),
            info={"plot": profile.get("name")},
            path=plugin.url_for(select_profile),
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
    if not (_login_email() if settings.LOGIN_METHOD.value == LOGIN_EMAIL else _login_qr()):
        return

    # Signed in either way, so a profile problem shouldn't undo that
    try:
        _select_profile()
    except Exception as e:
        log.warning(f"Kayo profile selection failed: {e}")

    gui.refresh()


def _login_email():
    username = gui.input(_.ASK_EMAIL, default=userdata.get("username", "")).strip()
    if not username:
        return False

    userdata.set("username", username)

    password = gui.input(_.ASK_PASSWORD, hide_input=True).strip()
    if not password:
        return False

    api.login(username, password)
    return True


def _login_qr():
    from .qr import progress_qr

    data = api.device_code()
    # Shown without the scheme so it fits on one line of the dialog
    url = data["url"].split("://", 1)[-1]
    monitor = xbmc.Monitor()
    with progress_qr(data["url"], _(_.QR_HELP, url=url), heading=_.LOGIN) as progress:
        for elapsed in range(QR_TIMEOUT):
            # Wait through the monitor, not time.sleep: a raw sleep blocks the interpreter without yielding to
            # Kodi, which drops the dialog after a beat while this loop keeps polling (the code only flashes up).
            if progress.iscanceled() or monitor.waitForAbort(1):
                return False

            progress.update(int(elapsed * 100 / QR_TIMEOUT))
            if elapsed % QR_POLL_INTERVAL == 0 and api.device_login(data["id"]):
                return True

    gui.ok(_.QR_EXPIRED)
    return False


@plugin.route()
@plugin.login_required()
def select_profile(**kwargs):
    if _select_profile():
        gui.refresh()


def _select_profile():
    # Returns True when a profile was chosen; with a single profile it is just recorded
    profiles = api.profiles()
    if not profiles:
        return False

    current = api.profile().get("id")
    if len(profiles) == 1:
        index = 0
    else:
        options = [
            plugin.Item(label=x.get("profileName") or x["profileId"], art={"thumb": x.get("avatar")}) for x in profiles
        ]
        preselect = next((i for i, x in enumerate(profiles) if x["profileId"] == current), 0)
        index = gui.select(_.SELECT_PROFILE, options=options, preselect=preselect, useDetails=True)
        if index < 0:
            return False

    profile = profiles[index]
    api.switch_profile(profile)
    if len(profiles) > 1:
        gui.notification(_.PROFILE_ACTIVATED, heading=profile.get("profileName"), icon=profile.get("avatar"))
    return True


@plugin.route()
def logout(**kwargs):
    if not gui.yes_no(_.LOGOUT_YES_NO):
        return

    api.logout()
    gui.refresh()


@plugin.route()
@plugin.login_required()
def live_channels(**kwargs):
    folder = plugin.Folder(_.LIVE_CHANNELS)
    folder.add_items(_parse_tiles(api.live_channels()))
    return folder


@plugin.route()
@plugin.login_required()
def page(group, params, title=None, **kwargs):
    folder = plugin.Folder(title, content="videos")

    rows = [x for x in api.rails(group, params) if x["Id"] != "ContinueWatching"]
    tasks = [lambda x=x: api.rail(x["Id"], params=x.get("Params") or "", service=x.get("Service")) for x in rows]
    results = async_tasks(tasks, raise_on_error=False)

    for row, data in zip(rows, results):
        if isinstance(data, Exception) or not data.get("Tiles") or data.get("Type") == "Hero":
            continue

        folder.add_item(
            label=data.get("Title") or row["Id"],
            art=_rail_art(data),
            path=plugin.url_for(
                rail, id=row["Id"], params=row.get("Params") or "", service=row.get("Service"), title=data.get("Title")
            ),
        )

    return folder


@plugin.route()
@plugin.login_required()
def rail(id, params="", service="Rail", title=None, **kwargs):
    data = api.rail(id, params=params, service=service)
    folder = plugin.Folder(title or data.get("Title"), content="videos")
    folder.add_items(_parse_tiles(data.get("Tiles", [])))
    return folder


def _channels():
    return [x for x in api.live_channels() if x.get("AssetId")]


@plugin.route()
@plugin.merge()
def playlist(output, **kwargs):
    with codecs.open(output, "w", encoding="utf8") as f:
        f.write("#EXTM3U")

        for tile in _channels():
            title = tile.get("Title") or ""
            # No group-title: IPTV Merge already groups an addon's channels under the addon name
            f.write(
                '\n#EXTINF:-1 tvg-id="{id}" tvg-chno="{chno}" tvg-name="{name}" tvg-logo="{logo}",{name}\n{url}'.format(
                    id=tile["AssetId"],
                    chno=CHANNEL_NUMBERS.get(title.lower(), ""),
                    name=title,
                    logo=_channel_logo(tile),
                    url=plugin.url_for(play, asset_id=tile["AssetId"], _is_live=True),
                )
            )


@plugin.route()
@plugin.merge()
def epg(output, **kwargs):
    # Kayo's live channel rail includes each channel's schedule (now, next and ~2.5 days later)
    def xmltv_time(value):
        return arrow.get(value).format("YYYYMMDDHHmmss Z")

    with codecs.open(output, "w", encoding="utf8") as f:
        f.write('<?xml version="1.0" encoding="utf-8" ?><tv>')

        channels = _channels()
        for tile in channels:
            f.write(
                "<channel id={}><display-name>{}</display-name><icon src={}/></channel>".format(
                    quoteattr(tile["AssetId"]), escape(tile.get("Title") or ""), quoteattr(_channel_logo(tile))
                )
            )

        for tile in channels:
            schedule = tile.get("LinearSchedule") or {}
            for row in [schedule.get("Now"), schedule.get("Next")] + (schedule.get("Later") or []):
                if not row or not row.get("Start") or not row.get("End"):
                    continue

                f.write(
                    '<programme channel={} start="{}" stop="{}"><title>{}</title>'.format(
                        quoteattr(tile["AssetId"]),
                        xmltv_time(row["Start"]),
                        xmltv_time(row["End"]),
                        escape(row.get("Title") or ""),
                    )
                )

                if row.get("EpisodeTitle"):
                    f.write("<sub-title>{}</sub-title>".format(escape(row["EpisodeTitle"])))
                if row.get("Description"):
                    f.write("<desc>{}</desc>".format(escape(row["Description"])))
                for genre in row.get("Genre") or []:
                    if genre.get("name"):
                        f.write("<category>{}</category>".format(escape(genre["name"])))

                icon = _image(row.get("BackgroundImage"), 1280, 720, folder=LINEAR_IMAGES) or _image(
                    row.get("Image"), 600, 900, folder=LINEAR_IMAGES
                )
                if icon:
                    f.write(f"<icon src={quoteattr(icon)}/>")

                f.write("</programme>")

        f.write("</tv>")


@plugin.route()
@plugin.search()
def search(query, page, **kwargs):
    items = []
    for row in api.search(query):
        items.extend(_parse_tiles(row.get("Tiles", [])))
    return items, False


# Bundled icons for rails with generic titles, checked in order
RAIL_ICONS = (
    ("channel", "live_channels"),
    ("live", "live"),
    ("upcoming", "live"),
    ("replay", "replays"),
    ("minis", "clips"),
    ("bites", "clips"),
    ("shorts", "clips"),
    ("show", "shows"),
    ("inside the game", "shows"),
    ("competitor", "competitors"),
    ("competition", "sports"),
    ("sport", "sports"),
)


def _icon(name, wide=False):
    # Bundled icons have a solid background so they stay visible on skin focus highlights
    path = os.path.join(ADDON_PATH, "resources", "media", "{}{}.png".format(name, "_wide" if wide else ""))
    return {"thumb": path, "icon": path}


def _rail_art(data):
    title = (data.get("Title") or "").lower()
    for keyword, name in RAIL_ICONS:
        if keyword in title:
            return _icon(name, wide=True)

    # Named rails (eg. a match or series) get the artwork of their first item
    for tile in data.get("Tiles", []):
        image = _image(tile.get("Image"), 1280, 720)
        if image:
            return {"thumb": image}

    return _icon("folder", wide=True)


def _add_query(url, **params):
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True) + list(params.items())
    return urlunparse(parsed._replace(query=urlencode(query)))


def _parse_tiles(tiles):
    return [x for x in (_parse_tile(tile) for tile in tiles) if x]


def _image(image, width, height, folder="jp"):
    if not image or not image.get("Id"):
        return None

    ext = "png" if image.get("ImageMimeType") == "png" else "jpg"
    # Schedule image IDs contain ':' which must stay unencoded, the image server returns a placeholder for %3A
    return IMAGE_URL.format(folder=folder, id=image["Id"], width=width, height=height, ext=ext)


def _channel_logo(tile):
    return _image(tile.get("LogoImage"), 512, 512, folder=LINEAR_IMAGES) or _image(tile.get("Image"), 1280, 720) or ""


def _parse_tile(tile):
    title = tile.get("Title")
    art = {"thumb": _image(tile.get("Image"), 1280, 720), "fanart": _image(tile.get("BackgroundImage"), 1920, 1080)}

    nav_params = tile.get("NavParams")
    if tile.get("Type") == "Navigation":
        if not nav_params:
            return None

        group = dict(x.split(":", 1) for x in nav_params.split(";") if ":" in x).get("PageType")
        if not group:
            return None

        art["thumb"] = art["thumb"] or _image(tile.get("LogoImage"), 512, 512)
        return plugin.Item(
            label=title,
            art=art,
            info={"plot": tile.get("Description")},
            path=plugin.url_for(page, group=group, params=nav_params, title=title),
        )

    if not tile.get("AssetId"):
        return None

    start = arrow.get(tile["Start"]) if tile.get("Start") else None
    is_live = tile.get("Type") == "Live"
    is_upcoming = tile.get("Type") == "UpComing"

    label = title
    if is_live and not tile.get("IsLinear"):
        label = _(_.LIVE, _bold=True) + " " + title
    elif is_upcoming and start:
        label = "{} [{}]".format(title, start.to("local").format("ddd D MMM h:mma"))

    plot = tile.get("Description") or ""
    if tile.get("Label"):
        plot = "[B]{}[/B]\n{}".format(tile["Label"], plot)

    info = {"plot": plot, "mediatype": "video"}
    if start and not tile.get("IsLinear"):
        info["aired"] = start.to("local").format("YYYY-MM-DD")

    duration = int((tile.get("DurationInMillis") or 0) / 1000) if not is_live and not is_upcoming else 0
    if duration:
        info["duration"] = duration

    return plugin.Item(
        label=label,
        art=art,
        info=info,
        playable=True,
        path=plugin.url_for(
            play,
            asset_id=tile["AssetId"],
            start=tile.get("Start") if is_upcoming or (is_live and not tile.get("IsLinear")) else None,
            duration=duration or None,
            _is_live=is_live,
            # Kayo's resume points (shared with its apps) are used instead of Kodi's own; live items always skip it
            **{NO_RESUME_TAG: True},
        ),
    )


def _stream_start(data):
    # The epoch the stream's timeline starts at, which can be a few minutes after the tile's scheduled Start
    start_from = int((data.get("ResumePoints") or {}).get("StartFrom") or 0)
    if start_from > 24 * 60 * 60:
        return start_from

    start = (data.get("Asset") or {}).get("StartTime")
    return int(arrow.get(start).datetime.timestamp()) if start else 0


def _resume_position(data, start_from):
    # Seconds into the stream to resume at, or 0. A replay's ResumeFrom is an offset (Kayo already takes 10 seconds
    # off it); a live event's is the epoch it was stopped at, as Kayo's apps store it (see playback_callback).
    position = int((data.get("ResumePoints") or {}).get("ResumeFrom") or 0)
    if position > 24 * 60 * 60:
        position = position - start_from if start_from else 0
    return position if position >= RESUME_MIN else 0


def _timeshift_limit(data, start_from):
    # Covers the event's scheduled length, or how long it has run if it is overrunning, plus room to overrun
    asset = data.get("Asset") or {}
    scheduled = 0
    if asset.get("StartTime") and asset.get("EndTime"):
        scheduled = (arrow.get(asset["EndTime"]) - arrow.get(asset["StartTime"])).total_seconds()
        # Linear channels end in the year 3000
        if scheduled > 24 * 60 * 60:
            scheduled = 0

    elapsed = time() - start_from if start_from else 0
    return int(max(scheduled, elapsed) + TIMESHIFT_MARGIN)


@plugin.route()
@plugin.login_required()
def play(asset_id, start=None, duration=None, **kwargs):
    if start and arrow.get(start) > arrow.utcnow():
        gui.ok(_(_.NOT_STARTED, start=arrow.get(start).to("local").humanize()))
        return

    is_live = bool(kwargs.get(ROUTE_LIVE_TAG))
    # Live events (not linear channels) carry their start, and keep the whole event in the DVR window, so they can
    # be joined live, watched from the start, or resumed from where they were last stopped
    is_event = is_live and bool(start)
    offset = int((arrow.utcnow() - arrow.get(start)).total_seconds()) if is_event else 0
    duration = int(duration or 0)

    data = api.play(asset_id)
    details = data["PlaybackDetails"][0]
    start_from = _stream_start(data) if is_event else 0
    resume_pos = _resume_position(data, start_from) if is_event or not is_live else 0

    play_type = PLAY_FROM_LIVE
    resume_target = None
    if offset > 0:
        play_type = settings.LIVE_PLAY_TYPE.value
        if play_type == PLAY_FROM_ASK:
            options = [_.JOIN_LIVE, _.FROM_START]
            can_resume = 0 < resume_pos < time() - start_from
            if can_resume:
                options.append(_.RESUME)

            index = gui.context_menu(options)
            if index == -1:
                api.release_lock()
                return

            play_type = PLAY_FROM_START if index == 1 else PLAY_FROM_LIVE
            if can_resume and index == 2:
                resume_target = max(resume_pos - RESUME_BUFFER, 0)

    elif not is_live and resume_pos and not kwargs.get(ROUTE_RESUME_TAG):
        # Skip a resume point at the very end, which is a replay watched to the finish. ROUTE_RESUME_TAG means Kodi
        # already resumed from its own bookmark (an item added before Kayo's resume points were used).
        if not duration or resume_pos < duration - RESUME_MIN:
            resume_target = plugin.resume_from(resume_pos)
            if resume_target == -1:
                api.release_lock()
                return

    # The CDN token has to be on the manifest and on every segment request
    token = details.get("CdnToken") or {}
    # Akamai tokens contain '#' and '=', so the value must be URL encoded or it gets cut off at the '#'
    token_param = urlencode({token["Name"]: token["Value"]}) if token.get("Name") else ""
    manifest_url = uncap_manifest(details["ManifestUrl"])
    if token_param:
        manifest_url = _add_query(manifest_url, **{token["Name"]: token["Value"]})

    properties = {}
    if token_param:
        properties["stream_params"] = token_param

    if is_event:
        limit = _timeshift_limit(data, start_from)
        if limit > TIMESHIFT_DEFAULT:
            properties["manifest_config"] = json.dumps({"timeshift_bufferlimit": limit})

    lock_interval = int((data.get("PlaybackLock") or {}).get("UpdateLockIntervalSeconds") or 0)
    interval = max(lock_interval - 15, 30)

    # Linear channels have no position worth keeping, so only events and replays post resume points
    callback_url = plugin.url_for(playback_callback)
    if is_event or not is_live:
        asset = data.get("Asset") or {}
        callback_url = plugin.url_for(
            playback_callback,
            asset_id=asset_id,
            video_type="LIVE" if is_live else "VOD",
            start_from=start_from or None,
            duration=duration or None,
            event_id=asset.get("EventId"),
            asset_type_id=(asset.get("Type") or {}).get("Id"),
        )
        update = int((data.get("ResumePoints") or {}).get("UpdateInterval") or 0)
        if update:
            interval = max(min(interval, update), 30)

    item = plugin.Item(
        path=manifest_url,
        headers={"User-Agent": USER_AGENT},
        inputstream=inputstream.Widevine(
            license_key=details["LaUrl"],
            license_headers={"User-Agent": USER_AGENT, "X-BRAND": BRAND, "X-DAZNID": userdata.get("dazn_id", "")},
            properties=properties,
        ),
        callback={"type": "interval_ts", "interval": interval, "callback": callback_url},
        use_proxy=True,
    )

    if resume_target:
        # SlyGuy forces no_resume on live items (and Kayo items skip Kodi's resume), which drops the resume point;
        # clearing it (and force_resume, to skip Kodi's own resume prompt) lets a positive resume_from through as a
        # real Kodi ResumeTime, seeking to resume_target seconds from the start of the stream. Unlike the live-edge
        # seek-back, this is an absolute position, so it lands exactly regardless of how long playback took to start.
        item.no_resume = False
        item.force_resume = True
        item.resume_from = resume_target
    elif play_type == PLAY_FROM_START:
        # A negative resume point seeks back from the live edge to the start of the event
        item.resume_from = -offset

    return item


@plugin.route()
def playback_callback(asset_id=None, video_type=None, start_from=0, duration=0, **kwargs):
    # Called on an interval during playback and once more when playback stops
    player = xbmc.Player()
    playing = player.isPlaying()
    if playing:
        api.refresh_lock()
    else:
        api.release_lock()

    if not asset_id:
        return

    if playing:
        try:
            position, total = int(player.getTime()), int(player.getTotalTime())
        except Exception:
            return
        # getTime can briefly misread while seeking, so ignore values outside the stream
        if not 0 <= position <= total + 30:
            return
    else:
        # The stop callback forwards the exact getTime at the stop point
        position, total = int(kwargs.get("_time") or 0), 0

    if position <= 0:
        return

    if video_type == "LIVE":
        # Kayo's apps store a live event's position as the epoch it was stopped at
        position += int(start_from or 0)
        length = position + 5
    else:
        length = max(total, int(duration or 0), position)

    api.resume_point(
        asset_id,
        position,
        length,
        video_type,
        event_id=kwargs.get("event_id"),
        asset_type_id=kwargs.get("asset_type_id"),
    )

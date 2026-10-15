import codecs
import os
import sys
from xml.sax.saxutils import escape, quoteattr

import arrow
from kodi_six import xbmc
from six.moves.urllib_parse import parse_qsl, urlencode, urlparse, urlunparse
from slyguy import gui, inputstream, plugin, signals, userdata
from slyguy.constants import ADDON_ICON, ADDON_PATH, ROUTE_SETTINGS, ROUTE_TAG
from slyguy.util import async_tasks

from .api import API
from .constants import BRAND, CHANNEL_NUMBERS, IMAGE_URL, LINEAR_IMAGES, USER_AGENT
from .language import _
from .settings import settings

api = API()


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
    username = gui.input(_.ASK_EMAIL, default=userdata.get("username", "")).strip()
    if not username:
        return

    userdata.set("username", username)

    password = gui.input(_.ASK_PASSWORD, hide_input=True).strip()
    if not password:
        return

    api.login(username, password)
    gui.refresh()


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

    return plugin.Item(
        label=label,
        art=art,
        info=info,
        playable=True,
        path=plugin.url_for(
            play, asset_id=tile["AssetId"], start=tile.get("Start") if is_upcoming else None, _is_live=is_live
        ),
    )


@plugin.route()
@plugin.login_required()
def play(asset_id, start=None, **kwargs):
    if start and arrow.get(start) > arrow.utcnow():
        gui.ok(_(_.NOT_STARTED, start=arrow.get(start).to("local").humanize()))
        return

    data = api.play(asset_id)
    details = data["PlaybackDetails"][0]

    # The CDN token has to be on the manifest and on every segment request
    token = details.get("CdnToken") or {}
    # Akamai tokens contain '#' and '=', so the value must be URL encoded or it gets cut off at the '#'
    token_param = urlencode({token["Name"]: token["Value"]}) if token.get("Name") else ""
    manifest_url = (
        _add_query(details["ManifestUrl"], **{token["Name"]: token["Value"]}) if token_param else details["ManifestUrl"]
    )

    properties = {}
    if token_param:
        properties["stream_params"] = token_param

    lock_interval = int((data.get("PlaybackLock") or {}).get("UpdateLockIntervalSeconds") or 0)

    return plugin.Item(
        path=manifest_url,
        headers={"User-Agent": USER_AGENT},
        inputstream=inputstream.Widevine(
            license_key=details["LaUrl"],
            license_headers={"User-Agent": USER_AGENT, "X-BRAND": BRAND, "X-DAZNID": userdata.get("dazn_id", "")},
            properties=properties,
        ),
        callback={
            "type": "interval_ts",
            "interval": max(lock_interval - 15, 30),
            "callback": plugin.url_for(lock_callback),
        }
        if lock_interval
        else None,
        use_proxy=True,
    )


@plugin.route()
def lock_callback(**kwargs):
    # Called on an interval during playback and once more when playback stops
    if xbmc.Player().isPlaying():
        api.refresh_lock()
    else:
        api.release_lock()

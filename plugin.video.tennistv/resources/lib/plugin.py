import os
import time
from time import gmtime

from slyguy import gui, inputstream, plugin, signals
from slyguy.constants import ADDON_PATH

from .api import API
from .constants import CATEGORIES, EARLIEST_YEAR, USER_AGENT
from .language import _

api = API()


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
        for title, tag, icon in CATEGORIES:
            folder.add_item(label=title, art=_icon(icon), path=plugin.url_for(category, tag=tag, title=title))

        folder.add_item(label=_.BROWSE_BY_YEAR, art=_icon("calendar"), path=plugin.url_for(years))
        folder.add_item(label=_.SEARCH, art=_icon("search"), path=plugin.url_for(search))

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

    with gui.progress(
        _(_.DEVICE_CODE, url=data["verification_uri"], code=data["user_code"]), heading=_.LOGIN
    ) as progress:
        for elapsed in range(expires):
            if progress.iscanceled():
                return

            progress.update(int(elapsed * 100 / expires))
            if elapsed % interval == 0 and api.device_login(data["device_code"]):
                break

            time.sleep(1)
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
def category(tag, title=None, page=0, **kwargs):
    page = int(page)
    folder = plugin.Folder(title, content="videos")

    items, info = api.content(tag, page=page)
    folder.add_items([x for x in (_parse_item(item) for item in items) if x])

    if page + 1 < int(info.get("numPages") or 0):
        folder.add_item(
            label=_(_.NEXT_PAGE, page=page + 2),
            art=_icon("folder"),
            path=plugin.url_for(category, tag=tag, title=title, page=page + 1),
        )

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
def play(media_guid=None, video_id=None, **kwargs):
    # Search results carry a numeric video_id; catalogue items carry a mediaGuid directly.
    if not media_guid and video_id:
        media_guid = api.content_by_id(video_id).get("mediaGuid")

    media = api.play(media_guid)["media"]
    is_dash = bool(media.get("dash"))
    return plugin.Item(
        path=media["dash"] if is_dash else media["hls"],
        headers={"User-Agent": USER_AGENT},
        inputstream=inputstream.MPD() if is_dash else inputstream.HLS(),
    )


def _icon(name):
    # Bundled icons have a solid background so they stay visible on skin focus highlights
    path = os.path.join(ADDON_PATH, "resources", "media", f"{name}.png")
    return {"thumb": path, "icon": path}


def _parse_item(item):
    media_guid = item.get("mediaGuid")
    if not media_guid:
        return None

    info = {"plot": item.get("description") or "", "mediatype": "video"}
    if item.get("duration"):
        info["duration"] = int(item["duration"])
    if item.get("date"):
        info["aired"] = item["date"][:10]

    return plugin.Item(
        label=item.get("title"),
        art={"thumb": item.get("thumbnailUrl") or item.get("imageUrl")},
        info=info,
        playable=True,
        path=plugin.url_for(play, media_guid=media_guid),
    )

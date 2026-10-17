import os
import time

from slyguy import gui, inputstream, plugin, signals
from slyguy.constants import ADDON_PATH

from .api import API
from .constants import CATEGORIES, USER_AGENT
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
def play(media_guid, **kwargs):
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

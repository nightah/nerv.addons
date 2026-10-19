import contextlib
import os

import xbmc
import xbmcgui
import xbmcvfs
from slyguy import gui
from slyguy.constants import ADDON_ID, ADDON_PATH

from .language import _

# A user keymap (special://profile/keymaps) overrides nothing by default and is removed when the user clears it.
KEYMAP_PATH = f"special://profile/keymaps/{ADDON_ID}.xml"
ACTION = f"RunPlugin(plugin://{ADDON_ID}/?_=match_info)"
CANCEL = (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK)

KEYMAP_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<keymap>\n"
    "    <FullscreenVideo>\n"
    "        <keyboard>\n"
    '            <key id="{code}">{action}</key>\n'
    "        </keyboard>\n"
    "    </FullscreenVideo>\n"
    "</keymap>\n"
)


class _Capture(xbmcgui.WindowXMLDialog):
    def onInit(self):
        self.code = None
        with contextlib.suppress(Exception):
            self.getControl(100).setLabel(_.BIND_PRESS)

    def onAction(self, action):
        if action.getId() in CANCEL:
            self.close()
            return
        code = action.getButtonCode()
        if code:
            self.code = code
            self.close()


def is_bound():
    return xbmcvfs.exists(KEYMAP_PATH)


def _capture_code():
    dialog = _Capture("BindKey.xml", ADDON_PATH, "Default", "1080i")
    dialog.doModal()
    code = dialog.code
    del dialog
    return code


def bind():
    # Capture the next button press and write it as a FullscreenVideo binding, applied live.
    code = _capture_code()
    if not code:
        return False
    path = xbmcvfs.translatePath(KEYMAP_PATH)
    xbmcvfs.mkdirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write(KEYMAP_XML.format(code=code, action=ACTION))
    xbmc.executebuiltin("Action(reloadkeymaps)")
    gui.notification(_.BIND_DONE)
    return True


def clear():
    if is_bound():
        xbmcvfs.delete(KEYMAP_PATH)
        xbmc.executebuiltin("Action(reloadkeymaps)")
    gui.notification(_.BIND_CLEARED)


def prompt_first_run():
    # Offered once, when the first match is played, so the overlay has a button without a global keymap.
    if gui.yes_no(_.BIND_PROMPT):
        bind()

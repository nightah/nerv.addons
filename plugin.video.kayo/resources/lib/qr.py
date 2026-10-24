import contextlib
import hashlib
import os
import re
import struct
import xml.etree.ElementTree as ET
import zlib

import xbmc
import xbmcgui
import xbmcvfs
from slyguy import gui
from slyguy.log import log

from .qrcodegen import QrCode

# Pixels per QR module, and the light margin (in modules) scanners need around the code
MODULE_PX = 8
QUIET_ZONE = 4
# Kodi's progress dialog, which every skin draws from DialogConfirm.xml, and its message textbox
PROGRESS_WINDOW = 10101
PROGRESS_XML = "DialogConfirm.xml"
TEXT_ID = 9
# Space between the message and the QR, in skin units
GAP = 20
# Arctic Fuse 3 builds DialogConfirm.xml from includes (Dialog_DialogConfirm.xml): a 1280x600 panel centred on the
# screen with 40 padding, and a 320 wide right column holding the progress bar and Cancel (an 80 tall row) with room
# below. The QR goes in that room.
FUSE_3 = "skin.arctic.fuse.3"
FUSE_3_PANEL = (1280, 600)
FUSE_3_PAD = 40
FUSE_3_COLUMN = 320
FUSE_3_BUTTONS = 80
FUSE_3_QR = 240
# Fallback when the skin's dialog can't be measured: where SlyGuy's progress_qr puts the code (x, y and size, in
# 1280x720 coordinates)
FALLBACK = (5, 200, 324)


def _png(data, path):
    qr = QrCode.encode_text(data, QrCode.Ecc.MEDIUM)
    modules = range(-QUIET_ZONE, qr.get_size() + QUIET_ZONE)
    side = len(modules) * MODULE_PX
    rows = b""
    for y in modules:
        # 8-bit RGB (Kodi 21 on GLES, eg. LibreELEC, draws a greyscale PNG as nothing): each row is a filter byte
        # (0, none) then three bytes per pixel, black for a dark module.
        row = b"\x00" + b"".join((b"\x00" * 3 if qr.get_module(x, y) else b"\xff" * 3) * MODULE_PX for x in modules)
        rows += row * MODULE_PX

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(rows, 9)))
        f.write(chunk(b"IEND", b""))


def _square(height, coords_w, coords_h):
    # The width that shows as square: Kodi stretches a window's coordinates to fill the screen, so on a screen wider
    # than the coordinates' aspect a square in coordinate units shows up wide.
    w, h = xbmcgui.getScreenWidth(), xbmcgui.getScreenHeight()
    return int(height * (coords_w * h) / (coords_h * w)) if w and h else height


def _length(value, total):
    value = (value or "").strip()
    if value.endswith("%"):
        return total * float(value[:-1]) / 100
    return float(value)


def _place(group, start, end, middle, size, total):
    # A control's offset along one axis from Kodi's left/right/centerleft (or top/bottom/centertop) and width
    # (or height); raises ValueError when the skin sets them through an include or "auto".
    length = _length(group.findtext(size), total)
    if group.findtext(middle):
        return _length(group.findtext(middle), total) - length / 2
    if group.findtext(start):
        return _length(group.findtext(start), total)
    if group.findtext(end):
        return total - _length(group.findtext(end), total) - length
    return 0


def _dialog_origin(coords_w, coords_h):
    # The progress dialog's controls sit in an outer group, and Python only sees positions relative to that group,
    # so the group's own position is read from the skin's DialogConfirm.xml.
    skin = xbmcvfs.translatePath("special://skin/")
    with open(os.path.join(skin, "addon.xml"), encoding="utf-8") as f:
        addon = f.read()
    folders = re.findall(r'<res\b[^>]*\bwidth="(\d+)"[^>]*\bheight="(\d+)"[^>]*\bfolder="([^"]+)"', addon)
    folder = next((d for w, h, d in folders if (int(w), int(h)) == (coords_w, coords_h)), None)
    if folder is None:
        raise ValueError(f"no skin folder for {coords_w}x{coords_h}")
    group = ET.parse(os.path.join(skin, folder, PROGRESS_XML)).getroot().find("controls/control[@type='group']")
    if group is None:
        raise ValueError("no outer group")
    x = _place(group, "left", "right", "centerleft", "width", coords_w)
    y = _place(group, "top", "bottom", "centertop", "height", coords_h)
    return x, y


def _beside_message(window, coords_w, coords_h):
    # Right of the message and as tall, with the message narrowed to make room; returns the image's box and the
    # message's own width to restore.
    gx, gy = _dialog_origin(coords_w, coords_h)
    text = window.getControl(TEXT_ID)
    tx, ty, tw, th = text.getX(), text.getY(), text.getWidth(), text.getHeight()
    size = _square(th, coords_w, coords_h)
    return (int(gx + tx + tw - size), int(gy + ty), size, th), (text, tw, tw - size - GAP)


def _fuse_3(coords_w, coords_h):
    # Centred in the right column's free space, between the Cancel row and the panel's bottom padding.
    width = _square(FUSE_3_QR, coords_w, coords_h)
    right = (coords_w + FUSE_3_PANEL[0]) / 2 - FUSE_3_PAD
    top = (coords_h - FUSE_3_PANEL[1]) / 2 + FUSE_3_PAD + FUSE_3_BUTTONS
    space = FUSE_3_PANEL[1] - 2 * FUSE_3_PAD - FUSE_3_BUTTONS
    return int(right - (FUSE_3_COLUMN + width) / 2), int(top + (space - FUSE_3_QR) / 2), width, FUSE_3_QR


@contextlib.contextmanager
def _attach(path):
    # The QR is added to the skin's own progress dialog: at a known spot for Arctic Fuse 3, otherwise at the right
    # of the message. If the dialog can't be measured it goes where SlyGuy's progress_qr puts it (left of the
    # screen), still in the same window so the dialog keeps focus.
    window = xbmcgui.Window(PROGRESS_WINDOW)
    coords_w, coords_h = window.getWidth(), window.getHeight()
    try:
        if xbmc.getSkinDir() == FUSE_3:
            box, (text, width, narrowed) = _fuse_3(coords_w, coords_h), (None, None, None)
        else:
            box, (text, width, narrowed) = _beside_message(window, coords_w, coords_h)
    except Exception:
        log.debug("QR: can't measure the skin's progress dialog, showing the code at the side", exc_info=True)
        x, y, size = FALLBACK
        size = int(size * coords_h / 720)
        box = (int(x * coords_w / 1280), int(y * coords_h / 720), _square(size, coords_w, coords_h), size)
        text = width = narrowed = None
    image = xbmcgui.ControlImage(*box, path)
    window.addControl(image)
    if text:
        text.setWidth(narrowed)
    try:
        yield
    finally:
        # The dialog window is reused by every progress dialog, so it is put back as the skin had it.
        with contextlib.suppress(RuntimeError):
            window.removeControl(image)
            if text:
                text.setWidth(width)


@contextlib.contextmanager
def progress_qr(data, message, heading):
    """Like SlyGuy's gui.progress_qr, but with the QR inside the skin's progress dialog (SlyGuy draws it in a
    separate window at a fixed spot), and drawn here instead of fetched from api.qrserver.com, which would send the
    sign-in code to a third party (over plain HTTP)."""
    # Named after the data so Kodi's texture cache never serves the previous sign-in's code.
    name = hashlib.sha1(data.encode()).hexdigest()
    path = os.path.join(xbmcvfs.translatePath("special://temp/"), f"kayo-qr-{name}.png")
    _png(data, path)

    try:
        with gui.progress(message, heading=heading) as progress, _attach(path):
            yield progress
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)

import contextlib
import hashlib
import os
import struct
import zlib

import xbmcgui
import xbmcvfs
from slyguy import gui

from .matchinfo import x_scale
from .qrcodegen import QrCode

# Where SlyGuy's progress_qr puts the code, in the 1280x720 coordinates of a Python window
QR_X, QR_Y, QR_SIZE = 5, 200, 324
# Pixels per QR module, and the light margin (in modules) scanners need around the code
MODULE_PX = 8
QUIET_ZONE = 4


def _png(data, path):
    qr = QrCode.encode_text(data, QrCode.Ecc.MEDIUM)
    modules = range(-QUIET_ZONE, qr.get_size() + QUIET_ZONE)
    side = len(modules) * MODULE_PX
    rows = b""
    for y in modules:
        # 8-bit greyscale: each row is a filter byte (0, none) then one byte per pixel, black for a dark module.
        row = b"\x00" + b"".join((b"\x00" if qr.get_module(x, y) else b"\xff") * MODULE_PX for x in modules)
        rows += row * MODULE_PX

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 0, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(rows, 9)))
        f.write(chunk(b"IEND", b""))


@contextlib.contextmanager
def progress_qr(data, message, heading):
    """Like SlyGuy's gui.progress_qr, but the QR is drawn here instead of fetched from api.qrserver.com, which
    would send the sign-in code to a third party (over plain HTTP)."""
    # Named after the data so Kodi's texture cache never serves the previous sign-in's code.
    name = hashlib.sha1(data.encode()).hexdigest()
    path = os.path.join(xbmcvfs.translatePath("special://temp/"), f"tennistv-qr-{name}.png")
    _png(data, path)

    window = xbmcgui.WindowDialog()
    # Narrowed on wider screens so it stays square.
    window.addControl(xbmcgui.ControlImage(QR_X, QR_Y, int(QR_SIZE * x_scale()), QR_SIZE, path))
    window.show()
    try:
        with gui.progress(message, heading=heading) as progress:
            yield progress
    finally:
        window.close()
        with contextlib.suppress(OSError):
            os.remove(path)

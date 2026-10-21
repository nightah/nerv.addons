import contextlib
import functools
import os
import re
import struct
import threading
import time

import xbmc
import xbmcgui
from slyguy.constants import ADDON_PATH
from slyguy.log import log

from . import keybind, timeline
from .language import _

# Section tabs / sub-tabs / toggles (ids in MatchInfo.xml)
SEC_LIVE, SEC_DRAW, SEC_KEY = 10, 11, 12
SUB_STATS, SUB_INSIGHTS, SUB_H2H = 13, 14, 15
SET_BASE, SET_MAX = 30, 5
ROUND_BASE, ROUND_MAX = 40, 7
BODY_ID, REVEAL_ID, KEY_NOTE_ID = 50, 60, 81
SECTIONS = (SEC_LIVE, SEC_DRAW, SEC_KEY)
SUBS = (SUB_STATS, SUB_INSIGHTS, SUB_H2H)
# Section tab label widths in Estuary's font10 on a 16:9 screen; the tabs are spaced evenly from these.
SEC_TEXT = {SEC_LIVE: 102, SEC_DRAW: 58, SEC_KEY: 148}
SUB_X = {SUB_STATS: 1524, SUB_INSIGHTS: 1650, SUB_H2H: 1776}
# The section tabs share the top row with the ATP+ logo (no title above them: the selected tab says where you are).
TABS_Y, LINE_Y, TAB_MIN_GAP = 24, 58, 10  # tab row top, the underline under it, the least gap between tabs
TAB_TEXT_FIT = 0.95  # rendered tab label width / SEC_TEXT estimate (measured on device)
SUB_Y, SUB_H = 66, 38
SET_GAP, SET_H = 8, 36

POLL_SECONDS = 15
SYNC_SECONDS = 2  # how often a timeline-synced overlay follows the video

# Each view's controls are shown by a window property (skin <visible> or setVisibleCondition), so a whole view
# appears in one frame once it is fully built and filled in, instead of control by control.
HDR_PROP = "tennistv.header"
STATS_PROP = "tennistv.stats"
SPOILER_PROP = "tennistv.spoiler"
TEXT_PROP = "tennistv.text"
DRAW_PROP = "tennistv.draw"
FIX_PROP = "tennistv.fixtures"
CARD_PROP = "tennistv.card"  # the centre card's background, shared by the stats and head-to-head views
H2H_PROP = "tennistv.h2h"
INS_PROP = "tennistv.insights"
KEY_PROP = "tennistv.moments"
KEY_LIST = 80  # the Key Moments list (MatchInfo.xml)
OFFSCREEN = 4000

# Estuary's font10/12 are a thin ("lighten") weight; its small bold sizes match the mock. Other skins lack these
# names (an unknown font falls back to the large font13), so they use font10, which the labels then bold.
_ESTUARY = xbmc.getSkinDir() == "skin.estuary"
FONT_XS = "font_flag" if _ESTUARY else "font10"  # 18, bold
FONT_S = "font20_title" if _ESTUARY else "font10"  # 20, bold
FONT_M = "font25_title" if _ESTUARY else "font12"  # 25, bold
FONT_L = "font30_title" if _ESTUARY else "font13"  # 30, bold

TEAL = "FF2FB8AC"
BLUE = "FF4F9BE8"
DARK = "FF06110F"  # near-black text on a teal (selected) pill
P1_DIM, P2_DIM = "802FB8AC", "804F9BE8"
WHITE = "FFE6EAF0"
MUTED = "FF8A93A0"
CARD = "0AFFFFFF"  # mock --card rgba(255,255,255,.05), a touch darker as it reads lighter on a TV
TRACK = "0AFFFFFF"
LINE = "17FFFFFF"  # mock --line rgba(255,255,255,.09): the tab-row underline track
MID = "33FFFFFF"
LOSE = "59FFFFFF"  # dim white for the losing set score (mock: .n.lose opacity .35)
BAND = "1AFFFFFF"  # mock .sc-set rgba(255,255,255,.1): the FINISHED header band
ATP_LOGO_H = 18  # atp-plus.png is 195x44
OUTLINE, OUTLINE_R = "21FFFFFF", 8  # the card's outline colour and corner radius (corner-*.png)
BALL = "FFD6E23B"  # mock --ball: the games box and the serving ball
DOT_OFF = "1FFFFFFF"

# Layout (1920x1080): a thin right-hand panel. Vertical rhythm follows the mock.
CX, CW = 1524, 372
PANEL_BOTTOM = 1076  # the lowest y a view may draw to
ROUND_STEP = 56  # draw round buttons: 50 wide, 6 apart, left-aligned (MatchInfo.xml)
CENTRE = CX + CW // 2
LCOL, RCOL = CX + 60, CX + CW - 60  # player column centres
LVAL_X, LVAL_W = 1524, 70
NAME_X, NAME_W = 1598, 232
RVAL_X, RVAL_W = 1826, 70
HS_Y, HS = 120, 72  # headshot top (15px+ below the sub-tabs, as in the mock) and height
SET_Y = 336  # Match / Set n toggle row, low enough for the live card to grow a dot row per point of a long game
ROWS_Y = 348

# Centre score card: top aligned with the headshots, running past the flags.
CTR_X, CTR_W = 1676, 68
CARD_BG = 70  # the card's background (MatchInfo.xml)
SET_ROW_H, SET_DIV_H = 34, 16  # the finished card's set score label height and its divider
CARD_H, BAND_H = 148, 22
# Live card (web player style): white point box under the band, the current game's points as dots, a ball-yellow
# games box, then a hairline and the completed sets.
PT_H, GAMES_H, DONE_H = 22, 22, 38
# Point dots, one per player per row, the winner's lit: (dot size, row pitch), tighter for a long game.
DOT_LAYOUTS = ((12, 14), (10, 11), (9, 10))
DOT_POOL = 16  # the most rows the card can hold
DIV_H = 12  # the short muted divider line in "a | b" (mock .setsc .d), about the height of the digits
# Kodi centres a label on the font's full height, descender included, so digits sit high; this nudges them down.
DIGIT_NUDGE = 1
CARD_MAX = SET_Y - 6 - HS_Y  # the live card grows with each point down to just above the Match / Set row
BALL_D, BALL_OUT = 14, 34  # serving ball size, and its centre's offset from the headshot centre (down and outward)

BAR_HALF = CW // 2
AL_LEFT, AL_RIGHT, AL_CENTRE = 4, 5, 6

# Draw fixture cards: two stacked "flag Surname" rows with per-set games on the right, paged to fit the panel.
FX_Y, FX_H, FX_STEP = 138, 52, 56
FX_PAGE = (PANEL_BOTTOM - FX_Y) // FX_STEP
FX_SETS, FX_COL = 3, 20  # FX_COL: one digit plus a figure space (Noto's digits are all one width)
FIGURE_SPACE, FIGURE_DASH = "\u2007", "\u2012"  # digit-wide space and dash, so the games columns line up
FX_NAME_W = CW - 20 - FX_SETS * FX_COL - 8
BYE = "BYE"  # the draw's marker for a bye (shown as _.DRAW_BYE)
PAGE_NEXT = {xbmcgui.ACTION_MOVE_DOWN, xbmcgui.ACTION_PAGE_DOWN, xbmcgui.ACTION_MOUSE_WHEEL_DOWN}
PAGE_PREV = {xbmcgui.ACTION_PAGE_UP, xbmcgui.ACTION_MOUSE_WHEEL_UP}

SERVICE_ROWS = (
    (_.STAT_ACES, "Aces"),
    (_.STAT_DOUBLE_FAULTS, "DoubleFaults"),
    (_.STAT_FIRST_SERVE, "FirstServe"),
    (_.STAT_FIRST_SERVE_WON, "FirstServePointsWon"),
    (_.STAT_SECOND_SERVE_WON, "SecondServePointsWon"),
    (_.STAT_BREAK_SAVED, "BreakPointsSaved"),
    (_.STAT_SERVICE_GAMES, "ServiceGamesPlayed"),
)
RETURN_ROWS = (
    (_.STAT_FIRST_RETURN_WON, "FirstServeReturnPointsWon"),
    (_.STAT_SECOND_RETURN_WON, "SecondServeReturnPointsWon"),
    (_.STAT_BREAK_CONVERTED, "BreakPointsConverted"),
    (_.STAT_RETURN_GAMES, "ReturnGamesPlayed"),
)
POINT_ROWS = (
    (_.STAT_SERVICE_POINTS, "TotalServicePointsWon"),
    (_.STAT_RETURN_POINTS, "TotalReturnPointsWon"),
    (_.STAT_TOTAL_POINTS, "TotalPointsWon"),
)
GROUPS = (
    (_.STAT_SERVICE, "ServiceStats", SERVICE_ROWS),
    (_.STAT_RETURN, "ReturnStats", RETURN_ROWS),
    (_.STAT_POINTS, "PointStats", POINT_ROWS),
)
RATIO_KEYS = {"BreakPointsSaved", "BreakPointsConverted"}

# Head to head: comparison rows (no bars) and the past meetings as cards, below the player header.
H2H_Y, H2H_ROW = SET_Y, 28
H2H_VAL_W = 100
MEET_H, MEET_STEP = 52, 56

# Insights (timeline-synced): a momentum split, recent games, attack / defence and shot quality rows, then the
# balance of power strip.
INS_GAMES, SPLIT_H, GAME_H, GAME_STEP = 6, 28, 18, 22
LEAD_IN = 5  # seconds of play shown before a key moment when jumping to it


def _value(stat, key):
    # A stat as shown; early in a match the timeline's stats carry null values, which show as "-".
    if not isinstance(stat, dict):
        return "-"
    if key in RATIO_KEYS and stat.get("Dividend") is not None and stat.get("Divisor") is not None:
        return f"{stat['Dividend']}/{stat['Divisor']}"
    if stat.get("Percent") is not None:
        return f"{round(stat['Percent'])}%"
    if stat.get("Number") is not None:
        return str(stat["Number"])
    return "-"


def _numeric(stat):
    if not isinstance(stat, dict):
        return 0.0
    if "Percent" in stat:
        return float(stat.get("Percent") or 0)
    if "Number" in stat:
        return float(stat.get("Number") or 0)
    return 0.0


def _fills(g1, g2, n1, n2):
    if (isinstance(g1, dict) and "Percent" in g1) or (isinstance(g2, dict) and "Percent" in g2):
        return min(n1 / 100, 1.0), min(n2 / 100, 1.0)
    total = n1 + n2
    return (n1 / total, n2 / total) if total else (0.0, 0.0)


def _set_stats(team, set_num):
    sets = team.get("Sets") or []
    chosen = next((s for s in sets if s.get("SetNumber") == set_num), None)
    return (chosen or (sets[0] if sets else {})).get("Stats") or {}


def _media(*parts):
    return os.path.join(ADDON_PATH, "resources", "media", *parts)


def _tex(name):
    return os.path.join(ADDON_PATH, "resources", "skins", "Default", "media", name)


def _white():
    return _tex("white.png")


def _headshot(sid):
    path = _media("players", f"{sid}.png")
    return path if sid and os.path.exists(path) else None


def _flag(code):
    path = _media("flags", f"{(code or '').lower()}.png")
    return path if code and os.path.exists(path) else None


def _b(text):
    return f"[B]{text}[/B]"


def _set_score(left, right, a, b):
    # A set's games, the winner's in their colour and the loser's dimmed.
    left.setLabel(_b(f"[COLOR={TEAL if a > b else LOSE}]{a}[/COLOR]"))
    right.setLabel(_b(f"[COLOR={BLUE if b > a else LOSE}]{b}[/COLOR]"))


@functools.lru_cache(maxsize=None)
def _png_size(path):
    with open(path, "rb") as f:
        return struct.unpack(">II", f.read(24)[16:24])


def x_scale():
    # Kodi stretches the 1920x1080 skin to fill the screen, so on a wider screen (eg. 21:9) a square in skin units
    # shows up wide. Round headshots and flags are narrowed by this factor so they keep their shape.
    w, h = xbmcgui.getScreenWidth(), xbmcgui.getScreenHeight()
    return min(max((1920 * h) / (1080 * w), 0.5), 1.5) if w and h else 1.0


class MatchInfo(xbmcgui.WindowXMLDialog):
    @classmethod
    def show(cls, api, match_ref, hls=None):
        try:
            tid, year, match_id = match_ref.split("_", 2)
        except ValueError:
            return
        opened = time.time()
        stats = api.match_stats(tid, year, match_id) or {}
        # With the match timeline and the video's date-times the overlay follows the video, so it never runs ahead
        # of what has been watched. Without them, finished replays open hidden behind a Reveal button.
        sync = _Sync.load(api, (tid, year, match_id), hls, (stats.get("PlayerTeam1") or {}).get("PlayerId"))
        revealed = sync is not None or stats.get("Status") != "Finished"
        dialog = cls("MatchInfo.xml", ADDON_PATH, "Default", "1080i")
        dialog.setup(api, tid, year, match_id, revealed, stats, sync)
        dialog._h2h()  # the header needs it; loading it now means the overlay opens complete
        dialog._opened = (opened, time.time())
        dialog.doModal()
        dialog._stop.set()  # however it was closed, stop the background threads
        del dialog

    def setup(self, api, tid, year, match_id, revealed, stats, sync=None):
        self._api = api
        self._sync, self._state, self._state_key = sync, {}, None
        self._tid, self._year, self._match_id = tid, year, match_id
        self._revealed = revealed
        self._section, self._sub = SEC_LIVE, SUB_STATS
        self._set_num, self._round_idx, self._page, self._focus = 0, 0, 0, SEC_LIVE
        self._stop = threading.Event()
        self._cache = {"stats": stats}
        self._rows, self._set_map, self._built = [], {}, False
        self._round_ids, self._rounds_built, self._draw_pages, self._draw_shown = [], False, set(), None
        # Building and showing views happens on the GUI thread (clicks), the follow loop and the warm-up thread.
        self._lock = threading.RLock()
        self._h2h_ctrls, self._h2h_built = [], None
        self._pending = []
        self._opened = (time.time(), time.time())  # data load start / end, for the timing log (set by show())
        self._ins_built, self._moments, self._moments_loaded, self._moments_key = False, [], False, None
        self._draw_rounds, self._set_text, self._set_rect, self._jumps, self._lc = [], {}, {}, [], None
        self._refreshed, self._last_tick, self._lost, self._beat = 0.0, None, False, 0.0  # follow loop state

    # --- lifecycle ---

    def onInit(self):
        # Every conditional control is hidden by a window property until its view is ready (see _refresh).
        self._xs = x_scale()
        self._toggle = keybind.bound_code()
        self.getControl(SEC_LIVE).setLabel(_.SEC_LIVE_STATS)
        self.getControl(SEC_DRAW).setLabel(_.TAB_DRAW)
        self.getControl(SEC_KEY).setLabel(_.SEC_KEY)
        self.getControl(SUB_STATS).setLabel(_b(_.TAB_STATS), font=FONT_S)
        self.getControl(SUB_INSIGHTS).setLabel(_b(_.SUB_INSIGHTS), font=FONT_S)
        self.getControl(SUB_H2H).setLabel(_b(_.SUB_H2H), font=FONT_S)
        self.getControl(REVEAL_ID).setLabel(_b(_.REVEAL))
        # The ATP+ mark from the web player's panel header, narrowed on a wide screen like the headshots, at the right
        # of the tab row when the tabs still fit beside it (on a 16:9 screen they need the whole width).
        logo_w = round(ATP_LOGO_H * 195 / 44 * self._xs)
        if self._layout_sections(CW - logo_w - 12):
            logo_y = TABS_Y + (32 - ATP_LOGO_H) // 2  # centred on the tab row
            self._mk(xbmcgui.ControlImage(CX + CW - logo_w, logo_y, logo_w, ATP_LOGO_H, _tex("atp-plus.png")))
        # Section-tab underline: a full-width dim track with a teal segment under the active tab.
        self._mk(xbmcgui.ControlImage(CX, LINE_Y, CW, 2, _white(), colorDiffuse=f"0x{LINE}"))
        self._sec_ind = self._mk(
            xbmcgui.ControlImage(
                self._sec_x[SEC_LIVE], LINE_Y, self._sec_w[SEC_LIVE], 2, _white(), colorDiffuse=f"0x{TEAL}"
            )
        )
        # Persistent "selected" pill overlays (teal bg + dark label) for the active sub-tab and the active set.
        self._sub_hl = (
            self._mk(
                xbmcgui.ControlImage(SUB_X[SUB_STATS], SUB_Y, 120, SUB_H, _tex("pill.png"), colorDiffuse=f"0x{TEAL}")
            ),
            self._mk(
                xbmcgui.ControlLabel(
                    SUB_X[SUB_STATS],
                    SUB_Y,
                    120,
                    SUB_H,
                    _b(_.TAB_STATS),
                    font=FONT_S,
                    textColor=DARK,
                    alignment=AL_CENTRE,
                )
            ),
        )
        self._set_hl = (
            self._gate(
                xbmcgui.ControlImage(CX, SET_Y, 118, SET_H, _tex("pill.png"), colorDiffuse=f"0x{TEAL}"), STATS_PROP
            ),
            self._gate(
                xbmcgui.ControlLabel(CX, SET_Y, 118, SET_H, "", font=FONT_S, textColor=DARK, alignment=AL_CENTRE),
                STATS_PROP,
            ),
        )
        self._rnd_hl = (
            self._gate(
                xbmcgui.ControlImage(CX, SUB_Y, 50, SUB_H, _tex("pill50.png"), colorDiffuse=f"0x{TEAL}"), DRAW_PROP
            ),
            self._gate(
                xbmcgui.ControlLabel(CX, SUB_Y, 50, SUB_H, "", font=FONT_S, textColor=DARK, alignment=AL_CENTRE),
                DRAW_PROP,
            ),
        )
        # The spoiler note: one centred line per sentence above the Reveal button, as in the mock.
        for i, line in enumerate(_sentences(_.SPOILER_PROMPT)):
            self._gate(
                xbmcgui.ControlLabel(
                    CX, SET_Y + i * 22, CW, 22, line, font="font10", textColor=MUTED, alignment=AL_CENTRE
                ),
                SPOILER_PROP,
            )
        if self._sync:
            self._state = self._sync.state()
        self._build_header()
        self._flush()
        with self._lock:
            try:
                self._set_section(SEC_LIVE)
            except Exception:  # a bad first draw must not stop the overlay following the video
                log.debug("Match Info: first draw failed", exc_info=True)
        log.debug(
            f"Match Info: data {self._opened[1] - self._opened[0]:.2f}s, drawn {time.time() - self._opened[1]:.2f}s"
            + (
                f", synced at {self._sync.position():.0f}s (timeline {self._sync.now()})"
                if self._sync
                else ", not synced"
            )
        )
        threading.Thread(target=self._poll, daemon=True).start()
        threading.Thread(target=self._warm, daemon=True).start()

    def onAction(self, action):
        with self._lock:
            self._on_action(action)

    def _on_action(self, action):
        aid = action.getId()
        # Kodi moves focus before this runs, so remember where focus was to tell "down onto the rounds" from
        # "down from the rounds".
        prev = self._focus
        with contextlib.suppress(RuntimeError):
            self._focus = self.getFocusId()
        # The Match Info key toggles: pressed again while the overlay is open, it closes it.
        toggled = self._toggle is not None and action.getButtonCode() == self._toggle
        if toggled or aid in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_STOP):
            self.close()
        elif prev in self._round_ids and self._pages() > 1 and (aid in PAGE_NEXT or aid in PAGE_PREV):
            # Long rounds are paged: down / page down / wheel for the next page (wrapping), page up for the previous.
            self._page = (self._page + (1 if aid in PAGE_NEXT else -1)) % self._pages()
            self._render_draw()

    def onClick(self, cid):
        with self._lock:
            self._on_click(cid)

    def _on_click(self, cid):
        if cid == KEY_LIST:
            self._jump()
        elif cid == REVEAL_ID:
            self._revealed = True
            self._refresh()
            with contextlib.suppress(RuntimeError):
                self.setFocusId(SUB_STATS)
        elif cid in SECTIONS:
            self._set_section(cid)
        elif cid in SUBS:
            self._sub = cid
            self._refresh()
        elif cid in self._set_map:
            self._set_num = self._set_map[cid]
            self._refresh()
        elif cid in self._round_ids:
            self._round_idx, self._page = self._round_ids.index(cid), 0
            self._refresh()

    def _warm(self):
        # Once Live Stats is on screen, build the other views hidden (H2H, Insights, the first Draw page) and load Key
        # Moments, so switching to them is only a property flip. The data is fetched first, outside the lock; each
        # build then takes it, so a click waits at most for one build, never for the network.
        try:
            self._h2h()
            self._draw()
            moments = self._fetch_moments() if self._sync else None
        except Exception:  # warming is an optimisation; the views still fetch and build on demand
            log.debug("Match Info: warming the data failed", exc_info=True)
            return
        steps = [self._warm_h2h, self._warm_insights, self._warm_draw]
        if moments is not None:
            steps.append(lambda: self._moments_loaded or self._set_moments(moments))
        for step in steps:
            if self._stop.is_set():
                return
            with self._lock:
                try:
                    step()
                except Exception:  # warming is an optimisation; the views still build on demand
                    log.debug("Match Info: warming a view failed", exc_info=True)

    def _warm_h2h(self):
        data = self._h2h()
        if data.get("Player") and data.get("Opponent") and self._h2h_built != self._revealed:
            self._build_h2h()

    def _warm_insights(self):
        if self._sync and not self._ins_built:
            self._build_insights()

    def _warm_draw(self):
        if not self._rounds_built:
            self._build_rounds()
        if self._draw_rounds:
            self._build_draw_page(0, 0)

    def close(self):
        self._stop.set()
        super().close()

    # --- build (programmatic controls) ---

    def _mk(self, control):
        self.addControl(control)
        return control

    def _gate(self, control, prop):
        # Stage a control that shows only while the window property is set. Staged controls are added together by
        # _flush(), off-screen, and moved home once their condition is attached, so none shows for a frame on its own.
        x, y = control.getPosition()
        control.setPosition(x + OFFSCREEN, y)
        self._pending.append((control, prop, x, y))
        return control

    def _flush(self):
        # One addControls call for everything staged: every call into Kodi waits for its GUI lock, so adding a view's
        # few hundred controls one by one is what made the overlay slow to appear.
        if not self._pending:
            return
        pending, self._pending = self._pending, []
        self.addControls([c for c, _prop, _x, _y in pending])
        for control, prop, x, y in pending:
            control.setVisibleCondition(f"String.IsEqual(Window.Property({prop}),1)")
            control.setPosition(x, y)

    def _stat(self, control):
        # Revealed-only controls (score card, stat rows): shown with the stats view.
        return self._gate(control, STATS_PROP)

    def _card(self, control):
        # Score card: shown under every Live Stats sub-tab once revealed, as on the web player.
        return self._gate(control, CARD_PROP)

    def _hdr(self, control):
        # Player header: shown in the stats view even before Reveal (it gives nothing away), as in the mock.
        return self._gate(control, HDR_PROP)

    def _layout_sections(self, room):
        # Space the section tabs evenly across room (or the whole width when they do not fit in it): the same gap
        # before, between and after the labels. Each button is its label plus half a gap either side, laid out from
        # the left. Text keeps its shape on a wide screen, so it takes fewer skin units there. Returns whether room
        # was used.
        widths = {sec: SEC_TEXT[sec] * self._xs for sec in SECTIONS}
        fits = sum(widths.values()) + 4 * TAB_MIN_GAP <= room
        gap = ((room if fits else CW) - sum(widths.values())) / 4
        x = CX  # the first button starts at the panel edge; its label is centred in it
        self._sec_x, self._sec_w = {}, {}
        for sec in SECTIONS:
            button = round(widths[sec] + gap)
            self.getControl(sec).setWidth(button)
            # The underline matches the label, which renders a little narrower than estimated (Estuary's light weight).
            line = round(widths[sec] * TAB_TEXT_FIT)
            self._sec_x[sec], self._sec_w[sec] = x + (button - line) // 2, line
            x += button
        return fits

    def _ensure_built(self):
        if not self._built:
            self._built = True
            self._build_centre()
            self._build_rows()
            self._build_set_toggle()
            self._flush()

    def _build_header(self):
        data = self._h2h()
        pl, op = data.get("Player") or {}, data.get("Opponent") or {}
        p1, p2 = self._player_ids()
        hw = round(HS * self._xs)
        for col, sid, person, accent in ((LCOL, p1, pl, TEAL), (RCOL, p2, op, BLUE)):
            # Circular headshot: photo, then a navy mask hiding the square corners, then a coloured ring.
            shot = _headshot(sid)
            if shot:
                inset = round(2 * self._xs)
                self._hdr(xbmcgui.ControlImage(col - hw // 2 + inset, HS_Y + 2, hw - 2 * inset, HS - 4, shot))
            self._hdr(xbmcgui.ControlImage(col - hw // 2, HS_Y, hw, HS, _tex("circle-mask.png")))
            self._hdr(xbmcgui.ControlImage(col - hw // 2, HS_Y, hw, HS, _tex("ring.png"), colorDiffuse=f"0x{accent}"))
            last = person.get("LastName") or ""
            first = person.get("FirstName") or ""
            code = person.get("NatlId") or ""
            # Bold surname over a smaller first name, then flag + code (mock .ln / .fn / .fc).
            self._hdr(
                xbmcgui.ControlLabel(
                    col - 72, HS_Y + 76, 144, 30, _b(last), font=FONT_M, textColor=WHITE, alignment=AL_CENTRE
                )
            )
            self._hdr(
                xbmcgui.ControlLabel(
                    col - 66, HS_Y + 104, 132, 22, first, font=FONT_XS, textColor=MUTED, alignment=AL_CENTRE
                )
            )
            # Flag + code centred together under the name (4:3 rectangular flag).
            flag = _flag(code)
            if flag:
                fw = round(22 * self._xs)
                self._hdr(xbmcgui.ControlImage(col - 6 - fw, HS_Y + 132, fw, 16, flag))
            self._hdr(
                xbmcgui.ControlLabel(
                    col - 2, HS_Y + 129, 48, 22, code, font=FONT_XS, textColor=MUTED, alignment=AL_LEFT
                )
            )

    def _caps(self, name, y, colour, fit=CTR_W - 8, scale=1.0):
        # A small bold caps label from a pre-rendered image (no skin font is that small and that bold), centred on
        # the card. Images are rendered at 2x and narrowed like the flags so they keep their shape; one wider than
        # the room it has (fit) is scaled down whole.
        path = _tex(name)
        w, h = _png_size(path)
        w, h = w / 2 * self._xs, h / 2
        scale = min(fit / w, scale)
        w, h = round(w * scale), round(h * scale)
        return xbmcgui.ControlImage(CTR_X + (CTR_W - w) // 2, y, w, h, path, colorDiffuse=f"0x{colour}")

    def _build_centre(self):
        # Score card (mock .scorecol): a FINISHED/LIVE band, then per-set rows ("SET n" over "a | b") split by
        # hairlines. Row positions depend on the set count, so _render_centre() lays them out.
        self._card(xbmcgui.ControlImage(CTR_X, HS_Y, CTR_W, BAND_H, _tex("band.png"), colorDiffuse=f"0x{BAND}"))
        self._finished = self._card(self._caps("lbl-finished.png", HS_Y + 5, WHITE))
        self._live = self._card(self._caps("lbl-live.png", HS_Y + 5, TEAL))
        self._setrows = []
        half = CTR_W // 2
        gap = round(9 * self._xs)  # from the card centre to each number
        for i in range(3):
            sep = self._card(xbmcgui.ControlImage(CTR_X, HS_Y, CTR_W, 1, _white(), colorDiffuse=f"0x{MID}"))
            lab = self._card(self._caps(f"lbl-set{i + 1}.png", HS_Y, MUTED))
            # Numbers bold and large, the divider regular and muted (mock .setsc .n / .d).
            left = self._card(
                xbmcgui.ControlLabel(CTR_X, HS_Y, half - gap, SET_ROW_H, "", font=FONT_L, alignment=AL_RIGHT)
            )
            div = self._card(self._divider(HS_Y, SET_ROW_H, SET_DIV_H))
            right = self._card(
                xbmcgui.ControlLabel(
                    CTR_X + half + gap, HS_Y, half - gap, SET_ROW_H, "", font=FONT_L, alignment=AL_LEFT
                )
            )
            self._setrows.append((sep, lab, left, div, right))
        if self._sync:
            self._build_live_card()
        self._build_outline()  # last, so it draws over the card's boxes

    def _build_live_card(self):
        card = self._card
        lc = {
            "band": [card(xbmcgui.ControlImage(CTR_X, HS_Y, CTR_W, BAND_H, _tex("band.png"), colorDiffuse=f"0x{BAND}"))]
        }
        lc["set"] = [card(self._caps(f"lbl-set{n}.png", HS_Y + 5, WHITE)) for n in range(1, 6)]
        y = HS_Y + BAND_H
        lc["band"].append(card(xbmcgui.ControlImage(CTR_X, y, CTR_W, PT_H, _white(), colorDiffuse="0xFFFFFFFF")))
        lc["pts"] = self._pair(y, PT_H, DARK)
        lc["games_bg"] = card(xbmcgui.ControlImage(CTR_X, y, CTR_W, GAMES_H, _white(), colorDiffuse=f"0x{BALL}"))
        lc["games"] = self._pair(y, GAMES_H, DARK)
        dw = max(round(12 * self._xs), 1)
        lc["dots"] = [
            (
                card(xbmcgui.ControlImage(CTR_X, y, dw, 12, _tex("dot.png"))),
                card(xbmcgui.ControlImage(CTR_X, y, dw, 12, _tex("dot.png"))),
            )
            for _i in range(DOT_POOL)
        ]
        lc["line"] = card(xbmcgui.ControlImage(CTR_X, y, CTR_W, 1, _white(), colorDiffuse=f"0x{MID}"))
        # Up to two completed sets side by side, each a SET n caption over its score.
        lc["done"] = []
        for _col in range(2):
            # The caption a size down from the band's "SET n", so the set in play reads first.
            caps = [card(self._caps(f"lbl-set{n}.png", y, MUTED, fit=CTR_W // 2 - 4, scale=0.8)) for n in range(1, 5)]
            lc["done"].append((caps, self._pair(y, 20, MUTED, font=FONT_XS)))
        # The serving ball just outside the server's headshot ring, down and towards the card.
        bw, out = round(BALL_D * self._xs), round(BALL_OUT * self._xs)
        by = HS_Y + HS // 2 + BALL_OUT - BALL_D // 2
        lc["serve"] = (
            card(xbmcgui.ControlImage(LCOL + out - bw // 2, by, bw, BALL_D, _tex("dot.png"), colorDiffuse=f"0x{BALL}")),
            card(xbmcgui.ControlImage(RCOL - out - bw // 2, by, bw, BALL_D, _tex("dot.png"), colorDiffuse=f"0x{BALL}")),
        )
        self._lc = lc

    def _divider(self, y, h, line=DIV_H, x=CTR_X, w=CTR_W):
        # A short muted line centred in an h tall row (a "|" glyph sits low and runs long in the skin's thin font).
        return xbmcgui.ControlImage(x + w // 2, y + (h - line) // 2, 1, line, _white(), colorDiffuse=f"0x{MUTED}")

    def _pair(self, y, h, colour, font=FONT_S, x=CTR_X, w=CTR_W):
        # "a | b" in its row: each number centred in its half (between the edge and a short muted divider), so a
        # one-digit score sits as squarely as a two-digit one.
        half = w // 2
        ny = y + DIGIT_NUDGE
        return (
            self._card(xbmcgui.ControlLabel(x, ny, half, h, "", font=font, textColor=colour, alignment=AL_CENTRE)),
            self._card(self._divider(y, h, x=x, w=w)),
            self._card(
                xbmcgui.ControlLabel(x + half, ny, w - half, h, "", font=font, textColor=colour, alignment=AL_CENTRE)
            ),
        )

    @staticmethod
    def _place_pair(pair, x, y, h, w=CTR_W):
        left, div, right = pair
        half = w // 2
        left.setPosition(x, y + DIGIT_NUDGE)
        div.setPosition(x + half, y + (h - div.getHeight()) // 2)
        right.setPosition(x + half, y + DIGIT_NUDGE)

    def _show_live_card(self, live):
        # Shows the live card (or hides it) as one; the finished card's set rows take its place when hidden.
        lc = self._lc
        ctrls = lc["band"] + lc["set"] + list(lc["pts"]) + [lc["games_bg"]] + list(lc["games"]) + [lc["line"]]
        ctrls += [d for row in lc["dots"] for d in row] + list(lc["serve"])
        ctrls += [c for caps, score in lc["done"] for c in [*caps, *score]]
        for ctrl in ctrls:
            ctrl.setVisible(live)

    def _render_live_card(self, card):
        lc = self._lc
        self._show_live_card(True)
        for n, cap in enumerate(lc["set"], 1):
            cap.setVisible(n == card["set"])
        pts_l, _div, pts_r = lc["pts"]
        pts_l.setLabel(_b(card["points"][0]))
        pts_r.setLabel(_b(card["points"][1]))
        # Only points already played get a dot (the winner's lit): the games box starts right under the point score
        # and moves down a row per point, so nothing hints at how the game will go. A long game tightens the rows a
        # little; only one longer than the card can hold keeps just its latest points.
        done = card["done"][-2:]
        done_h = DONE_H if done else 0
        dots_top = HS_Y + BAND_H + PT_H + 3
        room = HS_Y + CARD_MAX - 4 - done_h - GAMES_H - 1 - dots_top
        rally = card["rally"]
        size, step = next((lay for lay in DOT_LAYOUTS if len(rally) * lay[1] <= room), DOT_LAYOUTS[-1])
        rally = rally[-min(len(rally), room // step, DOT_POOL) :] if rally else []
        dw = max(round(size * self._xs), 1)
        # Each player's dot is centred in its half of the card, under its number.
        for i, (left, right) in enumerate(lc["dots"]):
            shown = i < len(rally)
            if shown:
                y = dots_top + i * step + (step - size) // 2
                for dot, x, player, colour in ((left, CTR_X, 1, TEAL), (right, CTR_X + CTR_W // 2, 2, BLUE)):
                    dot.setPosition(x + (CTR_W // 2 - dw) // 2, y)
                    dot.setWidth(dw)
                    dot.setHeight(size)
                    dot.setColorDiffuse(f"0x{colour if rally[i] == player else DOT_OFF}")
            left.setVisible(shown)
            right.setVisible(shown)
        games_y = HS_Y + BAND_H + PT_H + (len(rally) * step + 4 if rally else 0)
        # The games box rounds off the card when it is the bottom row (no completed sets under it).
        lc["games_bg"].setPosition(CTR_X, games_y)
        lc["games_bg"].setImage(_white() if done else _tex("band-b.png"))
        self._place_pair(lc["games"], CTR_X, games_y, GAMES_H)
        g_l, _div, g_r = lc["games"]
        g_l.setLabel(_b(str(card["games"][0])))
        g_r.setLabel(_b(str(card["games"][1])))
        # Completed sets under a hairline: a SET n caption, then its score clear below it.
        done_y = games_y + GAMES_H
        lc["line"].setVisible(bool(done))
        lc["line"].setPosition(CTR_X, done_y)
        first = len(card["done"]) - len(done) + 1
        width = CTR_W // max(len(done), 1)
        for col, (caps, score) in enumerate(lc["done"]):
            shown = col < len(done)
            x = CTR_X + col * width
            for n, cap in enumerate(caps, 1):
                cap.setVisible(shown and n == first + col)
                cap.setPosition(x + (width - cap.getWidth()) // 2, done_y + 6)
            for ctrl in score:
                ctrl.setVisible(shown)
            if shown:
                a, b = done[col]
                left, _div, right = score
                for ctrl in (left, right):
                    ctrl.setWidth(width // 2)
                self._place_pair(score, x, done_y + 15, 20, w=width)
                _set_score(left, right, a, b)
        self._card_height(done_y + done_h - HS_Y)
        ball_l, ball_r = lc["serve"]
        ball_l.setVisible(card["server"] == 1)
        ball_r.setVisible(card["server"] == 2)

    def _build_outline(self):
        # The card's 1px outline, drawn on top of its coloured boxes so it frames them exactly (behind them, a pixel of
        # rounding on a stretched screen showed it running past the boxes' corners). Built from four rounded corners
        # and four edges, since an image added from Python cannot be border-scaled and a single one would distort.
        card, cw = self._card, round(OUTLINE_R * self._xs)
        tint = f"0x{OUTLINE}"
        self._outline = {
            name: card(xbmcgui.ControlImage(CTR_X, HS_Y, cw, OUTLINE_R, _tex(f"corner-{name}.png"), colorDiffuse=tint))
            for name in ("tl", "tr", "bl", "br")
        }
        for name in ("top", "bottom", "left", "right"):
            self._outline[name] = card(xbmcgui.ControlImage(CTR_X, HS_Y, 1, 1, _white(), colorDiffuse=tint))

    def _card_height(self, height):
        # The card background (MatchInfo.xml 70) and the outline follow the card's height.
        with contextlib.suppress(RuntimeError):
            self.getControl(CARD_BG).setHeight(height)
        o, cw, r = self._outline, round(OUTLINE_R * self._xs), OUTLINE_R
        x, y, w = CTR_X, HS_Y, CTR_W
        o["tl"].setPosition(x, y)
        o["tr"].setPosition(x + w - cw, y)
        o["bl"].setPosition(x, y + height - r)
        o["br"].setPosition(x + w - cw, y + height - r)
        for name, (ex, ey, ew, eh) in {
            "top": (x + cw, y, w - 2 * cw, 1),
            "bottom": (x + cw, y + height - 1, w - 2 * cw, 1),
            "left": (x, y + r, 1, height - 2 * r),
            "right": (x + w - 1, y + r, 1, height - 2 * r),
        }.items():
            o[name].setPosition(ex, ey)
            o[name].setWidth(ew)
            o[name].setHeight(max(eh, 1))

    def _render_centre(self):
        status = self._view_stats().get("Status")
        if self._sync:
            card = timeline.live_card(self._state, self._sync.team_a_is_p1)
            if card and not card["finished"]:
                self._finished.setVisible(False)
                self._live.setVisible(False)
                for row in self._setrows:
                    for ctrl in row:
                        ctrl.setVisible(False)
                self._render_live_card(card)
                return
            self._show_live_card(False)
            # Before the first point there is nothing to show; once finished, the final sets as usual.
            status = "Finished" if card else None
        self._card_height(CARD_H)
        self._finished.setVisible(status == "Finished")
        self._live.setVisible(bool(status) and status != "Finished")
        sets = self._set_scores() if status else []
        top = HS_Y + BAND_H
        row_h = (CARD_H - BAND_H) // max(len(sets), 1)
        # The score sits clear of its SET n caption; three sets leave less room, so the gap closes up a little.
        off = 16 if row_h >= 52 else 12
        pad = max((row_h - off - 32) // 2, 0)  # centre the label + score pair in its row
        for i, (sep, lab, left, div, right) in enumerate(self._setrows):
            shown = i < len(sets)
            if shown:
                a, b = sets[i]
                y = top + i * row_h
                sep.setPosition(CTR_X, y)
                lab.setPosition(lab.getPosition()[0], y + pad)
                for ctrl in (left, right):
                    ctrl.setPosition(ctrl.getPosition()[0], y + pad + off)
                div.setPosition(div.getPosition()[0], y + pad + off + (SET_ROW_H - SET_DIV_H) // 2)
                _set_score(left, right, a, b)
            sep.setVisible(shown and i > 0)
            for ctrl in (lab, left, div, right):
                ctrl.setVisible(shown)

    def _set_scores(self):
        data = self._view_stats()
        t1 = (data.get("PlayerTeam1") or {}).get("Sets") or []
        t2 = {s.get("SetNumber"): s for s in (data.get("PlayerTeam2") or {}).get("Sets") or []}
        out = []
        for s in t1:
            n = s.get("SetNumber")
            a, b = s.get("SetScore"), t2.get(n, {}).get("SetScore")
            if n and a is not None and b is not None:
                with contextlib.suppress(TypeError, ValueError):
                    out.append((int(a), int(b)))
        return out

    def _build_rows(self):
        y = ROWS_Y + 40
        for heading, group, rows in GROUPS:
            y = self._heading(self._stat, y, heading)
            for label, key in rows:
                self._rows.append({"group": group, "key": key, **self._bar_row(self._stat, y, label)})
                y += 40
            y += 10

    def _heading(self, gate, y, heading):
        # A section heading card (SERVICE, RETURN, MOMENTUM, ...); returns the y below it.
        gate(xbmcgui.ControlImage(CX, y, CW, 26, _tex("card.png"), colorDiffuse=f"0x{CARD}"))
        gate(xbmcgui.ControlLabel(CX, y, CW, 26, _b(heading), font=FONT_XS, textColor=MUTED, alignment=AL_CENTRE))
        return y + 32

    def _bar_row(self, gate, y, label, bar_y=28):
        # "left  label  right" over a grey full-width track with two rounded fills growing out from the centre and a
        # centre tick on top.
        lval = gate(xbmcgui.ControlLabel(LVAL_X, y, LVAL_W, 22, "", font=FONT_XS, alignment=AL_RIGHT))
        gate(xbmcgui.ControlLabel(NAME_X, y, NAME_W, 22, _b(label), font=FONT_XS, textColor=WHITE, alignment=AL_CENTRE))
        rval = gate(xbmcgui.ControlLabel(RVAL_X, y, RVAL_W, 22, "", font=FONT_XS, alignment=AL_LEFT))
        gate(xbmcgui.ControlImage(CX, y + bar_y, CW, 6, _tex("track.png"), colorDiffuse=f"0x{TRACK}"))
        lbar = gate(xbmcgui.ControlImage(CENTRE, y + bar_y, 1, 6, _tex("fill-l.png"), colorDiffuse=f"0x{TEAL}"))
        rbar = gate(xbmcgui.ControlImage(CENTRE, y + bar_y, 1, 6, _tex("fill-r.png"), colorDiffuse=f"0x{BLUE}"))
        gate(xbmcgui.ControlImage(CENTRE, y + bar_y - 1, 1, 8, _white(), colorDiffuse=f"0x{MID}"))
        return {"lval": lval, "rval": rval, "lbar": lbar, "rbar": rbar}

    def _fill(self, row, lf, rf):
        lw, rw = max(int(lf * BAR_HALF), 1), max(int(rf * BAR_HALF), 1)
        y = row["lbar"].getPosition()[1]
        row["lbar"].setWidth(lw)
        row["lbar"].setPosition(CENTRE - lw, y)
        row["rbar"].setWidth(rw)
        row["rbar"].setPosition(CENTRE, y)

    def _build_set_toggle(self):
        team = (self._view_stats().get("PlayerTeam1") or {}).get("Sets") or []
        self._set_map = {}
        sets = sorted({s.get("SetNumber") for s in team if s.get("SetNumber")})
        items = [(_.STATS_MATCH, 0)] + [(_(_.STATS_SET, n=n), n) for n in sets]
        n = len(items)
        width = min(120, (CW - SET_GAP * (n - 1)) // n) if n else 120
        self._set_text, self._set_rect = {}, {}  # set value -> label, and -> (x, width) for the overlay
        for i in range(SET_MAX):
            btn = self.getControl(SET_BASE + i)
            if i < len(items):
                label, value = items[i]
                btn.setLabel(_b(label), font=FONT_S)
                btn.setWidth(width)
                btn.setVisible(True)
                self._set_map[SET_BASE + i] = value
                self._set_text[value] = _b(label)
                self._set_rect[value] = (CX + i * (width + SET_GAP), width)
            else:
                btn.setVisible(False)

    def _build_rounds(self):
        self._rounds_built = True
        ms = (self._draw() or {}).get("MS") or {}
        self._draw_rounds = [r for r in reversed(ms.get("Rounds") or []) if r.get("Fixtures")]
        for i in range(ROUND_MAX):
            btn = self.getControl(ROUND_BASE + i)
            if i < len(self._draw_rounds):
                btn.setLabel(_b(_short_round(self._draw_rounds[i].get("RoundName") or "")), font=FONT_S)
                btn.setVisible(True)
                self._round_ids.append(ROUND_BASE + i)
            else:
                btn.setVisible(False)

    # --- section / sub switching ---

    def _set_section(self, section):
        self._section = section
        if section == SEC_DRAW and not self._rounds_built:
            self._build_rounds()
        self._refresh()

    def _refresh(self):
        live = self._section == SEC_LIVE
        stats_view = live and self._sub == SUB_STATS
        show_stats = stats_view and self._revealed
        h2h_sub = live and self._sub == SUB_H2H
        h2h_view = h2h_sub and bool(self._h2h().get("Player") and self._h2h().get("Opponent"))
        ins_view = live and self._sub == SUB_INSIGHTS and bool(self._sync)
        key_view = self._section == SEC_KEY and self._load_moments()
        text_view = (
            (live and self._sub == SUB_INSIGHTS and not ins_view)
            or (h2h_sub and not h2h_view)
            or (self._section == SEC_KEY and not key_view)
        )
        views = {
            HDR_PROP: live,
            CARD_PROP: live and self._revealed,
            STATS_PROP: show_stats,
            H2H_PROP: h2h_view,
            INS_PROP: ins_view,
            KEY_PROP: key_view,
            SPOILER_PROP: stats_view and not self._revealed,
            TEXT_PROP: text_view,
            DRAW_PROP: self._section == SEC_DRAW,
        }
        # Hide the views going away first, build and fill in the new one while hidden, then show it in one go.
        for prop, on in views.items():
            if not on:
                self.setProperty(prop, "")
        for cid in SUBS:
            self.getControl(cid).setVisible(live)
        if live and self._revealed:
            self._ensure_built()
        # Text panes sit below the player header in Live Stats, and at the top in Key Moments.
        body = self.getControl(BODY_ID)
        body.setPosition(CX, SET_Y if live else SUB_Y)
        body.setHeight(PANEL_BOTTOM - 16 - (SET_Y if live else SUB_Y))
        if h2h_view and self._h2h_built != self._revealed:
            self._build_h2h()
        if ins_view and not self._ins_built:
            self._build_insights()
        if self._section != SEC_DRAW:
            self._clear_draw()
        self._sec_ind.setWidth(self._sec_w[self._section])
        self._sec_ind.setPosition(self._sec_x[self._section], LINE_Y)
        self._highlight_active(live, show_stats)
        self._wire_nav()
        self._render()
        for prop, on in views.items():
            if on:
                self.setProperty(prop, "1")

    def _highlight_active(self, live, show_stats):
        # Teal pill + dark label over the selected sub-tab, set and draw round (persistent, focus-independent).
        # Buttons themselves are grey at rest and white when focused, so only the selected item is teal.
        sub_bg, sub_lbl = self._sub_hl
        sub_bg.setPosition(SUB_X[self._sub], SUB_Y)
        sub_lbl.setPosition(SUB_X[self._sub], SUB_Y)
        sub_lbl.setLabel(_b({SUB_STATS: _.TAB_STATS, SUB_INSIGHTS: _.SUB_INSIGHTS, SUB_H2H: _.SUB_H2H}[self._sub]))
        sub_bg.setVisible(live)
        sub_lbl.setVisible(live)
        set_bg, set_lbl = self._set_hl
        rect = self._set_rect.get(self._set_num)
        if show_stats and rect:
            x, w = rect
            set_bg.setWidth(w)
            set_bg.setPosition(x, SET_Y)
            set_lbl.setWidth(w)
            set_lbl.setPosition(x, SET_Y)
            set_lbl.setLabel(self._set_text.get(self._set_num, ""))
        rnd_bg, rnd_lbl = self._rnd_hl
        if self._section == SEC_DRAW and self._round_ids:
            idx = min(self._round_idx, len(self._round_ids) - 1)
            x = CX + idx * ROUND_STEP
            rnd_bg.setPosition(x, SUB_Y)
            rnd_lbl.setPosition(x, SUB_Y)
            rnd_lbl.setLabel(self.getControl(self._round_ids[idx]).getLabel())

    def _wire_nav(self):
        # Rewire keyboard down/up between the rows that are actually visible for this section.
        live = self._section == SEC_LIVE
        if live:
            row2 = SUB_STATS
        elif self._section == SEC_DRAW and self._round_ids:
            row2 = self._round_ids[0]
        elif self._section == SEC_KEY and self._moments:
            row2 = KEY_LIST
        else:
            row2 = None
        for sec in SECTIONS:
            self.getControl(sec).controlDown(self.getControl(row2 or sec))
        if self._sub == SUB_STATS and not self._revealed:
            down3 = REVEAL_ID
        elif self._sub == SUB_STATS and self._set_map:
            down3 = min(self._set_map)
        else:
            down3 = None
        for sub in SUBS:
            ctrl = self.getControl(sub)
            ctrl.controlUp(self.getControl(SEC_LIVE))
            ctrl.controlDown(self.getControl(down3 if (sub == SUB_STATS and down3) else sub))
        for rid in self._round_ids:
            self.getControl(rid).controlUp(self.getControl(SEC_DRAW))

    def _render(self):
        if self._section == SEC_LIVE and self._revealed:
            self._render_centre()
        if self._section == SEC_LIVE and self._sub == SUB_STATS:
            if self._revealed:
                self._render_stats()
        elif self._section == SEC_LIVE and self._sub == SUB_INSIGHTS:
            if self._sync:
                self._render_insights()
            else:
                self.getControl(BODY_ID).setText(_.INSIGHTS_NOTE)
        elif self._section == SEC_LIVE and self._sub == SUB_H2H:
            self.getControl(BODY_ID).setText(_.NO_MATCH_INFO)
        elif self._section == SEC_DRAW:
            self._render_draw()
        elif self._section == SEC_KEY:
            if self._moments:
                self._render_moments()
            else:
                self.getControl(BODY_ID).setText(_.KEY_NOTE)

    def _render_stats(self):
        data = self._view_stats()
        s1 = _set_stats(data.get("PlayerTeam1") or {}, self._set_num)
        s2 = _set_stats(data.get("PlayerTeam2") or {}, self._set_num)
        for row in self._rows:
            g1 = (s1.get(row["group"]) or {}).get(row["key"])
            g2 = (s2.get(row["group"]) or {}).get(row["key"])
            n1, n2 = _numeric(g1), _numeric(g2)
            self._lead_labels(row, n1, n2, _value(g1, row["key"]), _value(g2, row["key"]))
            self._fill(row, *_fills(g1, g2, n1, n2))

    # --- data ---

    def _stats(self):
        if "stats" not in self._cache:
            self._cache["stats"] = self._api.match_stats(self._tid, self._year, self._match_id) or {}
        return self._cache["stats"]

    def _view_stats(self):
        # The stats to show: as of the video position when synced, else the latest.
        if not self._sync:
            return self._stats()
        stats = self._state.get("MatchStats#show") or {}
        return stats if stats.get("PlayerTeam1") else {}

    def _draw(self):
        if "draw" not in self._cache:
            self._cache["draw"] = self._api.draw(self._tid, self._year) or {}
        return self._cache["draw"]

    def _player_ids(self):
        data = self._stats()
        return (data.get("PlayerTeam1") or {}).get("PlayerId"), (data.get("PlayerTeam2") or {}).get("PlayerId")

    def _h2h(self):
        if "h2h" not in self._cache:
            p1, p2 = self._player_ids()
            self._cache["h2h"] = (self._api.head_to_head(p1, p2) if p1 and p2 else {}) or {}
        return self._cache["h2h"]

    # --- poll ---

    def _poll(self):
        if self._sync:
            self._follow()
            return
        while not self._stop.wait(POLL_SECONDS):
            if (self._cache.get("stats") or {}).get("Status") == "Finished":
                return
            try:
                stats = self._api.match_stats(self._tid, self._year, self._match_id) or {}
                with self._lock:
                    self._cache["stats"] = stats
                    if self._section == SEC_LIVE and self._revealed:
                        self._render_centre()
                        if self._sub == SUB_STATS:
                            self._render_stats()
            except Exception:
                log.debug("Match Info: live poll failed; carrying on", exc_info=True)

    def _follow(self):
        # Timeline-synced: re-read the state for the current video position every couple of seconds, refetching the
        # timeline and playlist of a live match as it goes, and redraw only when the state has moved on. A failing
        # tick is logged and the loop carries on, so one bad moment cannot leave the overlay frozen.
        self._refreshed = time.time()
        while not self._stop.wait(SYNC_SECONDS):
            try:
                self._follow_tick()
            except Exception:
                log.debug("Match Info: follow tick failed; carrying on", exc_info=True)

    def _follow_tick(self):
        if not xbmc.Player().isPlaying():
            log.debug("Match Info: playback ended; closing")
            self.close()
            return
        if self._sync.live and time.time() - self._refreshed >= POLL_SECONDS:
            self._refreshed = time.time()
            try:
                self._sync.refresh()
            except Exception as e:  # keep following on the last timeline
                log.debug(f"Match Info: live refresh failed ({e}); keeping the last timeline")
            else:
                if self._moments_loaded:
                    moments = self._fetch_moments()  # outside the lock: it is a network call
                    with self._lock:
                        self._set_moments(moments)
        pos, when = self._sync.position(), self._sync.now()
        if when is None:
            if not self._lost:
                log.debug("Match Info: no video position from Kodi; waiting")
            self._lost = True
            return
        self._lost = False
        state = timeline.state_at(self._sync.events, when)
        tick = (pos, time.time())
        # A jump in position that wall time does not explain is a seek; a heartbeat every 30s shows the overlay still
        # following between seeks. Both log what it shows, for diagnosing a stuck overlay from kodi.log.
        seek = self._last_tick and abs((tick[0] - self._last_tick[0]) - (tick[1] - self._last_tick[1])) > 5
        if seek or not self._last_tick or tick[1] - self._beat >= 30:
            self._beat = tick[1]
            card = timeline.live_card(state, self._sync.team_a_is_p1) or {}
            log.debug(
                f"Match Info: {'seek to' if seek else 'following at'} {pos:.0f}s, timeline {when}, set "
                f"{card.get('set')} games {card.get('games')} points {card.get('points')}"
            )
        self._last_tick = tick
        # The metadata objects are the timeline's own, so their ids only change when a newer event takes over.
        key = tuple(sorted((k, id(v)) for k, v in state.items()))
        if key != self._state_key:
            with self._lock:
                self._apply_state(state, key)

    def _apply_state(self, state, key):
        # Redraw whatever is on screen for a new timeline state (the video moved on, or jumped).
        if self._stop.is_set():
            return
        sets = len((self._view_stats().get("PlayerTeam1") or {}).get("Sets") or [])
        self._state, self._state_key = state, key
        if self._section == SEC_KEY and self._moments:
            self._render_moments()
        if not (self._section == SEC_LIVE and self._built):
            return
        if len((self._view_stats().get("PlayerTeam1") or {}).get("Sets") or []) != sets:
            self._build_set_toggle()
            if self._set_num not in self._set_map.values():  # a seek back can remove the selected set
                self._set_num = 0
            self._highlight_active(True, self._sub == SUB_STATS)
            self._wire_nav()
        self._render_centre()
        if self._sub == SUB_STATS:
            self._render_stats()
        elif self._sub == SUB_INSIGHTS and self._ins_built:
            self._render_insights()

    # --- insights ---

    def _ins(self, control):
        return self._gate(control, INS_PROP)

    def _split(self, y, h, font, x=CX, w=CW, three=False):
        # A momentum style split bar: teal | (grey) | blue segments sized by share, each with its percentage inside.
        g = self._ins
        parts = {
            "a": g(xbmcgui.ControlImage(x, y, 1, h, _white(), colorDiffuse=f"0x{TEAL}")),
            "b": g(xbmcgui.ControlImage(x, y, 1, h, _white(), colorDiffuse=f"0x{BLUE}")),
            "la": g(xbmcgui.ControlLabel(x + 6, y, w // 2, h, "", font=font, textColor=DARK, alignment=AL_LEFT)),
            "lb": g(
                xbmcgui.ControlLabel(x + w // 2, y, w // 2 - 6, h, "", font=font, textColor=DARK, alignment=AL_RIGHT)
            ),
            "x": x,
            "w": w,
        }
        if three:
            parts["n"] = g(xbmcgui.ControlImage(x, y, 1, h, _white(), colorDiffuse=f"0x{MID}"))
            parts["ln"] = g(xbmcgui.ControlLabel(x, y, 1, h, "", font=font, textColor=WHITE, alignment=AL_CENTRE))
        return parts

    def _set_split(self, parts, a, b, n=None):
        x, w = parts["x"], parts["w"]
        known = a is not None and b is not None
        a, b, n = (a or 0, b or 0, n or 0) if known else (50, 50, 0)
        total = (a + b + n) or 1
        wa, wn = round(w * a / total), round(w * n / total)
        y = parts["a"].getPosition()[1]
        parts["a"].setWidth(max(wa, 1))
        parts["b"].setPosition(x + wa + wn, y)
        parts["b"].setWidth(max(w - wa - wn, 1))
        parts["la"].setLabel(_b(f"{a}%" if known else "-"))
        parts["lb"].setLabel(_b(f"{b}%" if known else "-"))
        if "n" in parts:
            parts["n"].setPosition(x + wa, y)
            parts["n"].setWidth(max(wn, 1))
            parts["ln"].setPosition(x + wa, y)
            parts["ln"].setWidth(max(wn, 1))
            parts["ln"].setLabel(_b(f"{n}%") if known and wn > 30 else "")

    def _build_insights(self):
        self._ins_built = True
        g = self._ins
        y = self._heading(g, SET_Y, _.INS_MOMENTUM)
        self._ins_now = self._split(y, SPLIT_H, FONT_S)
        y = self._heading(g, y + SPLIT_H + 10, _.INS_PREVIOUS_GAMES)
        self._ins_games = []
        for _i in range(INS_GAMES):
            label = g(xbmcgui.ControlLabel(CX, y, 56, GAME_H, "", font=FONT_XS, textColor=MUTED, alignment=AL_LEFT))
            self._ins_games.append((label, self._split(y, GAME_H, FONT_XS, x=CX + 60, w=CW - 60)))
            y += GAME_STEP
        y = self._heading(g, y + 6, _.INS_ATTACK_DEFENCE)
        # Conversion and steal: the % on top, the points won of those played underneath, then the bar.
        self._ins_ad = []
        for label, hint in ((_.INS_CONVERSION, _.INS_CONVERSION_HINT), (_.INS_STEAL, _.INS_STEAL_HINT)):
            row = self._bar_row(g, y, label, bar_y=46)
            row["lhint"] = g(xbmcgui.ControlLabel(LVAL_X, y + 22, LVAL_W, 20, "", font=FONT_XS, alignment=AL_RIGHT))
            g(
                xbmcgui.ControlLabel(
                    NAME_X, y + 22, NAME_W, 20, hint, font=FONT_XS, textColor=MUTED, alignment=AL_CENTRE
                )
            )
            row["rhint"] = g(xbmcgui.ControlLabel(RVAL_X, y + 22, RVAL_W, 20, "", font=FONT_XS, alignment=AL_LEFT))
            self._ins_ad.append(row)
            y += 58
        y = self._heading(g, y, _.INS_SHOT_QUALITY)
        self._ins_shots = []
        for label in (_.INS_SERVE, _.INS_RETURN, _.INS_FOREHAND, _.INS_BACKHAND):
            self._ins_shots.append(self._bar_row(g, y, label))
            y += 40
        y = self._heading(g, y + 4, _.INS_BALANCE)
        self._ins_power = self._split(y, SPLIT_H, FONT_S, three=True)
        y += SPLIT_H + 4
        data = self._h2h()
        names = ((data.get("Player") or {}).get("LastName") or "", (data.get("Opponent") or {}).get("LastName") or "")
        g(xbmcgui.ControlLabel(CX, y, CW // 3, 22, _b(names[0]), font=FONT_XS, textColor=TEAL, alignment=AL_LEFT))
        g(xbmcgui.ControlLabel(CX, y, CW, 22, _b(_.INS_NEUTRAL), font=FONT_XS, textColor=MUTED, alignment=AL_CENTRE))
        g(
            xbmcgui.ControlLabel(
                CX + CW * 2 // 3, y, CW // 3, 22, _b(names[1]), font=FONT_XS, textColor=BLUE, alignment=AL_RIGHT
            )
        )
        self._flush()

    def _render_insights(self):
        now = self._sync.now()
        card = timeline.live_card(self._state, self._sync.team_a_is_p1)
        current = (card["set"], card["game"]) if card else None
        games = timeline.momentum_games(self._sync.events, now, current) if now is not None else []
        h = timeline.insights(self._state, games, self._sync.team_a_is_p1)
        self._set_split(self._ins_now, *h["momentum"])
        # Finished games only, newest first; rows without a game yet stay empty rather than showing a blank bar.
        for i, (label, split) in enumerate(self._ins_games):
            game = h["games"][i] if i < len(h["games"]) else None
            label.setLabel(_b(_(_.INS_GAME, set=game[0], game=game[1])) if game else "")
            for key in ("a", "b", "la", "lb"):
                split[key].setVisible(bool(game))
            if game:
                self._set_split(split, *game[2:])
        for row, (a, b) in zip(self._ins_ad, (h["conversion"], h["steal"])):
            (w1, t1, p1), (w2, t2, p2) = a, b
            self._lead_labels(row, p1, p2, f"{p1}%" if p1 is not None else "-", f"{p2}%" if p2 is not None else "-")
            row["lhint"].setLabel(_b(f"[COLOR={MUTED}]{w1}/{t1}[/COLOR]") if t1 else "")
            row["rhint"].setLabel(_b(f"[COLOR={MUTED}]{w2}/{t2}[/COLOR]") if t2 else "")
            self._fill(row, (p1 or 0) / 100, (p2 or 0) / 100)
        for row, (_label, a, b) in zip(self._ins_shots, h["shots"]):
            self._lead_labels(row, a, b, f"{a:.1f}" if a is not None else "-", f"{b:.1f}" if b is not None else "-")
            self._fill(row, min((a or 0) / 10, 1.0), min((b or 0) / 10, 1.0))
        p1, neutral, p2 = h["power"]
        self._set_split(self._ins_power, p1, p2, neutral)

    def _lead_labels(self, row, a, b, left, right):
        # The leading value bright in its player's colour, the other dimmed (as in the stats rows).
        a, b = a or 0, b or 0
        row["lval"].setLabel(_b(f"[COLOR={TEAL if a >= b and (a or b) else P1_DIM}]{left}[/COLOR]"))
        row["rval"].setLabel(_b(f"[COLOR={BLUE if b >= a and (a or b) else P2_DIM}]{right}[/COLOR]"))

    # --- key moments ---

    def _load_moments(self):
        # The match's Key Moments, loaded on first use (the warm-up usually has them already).
        if not self._sync:
            return False
        if not self._moments_loaded:
            self._set_moments(self._fetch_moments())
        return bool(self._moments)

    def _fetch_moments(self):
        # The match's PlayAnywhere clips (the timeline names the event), oldest first. Clips without a readable time
        # cannot be placed on the video, so they are left out. Optional: on failure the view shows a note instead.
        pa = timeline.playanywhere_event(self._sync.events)
        try:
            clips = self._api.key_moments(pa) if pa else []
        except Exception as e:
            log.debug(f"Match Info: key moments unavailable ({e})")
            clips = []
        return sorted((m for m in map(_moment, clips) if m["clock"]), key=lambda m: m["clock"])

    def _set_moments(self, moments):
        self._moments, self._moments_loaded, self._moments_key = moments, True, None

    def _render_moments(self):
        # Only the moments up to the video position are listed (newest first); later ones stay hidden until reached.
        now = self._sync.now()
        seen = [m for m in self._moments if now is not None and m["clock"] <= now]
        key = tuple(m["clock"] for m in seen)
        if key == self._moments_key:
            return
        self._moments_key = key
        later = len(self._moments) - len(seen)
        note = (_.KEY_MORE_ONE if later == 1 else _(_.KEY_MORE, count=later)) if later else ""
        self.getControl(KEY_NOTE_ID).setLabel(_b(note))
        lst = self.getControl(KEY_LIST)
        lst.reset()
        self._jumps = []
        for m in reversed(seen):
            pos = max(self._sync.position_for(m["clock"]) - LEAD_IN, 0)
            item = xbmcgui.ListItem(_b(m["who"] or m["kind"]), m["meta"])
            item.setArt({"thumb": m["thumb"]})
            lst.addItem(item)
            self._jumps.append(pos)
        self._wire_nav()

    def _jump(self):
        # Seek the match video to the selected moment.
        with contextlib.suppress(RuntimeError, IndexError):
            index = self.getControl(KEY_LIST).getSelectedPosition()
            target = self._jumps[index]
            log.debug(
                f"Match Info: key moment {index} -> seek to {target:.0f}s (video at {self._sync.position():.0f}s, "
                f"timeline {self._sync.now()}, {len(self._jumps)} moments listed)"
            )
            xbmc.Player().seekTime(target)

    # --- head to head ---

    def _build_h2h(self):
        # Built once per reveal state. The match being watched is left out of the record while the overlay follows the
        # video, and before Reveal on a finished replay, so the record never gives its result away.
        if self._h2h_ctrls:
            self.removeControls(self._h2h_ctrls)
        self._h2h_built = self._revealed
        exclude = None if self._revealed and not self._sync else (self._tid, self._year, self._match_id)
        p1 = self._player_ids()[0]
        h = _h2h_summary(self._h2h(), p1, exclude)
        ctrls = []
        y = H2H_Y
        for heading, rows in ((_.H2H_PROFILE, h["profile"]), (_.H2H_CAREER, h["career"])):
            y = self._heading(ctrls.append, y, heading)
            for i, (label, left, right, lead) in enumerate(rows):
                lc = TEAL if lead in ("l", "tie") else P1_DIM
                rc = BLUE if lead in ("r", "tie") else P2_DIM
                ctrls.append(
                    xbmcgui.ControlLabel(
                        CX, y, H2H_VAL_W, H2H_ROW, _b(f"[COLOR={lc}]{left}[/COLOR]"), font=FONT_XS, alignment=AL_RIGHT
                    )
                )
                ctrls.append(
                    xbmcgui.ControlLabel(
                        CX + H2H_VAL_W,
                        y,
                        CW - 2 * H2H_VAL_W,
                        H2H_ROW,
                        _b(label),
                        font=FONT_XS,
                        textColor=WHITE,
                        alignment=AL_CENTRE,
                    )
                )
                ctrls.append(
                    xbmcgui.ControlLabel(
                        CX + CW - H2H_VAL_W,
                        y,
                        H2H_VAL_W,
                        H2H_ROW,
                        _b(f"[COLOR={rc}]{right}[/COLOR]"),
                        font=FONT_XS,
                        alignment=AL_LEFT,
                    )
                )
                if i < len(rows) - 1:
                    ctrls.append(xbmcgui.ControlImage(CX, y + H2H_ROW - 1, CW, 1, _white(), colorDiffuse=f"0x{LINE}"))
                y += H2H_ROW
            y += 10
        meetings = h["meetings"]
        fit = max((PANEL_BOTTOM - y - 32 - MEET_STEP) // MEET_STEP, 0)
        heading = _.H2H_MEETINGS if len(meetings) <= fit else _(_.H2H_MEETINGS_LATEST, shown=fit, total=len(meetings))
        y = self._heading(ctrls.append, y, heading)
        fw = round(20 * self._xs)
        rh = MEET_H // 2
        y = self._h2h_total(ctrls, y, h["wins"], fw)
        if not meetings:
            ctrls.append(
                xbmcgui.ControlLabel(
                    CX, y, CW, 26, _b(_.H2H_NO_MEETINGS), font=FONT_XS, textColor=MUTED, alignment=AL_CENTRE
                )
            )
        for m in meetings[:fit]:
            colour = TEAL if m["side"] == 1 else BLUE
            ctrls.append(xbmcgui.ControlImage(CX, y, CW, MEET_H, _tex("fixture.png"), colorDiffuse=f"0x{CARD}"))
            ctrls.append(
                xbmcgui.ControlLabel(
                    CX + 10, y + 2, CW - 20, rh, _b(m["event"]), font=FONT_XS, textColor=MUTED, alignment=AL_LEFT
                )
            )
            flag = _flag(m["code"])
            if flag:
                ctrls.append(xbmcgui.ControlImage(CX + 10, y + rh + (rh - 15) // 2, fw, 15, flag))
            ctrls.append(
                xbmcgui.ControlLabel(
                    CX + 16 + fw,
                    y + rh,
                    CW - 140,
                    rh,
                    _b(m["winner"]),
                    font=FONT_XS,
                    textColor=colour,
                    alignment=AL_LEFT,
                )
            )
            ctrls.append(
                xbmcgui.ControlLabel(
                    CX + 10, y + rh, CW - 20, rh, _b(m["score"]), font=FONT_XS, textColor=WHITE, alignment=AL_RIGHT
                )
            )
            y += MEET_STEP
        for ctrl in ctrls:
            self._gate(ctrl, H2H_PROP)
        self._flush()
        self._h2h_ctrls = ctrls

    def _h2h_total(self, ctrls, y, wins, fw):
        # The head-to-head total, heading the meetings: "flag Surname   a | b   Surname flag", the trailing count dim.
        pl, op = self._h2h().get("Player") or {}, self._h2h().get("Opponent") or {}
        a, b = wins
        rh = MEET_H // 2
        ctrls.append(xbmcgui.ControlImage(CX, y, CW, MEET_H, _tex("fixture.png"), colorDiffuse=f"0x{CARD}"))
        ctrls.append(
            xbmcgui.ControlLabel(
                CX + 10,
                y + 2,
                CW - 20,
                rh,
                _b(_(_.H2H_TOTAL, count=a + b)),
                font=FONT_XS,
                textColor=MUTED,
                alignment=AL_LEFT,
            )
        )
        ry = y + rh
        flag1, flag2 = _flag(pl.get("NatlId")), _flag(op.get("NatlId"))
        if flag1:
            ctrls.append(xbmcgui.ControlImage(CX + 10, ry + (rh - 15) // 2, fw, 15, flag1))
        if flag2:
            ctrls.append(xbmcgui.ControlImage(CX + CW - 10 - fw, ry + (rh - 15) // 2, fw, 15, flag2))
        name_w = CW // 2 - 50
        ctrls.append(
            xbmcgui.ControlLabel(
                CX + 16 + fw,
                ry,
                name_w - fw,
                rh,
                _b(pl.get("LastName") or ""),
                font=FONT_XS,
                textColor=TEAL,
                alignment=AL_LEFT,
            )
        )
        ctrls.append(
            xbmcgui.ControlLabel(
                CX + CW - 16 - fw - (name_w - fw),
                ry,
                name_w - fw,
                rh,
                _b(op.get("LastName") or ""),
                font=FONT_XS,
                textColor=BLUE,
                alignment=AL_RIGHT,
            )
        )
        gap = round(8 * self._xs)
        ctrls.append(
            xbmcgui.ControlLabel(
                CENTRE - 40,
                ry,
                40 - gap,
                rh,
                _b(f"[COLOR={TEAL if a >= b else LOSE}]{a}[/COLOR]"),
                font=FONT_S,
                alignment=AL_RIGHT,
            )
        )
        ctrls.append(
            xbmcgui.ControlLabel(CENTRE - 20, ry, 40, rh, "|", font="font10", textColor=MUTED, alignment=AL_CENTRE)
        )
        ctrls.append(
            xbmcgui.ControlLabel(
                CENTRE + gap,
                ry,
                40 - gap,
                rh,
                _b(f"[COLOR={BLUE if b >= a else LOSE}]{b}[/COLOR]"),
                font=FONT_S,
                alignment=AL_LEFT,
            )
        )
        return y + MEET_STEP

    def _clear_draw(self):
        if self._draw_shown:
            self.setProperty(self._draw_shown, "")
            self._draw_shown = None

    def _fixtures(self):
        rounds = self._draw_rounds
        if not rounds:
            return None, []
        rnd = rounds[min(self._round_idx, len(rounds) - 1)]
        return rnd, rnd.get("Fixtures") or []

    def _pages(self):
        return max(-(-len(self._fixtures()[1]) // FX_PAGE), 1)

    def _render_draw(self):
        # Each round's page is built once, behind its own window property; switching rounds or pages only flips
        # which property is set.
        rnd, _fixtures = self._fixtures()
        if not rnd:
            self._clear_draw()
            return
        prop = self._build_draw_page(self._round_idx, self._page)
        if prop != self._draw_shown:
            self._clear_draw()
            self.setProperty(prop, "1")
            self._draw_shown = prop

    def _build_draw_page(self, round_idx, page):
        # The fixtures of one round's page as cards (web player style): "flag Surname" over "flag Surname", a hairline
        # between them, and each player's games per set on the right (a dash for a set not played yet).
        prop = f"{FIX_PROP}.{round_idx}.{page}"
        if prop in self._draw_pages:
            return prop
        self._draw_pages.add(prop)
        rnd = self._draw_rounds[round_idx]
        fixtures = rnd.get("Fixtures") or []
        pages = max(-(-len(fixtures) // FX_PAGE), 1)
        head = _b(f"[COLOR={TEAL}]{rnd.get('RoundName')}[/COLOR]")
        if pages > 1:
            head += f"  [COLOR={MUTED}]{page + 1}/{pages}[/COLOR]"
        ctrls = [xbmcgui.ControlLabel(CX, FX_Y - 30, CW, 26, head, font=FONT_S, alignment=AL_LEFT)]
        fw = round(20 * self._xs)
        start = page * FX_PAGE
        for i, fx in enumerate(fixtures[start : start + FX_PAGE]):
            y = FX_Y + i * FX_STEP
            ctrls.append(xbmcgui.ControlImage(CX, y, CW, FX_H, _tex("fixture.png"), colorDiffuse=f"0x{CARD}"))
            # The hairline sits exactly halfway, and each name is centred in its half, so the gap above and below
            # the line is the same.
            half = FX_H // 2
            ctrls.append(xbmcgui.ControlImage(CX + 10, y + half, FX_NAME_W, 1, _white(), colorDiffuse=f"0x{LINE}"))
            for row, (name, code, games) in enumerate(_fixture_rows(fx)):
                ry = y + row * half
                won = (fx.get("Result") or {}).get("Winner")
                colour = MUTED if name == BYE or (won and won != row + 1) else WHITE
                flag = _flag(code)
                if flag:
                    ctrls.append(xbmcgui.ControlImage(CX + 10, ry + (half - 15) // 2, fw, 15, flag))
                ctrls.append(
                    xbmcgui.ControlLabel(
                        CX + 16 + fw,
                        ry,
                        FX_NAME_W - 6 - fw,
                        half,
                        _b(_.DRAW_BYE if name == BYE else name),
                        font=FONT_XS,
                        textColor=colour,
                        alignment=AL_LEFT,
                    )
                )
                # The games per set in one label: digits, dashes and figure spaces are all one width, so the columns
                # line up (one label instead of one per set keeps the page quicker to build).
                if games:
                    text = FIGURE_SPACE.join(
                        f"[COLOR={WHITE if won_set else MUTED}]{FIGURE_DASH if t == '-' else t}[/COLOR]"
                        for t, won_set in games
                    )
                    ctrls.append(
                        xbmcgui.ControlLabel(
                            CX + CW - 10 - FX_SETS * FX_COL,
                            ry,
                            FX_SETS * FX_COL - 4,
                            half,
                            _b(text),
                            font=FONT_XS,
                            alignment=AL_RIGHT,
                        )
                    )
        for ctrl in ctrls:
            self._gate(ctrl, prop)
        self._flush()
        return prop


def _money(value):
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${value / 1000:.0f}K" if value >= 1000 else f"${value}"


def _ratio(won, lost):
    return won / (won + lost) if won + lost else 0.0


def _lead(a, b, lower=False):
    # "l" / "r" for the better value, "tie" when equal or not comparable.
    if a == b or a is None or b is None:
        return "tie"
    return "l" if (a < b if lower else a > b) else "r"


def _score(result):
    # "63 76(5)" -> "6-3 7-6(5)"; anything unexpected (RET, W/O) is kept as is.
    out = []
    for tok in (result or "").split():
        m = re.fullmatch(r"(\d{2,4})(\(\d+\))?", tok)
        if not m:
            out.append(tok)
            continue
        d = m.group(1)
        if len(d) == 2:
            a, b = d[0], d[1]
        elif len(d) == 4:
            a, b = d[:2], d[2:]
        else:  # three digits: one side reached 10+ (eg. "108" is 10-8, "810" is 8-10)
            a, b = (d[:2], d[2:]) if d[0] == "1" else (d[0], d[1:])
        out.append(f"{a}-{b}{m.group(2) or ''}")
    return " ".join(out)


def _h2h_summary(data, p1, exclude=None):
    # Wins, career and profile comparison rows and the meetings (newest first) from the head-to-head response. A
    # meeting matching exclude (tournament id, year, match id) is dropped and its win taken off, so a finished
    # replay's own result does not show before Reveal.
    pl, op = data.get("Player") or {}, data.get("Opponent") or {}
    wins = [pl.get("H2HWins") or 0, op.get("H2HWins") or 0]
    meetings = []
    for m in data.get("CountableTournaments") or []:
        side = 1 if m.get("WinningPlayerId") == (pl.get("PlayerId") or p1) else 2
        key = (str(m.get("TournamentId")), str(m.get("TournamentYear")), str(m.get("MatchId") or "").upper())
        if exclude and key == (str(exclude[0]), str(exclude[1]), str(exclude[2]).upper()):
            wins[side - 1] = max(wins[side - 1] - 1, 0)
            continue
        winner = pl if side == 1 else op
        event = " · ".join(
            str(part)
            for part in (
                f"{m.get('TournamentYear')} {m.get('TournamentCity') or m.get('TournamentTitle') or ''}".strip(),
                m.get("RoundName"),
                m.get("Surface"),
            )
            if part
        )
        meetings.append(
            {
                "year": m.get("TournamentYear") or 0,
                "event": event,
                "side": side,
                "winner": winner.get("LastName") or m.get("WinningLastName") or "",
                "code": winner.get("NatlId"),
                "score": _score(m.get("ResultString")),
            }
        )
    meetings.sort(key=lambda m: m["year"], reverse=True)

    def both(key):
        return pl.get(key) or 0, op.get(key) or 0

    def rank(value):
        return f"#{value}" if value else "-"

    st, dt, prize = both("SglCareerTitles"), both("DblCareerTitles"), both("CareerPrize")
    sw, sl, dw, dl = both("SglCareerWon"), both("SglCareerLost"), both("DblCareerWon"), both("DblCareerLost")
    career = [
        (_.H2H_SINGLES_TITLES, str(st[0]), str(st[1]), _lead(*st)),
        (_.H2H_DOUBLES_TITLES, str(dt[0]), str(dt[1]), _lead(*dt)),
        (_.H2H_PRIZE_MONEY, _money(prize[0]), _money(prize[1]), _lead(*prize)),
        (_.H2H_WL_SINGLES, f"{sw[0]}/{sl[0]}", f"{sw[1]}/{sl[1]}", _lead(_ratio(sw[0], sl[0]), _ratio(sw[1], sl[1]))),
        (_.H2H_WL_DOUBLES, f"{dw[0]}/{dl[0]}", f"{dw[1]}/{dl[1]}", _lead(_ratio(dw[0], dl[0]), _ratio(dw[1], dl[1]))),
    ]
    hi, cur = both("SglHiRank"), both("SglRank")
    hands = {"R": _.H2H_RIGHT, "L": _.H2H_LEFT}
    backhands = {"1": _.H2H_ONE_HANDED, "2": _.H2H_TWO_HANDED}
    profile = [
        (_.H2H_CAREER_HIGH, rank(hi[0]), rank(hi[1]), _lead(*hi, lower=True) if all(hi) else "tie"),
        (_.H2H_RANKING, rank(cur[0]), rank(cur[1]), _lead(*cur, lower=True) if all(cur) else "tie"),
        (_.H2H_AGE, str(pl.get("Age") or "-"), str(op.get("Age") or "-"), "tie"),
        (
            _.H2H_WEIGHT,
            _(_.H2H_KG, kg=pl["WeightKg"]) if pl.get("WeightKg") else "-",
            _(_.H2H_KG, kg=op["WeightKg"]) if op.get("WeightKg") else "-",
            "tie",
        ),
        (
            _.H2H_HEIGHT,
            _(_.H2H_CM, cm=pl["HeightCm"]) if pl.get("HeightCm") else "-",
            _(_.H2H_CM, cm=op["HeightCm"]) if op.get("HeightCm") else "-",
            "tie",
        ),
        (_.H2H_HANDEDNESS, hands.get(pl.get("PlayHand"), "-"), hands.get(op.get("PlayHand"), "-"), "tie"),
        (_.H2H_BACKHAND, backhands.get(pl.get("BackHand"), "-"), backhands.get(op.get("BackHand"), "-"), "tie"),
        (_.H2H_TURNED_PRO, str(pl.get("ProYear") or "-"), str(op.get("ProYear") or "-"), "tie"),
    ]
    return {"wins": wins, "career": career, "profile": profile, "meetings": meetings}


def prefetch(api, match_ref, hls):
    # Fetch everything the overlay shows into the shared cache (see API._stored). Best effort: the overlay fetches
    # whatever is missing itself.
    try:
        tid, year, match_id = match_ref.split("_", 2)
    except (AttributeError, ValueError):
        return

    def fetch(name, call):
        try:
            return call()
        except Exception as e:
            log.debug(f"Match Info: prefetching {name} failed ({e})")
            return None

    stats = fetch("stats", lambda: api.match_stats(tid, year, match_id)) or {}
    p1, p2 = ((stats.get(t) or {}).get("PlayerId") for t in ("PlayerTeam1", "PlayerTeam2"))
    if p1 and p2:
        fetch("head to head", lambda: api.head_to_head(p1, p2))
    fetch("draw", lambda: api.draw(tid, year))
    sync = _Sync.load(api, (tid, year, match_id), hls, p1)
    pa = timeline.playanywhere_event(sync.events) if sync else None
    if pa:
        fetch("key moments", lambda: api.key_moments(pa))


class _Sync:
    # Follows the video along the match timeline: video position -> program date-time -> the overlay state then.

    def __init__(self, api, ref, hls, p1):
        self._api, self._ref, self._hls, self._p1 = api, ref, hls, p1
        # (segments, playlist length, whether it is complete (VOD), when it was fetched), replaced as one value
        self._timing = ([], 0.0, True, 0.0)
        self.events, self.team_a_is_p1 = [], True

    @classmethod
    def load(cls, api, ref, hls, p1):
        if not hls:
            return None
        sync = cls(api, ref, hls, p1)
        try:
            sync.refresh()
        except Exception as e:  # the overlay works without it (eg. no timeline for this match)
            log.debug(f"Match Info: not following the video ({e})")
            return None
        return sync if sync._timing[0] and sync.events else None

    @property
    def live(self):
        return not self._timing[2]

    def refresh(self):
        master = self._api.playlist(self._hls)
        variant = timeline.variant_url(master, self._hls)
        segs, length, vod = timeline.segments(self._api.playlist(variant) if variant else master)
        if segs:  # one value, so a reader never sees segments from one fetch and the time of another
            self._timing = (segs, length, vod, time.time())
        self.events = self._api.timeline(*self._ref)
        # Team A is usually the stats' first player; check by id so the colours never swap.
        info = next((e.get("metadata") for e in self.events if e.get("event") == "MatchInfo#show"), None) or {}
        team_a = ((info.get("teamA") or {}).get("players") or [{}])[0].get("associationId")
        self.team_a_is_p1 = not (team_a and self._p1 and team_a != self._p1)

    def position(self):
        try:
            return xbmc.Player().getTime()
        except RuntimeError:
            return 0.0

    def _live_edge(self, timing):
        # The program date-time at the live edge now: the window's last segment end, moved on by the time since the
        # playlist was fetched.
        segs, length, _vod, fetched = timing
        start, pdt = segs[-1]
        return pdt + int((length - start) * 1000) + int((time.time() - fetched) * 1000)

    def now(self):
        # The timeline time for the current video position (None when nothing is playing).
        try:
            player = xbmc.Player()
            pos = player.getTime()
            total = player.getTotalTime()
        except RuntimeError:
            return None
        timing = self._timing
        if timing[2]:
            clock = timeline.wall_clock(timing[0], pos)
        else:
            # A live window slides, so the position is placed back from the live edge rather than from its start.
            clock = self._live_edge(timing) - int((total - pos) * 1000)
        return None if clock is None else clock + timeline.TIMECODE_OFFSET_MS

    def position_for(self, clock):
        # The video position of a timeline time (the inverse of now()).
        pdt = clock - timeline.TIMECODE_OFFSET_MS
        timing = self._timing
        if timing[2]:
            return timeline.position_at(timing[0], pdt)
        try:
            total = xbmc.Player().getTotalTime()
        except RuntimeError:
            return 0.0
        return max(total - (self._live_edge(timing) - pdt) / 1000, 0.0)

    def state(self):
        when = self.now()
        return timeline.state_at(self.events, when) if when is not None else {}


# Key Moments tags: (text in PlayAnywhere's English description, tag shown, its colour).
MOMENT_TAGS = (
    ("Break point", _.KEY_BREAK_POINT, BALL),
    ("Set point", _.KEY_SET_POINT, TEAL),
    ("Match point", _.KEY_MATCH_POINT, TEAL),
    ("First point", _.KEY_START, MUTED),
    ("Walk On", _.KEY_WALK_ON, MUTED),
)


def _moment(clip):
    # A Key Moments clip as the list shows it: who ("Basilashvili") over a coloured tag and the set and game.
    desc = clip.get("description") or clip.get("title") or ""
    who = re.match(r".* won by (.+)$", desc)
    walk = re.match(r"(.+) Walk On$", desc, re.I)
    tag, colour = next(((t, c) for key, t, c in MOMENT_TAGS if key.lower() in desc.lower()), ("", MUTED))
    game = clip.get("game_time") or (_.KEY_BEFORE_MATCH if walk else "")
    meta = f"[COLOR={colour}]{tag}[/COLOR]  [COLOR={MUTED}]{game}[/COLOR]" if tag else f"[COLOR={MUTED}]{game}[/COLOR]"
    return {
        "clock": timeline.parse_time(clip.get("clip_time") or ""),
        "who": (who or walk).group(1) if (who or walk) else "",
        "kind": desc,
        "meta": _b(meta),
        "thumb": clip.get("clip_thumbnail") or "",
    }


def _sentences(text):
    # One sentence per line (labels do not wrap, and a whole paragraph would truncate).
    return [part for part in re.split(r"(?<=[.?!])\s+", text.strip()) if part]


def _slot(team, drawline, placeholder):
    # Returns (surname, three-letter nationality) for a draw slot.
    if team and team.get("Player"):
        p = team["Player"]
        return (p.get("LastName") or ""), p.get("Nationality")
    players = (drawline or {}).get("Players") or []
    if players:
        return (players[0].get("LastName") or ""), players[0].get("Nationality")
    return (placeholder or "?"), None


def _fixture_rows(fx):
    # [(surname, nationality, [(games text, won that set)] per set)] for the top and bottom player of a fixture.
    res = fx.get("Result") or {}
    top = _slot(res.get("TeamTop"), fx.get("DrawLineTop"), fx.get("TopPlaceholderText"))
    if res.get("ResultReason") == "BYE" and not res.get("TeamBottom"):
        bottom = (BYE, None)
    else:
        bottom = _slot(res.get("TeamBottom"), fx.get("DrawLineBottom"), fx.get("BottomPlaceholderText"))
    # A bye (either side, flagged by the result or only by the placeholder) has no games to show.
    if BYE in (top[0].upper(), bottom[0].upper()):
        return [(*_bye(*top), []), (*_bye(*bottom), [])]
    sets = {s.get("SetNumber"): s for s in res.get("SetResults") or []}
    a_games, b_games = [], []
    for n in range(1, FX_SETS + 1):
        s = sets.get(n) or {}
        a, b = s.get("GamesA"), s.get("GamesB")
        if a is None or b is None:
            a_games.append(("-", False))
            b_games.append(("-", False))
        else:
            a_games.append((str(a), a > b))
            b_games.append((str(b), b > a))
    return [(*top, a_games), (*bottom, b_games)]


def _bye(name, code):
    return (BYE, None) if name.upper() == BYE else (name, code)


def _short_round(name):
    # A round button's label from the draw's (English) round name: "Round of 28" -> "R28", "Quarterfinal" -> "QF".
    if name.startswith("Round of "):
        return _(_.DRAW_ROUND, size=name.split()[-1])
    return {"Quarterfinal": _.DRAW_QF, "Semifinal": _.DRAW_SF, "Final": _.DRAW_FINAL}.get(name, name[:3])

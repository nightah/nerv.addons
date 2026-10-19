import os
import threading

import xbmcgui
from slyguy import gui
from slyguy.constants import ADDON_PATH

from .language import _

# Static control ids in MatchInfo.xml
TAB_STATS, TAB_DRAW, TAB_H2H = 10, 11, 12
SET_BTN_BASE, SET_BTN_MAX = 20, 5  # buttons 20..24: Match + up to four sets
TITLE_ID, SCORE_ID, BODY_ID = 100, 101, 50
TABS = (TAB_STATS, TAB_DRAW, TAB_H2H)
TAB_X = {TAB_STATS: 1456, TAB_DRAW: 1604, TAB_H2H: 1752}

POLL_SECONDS = 20

# Web palette: dark navy panel, teal accent, muted labels.
TEAL = "FF2FB8AC"
WHITE = "FFE6EAF0"
MUTED = "FF8A93A0"
CARD = "14FFFFFF"

# Layout (1920x1080)
CX, CW = 1456, 438
LVAL_X, LVAL_W = 1456, 84
NAME_X, NAME_W = 1544, 262
RVAL_X, RVAL_W = 1810, 84
BAR_GAP = 96
SERVICE_Y = 258
AL_LEFT, AL_RIGHT, AL_CENTRE = 4, 5, 6

# (display label, API key) using the web's wording.
SERVICE_ROWS = (
    ("Aces", "Aces"),
    ("Double Faults", "DoubleFaults"),
    ("First Serve In", "FirstServe"),
    ("First Serve Points Won", "FirstServePointsWon"),
    ("Second Serve Points Won", "SecondServePointsWon"),
    ("Break Points Saved", "BreakPointsSaved"),
    ("Service Games Played", "ServiceGamesPlayed"),
)
RETURN_ROWS = (
    ("First Return Points Won", "FirstServeReturnPointsWon"),
    ("Second Return Points Won", "SecondServeReturnPointsWon"),
    ("Break Points Converted", "BreakPointsConverted"),
    ("Return Games Played", "ReturnGamesPlayed"),
)
SECTIONS = (("SERVICE", "ServiceStats", SERVICE_ROWS), ("RETURN", "ReturnStats", RETURN_ROWS))
RATIO_KEYS = {"BreakPointsSaved", "BreakPointsConverted"}


def _value(stat, key):
    # Match the web: a ratio for break points, a percentage for percentage stats, otherwise the raw count.
    if not isinstance(stat, dict):
        return "-"
    if key in RATIO_KEYS and "Dividend" in stat:
        return f"{stat['Dividend']}/{stat['Divisor']}"
    if "Percent" in stat:
        return f"{round(stat['Percent'])}%"
    if "Number" in stat:
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


def _set_stats(team, set_num):
    sets = team.get("Sets") or []
    chosen = next((s for s in sets if s.get("SetNumber") == set_num), None)
    return (chosen or (sets[0] if sets else {})).get("Stats") or {}


def _white():
    return os.path.join(ADDON_PATH, "resources", "skins", "Default", "media", "white.png")


def _headshot(sid):
    path = os.path.join(ADDON_PATH, "resources", "media", "players", f"{sid}.png")
    return path if sid and os.path.exists(path) else None


class MatchInfo(xbmcgui.WindowXMLDialog):
    @classmethod
    def show(cls, api, match_ref, title):
        try:
            tid, year, match_id = match_ref.split("_", 2)
        except ValueError:
            return
        stats = api.match_stats(tid, year, match_id) or {}
        revealed = True
        if stats.get("Status") == "Finished":
            revealed = gui.yes_no(_.SPOILER_PROMPT)
        dialog = cls("MatchInfo.xml", ADDON_PATH, "Default", "1080i")
        dialog.setup(api, tid, year, match_id, title, revealed, stats)
        dialog.doModal()
        del dialog

    def setup(self, api, tid, year, match_id, title, revealed, stats):
        self._api = api
        self._tid, self._year, self._match_id = tid, year, match_id
        self._title = title or ""
        self._revealed = revealed
        self._tab = TAB_STATS
        self._set_num = 0
        self._stop = threading.Event()
        self._cache = {"stats": stats}
        self._rows = []
        self._stat_ctrls = []
        self._set_map = {}

    # --- lifecycle ---

    def onInit(self):
        self.getControl(TITLE_ID).setLabel(self._title)
        self.getControl(TAB_STATS).setLabel(_.TAB_STATS)
        self.getControl(TAB_DRAW).setLabel(_.TAB_DRAW)
        self.getControl(TAB_H2H).setLabel(_.TAB_H2H)
        self._indicator = xbmcgui.ControlImage(TAB_X[TAB_STATS], 136, 140, 3, _white(), colorDiffuse=f"0x{TEAL}")
        self.addControl(self._indicator)
        self._spoiler = xbmcgui.ControlLabel(
            CX, 360, CW, 60, _.SPOILER_HIDDEN, font="font10", textColor=MUTED, alignment=AL_CENTRE
        )
        self.addControl(self._spoiler)
        self._build_header()
        self._build_rows()
        self._build_set_toggle()
        self._set_tab(TAB_STATS)
        threading.Thread(target=self._poll, daemon=True).start()

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_STOP):
            self.close()

    def onClick(self, control_id):
        if control_id in TABS:
            self._set_tab(control_id)
        elif control_id in self._set_map:
            self._set_num = self._set_map[control_id]
            self._render()

    def close(self):
        self._stop.set()
        super().close()

    # --- programmatic controls ---

    def _build_header(self):
        # Two players: headshot (when vendored), surname and three-letter country code, from the head-to-head data.
        data = self._h2h()
        pl, op = data.get("Player") or {}, data.get("Opponent") or {}
        p1, p2 = self._player_ids()
        for sid, person, align in ((p1, pl, AL_LEFT), (p2, op, AL_RIGHT)):
            shot = _headshot(sid)
            if shot:
                x = CX if align == AL_LEFT else CX + CW - 56
                self._add(xbmcgui.ControlImage(x, 136, 56, 56, shot))
            tx = CX + 64 if align == AL_LEFT else CX
            tw = CW - 64
            name = person.get("LastName") or ""
            code = person.get("NatlId") or ""
            self._add(xbmcgui.ControlLabel(tx, 140, tw, 24, name, font="font11", textColor=WHITE, alignment=align))
            self._add(xbmcgui.ControlLabel(tx, 166, tw, 22, code, font="font10", textColor=MUTED, alignment=align))

    def _build_rows(self):
        y = SERVICE_Y
        for heading, group, rows in SECTIONS:
            self._add(xbmcgui.ControlImage(CX, y, CW, 26, _white(), colorDiffuse=f"0x{CARD}"))
            self._add(
                xbmcgui.ControlLabel(
                    CX + 10, y, CW - 20, 26, heading, font="font10", textColor=MUTED, alignment=AL_LEFT
                )
            )
            y += 34
            for label, key in rows:
                lval = self._add(xbmcgui.ControlLabel(LVAL_X, y, LVAL_W, 22, "", font="font10", alignment=AL_RIGHT))
                self._add(
                    xbmcgui.ControlLabel(
                        NAME_X, y, NAME_W, 22, label, font="font10", textColor=WHITE, alignment=AL_CENTRE
                    )
                )
                rval = self._add(xbmcgui.ControlLabel(RVAL_X, y, RVAL_W, 22, "", font="font10", alignment=AL_LEFT))
                lbar = self._add(xbmcgui.ControlImage(CX, y + 24, 1, 4, _white(), colorDiffuse=f"0x{TEAL}"))
                rbar = self._add(xbmcgui.ControlImage(CX + CW, y + 24, 1, 4, _white(), colorDiffuse=f"0x{TEAL}"))
                self._rows.append({"group": group, "key": key, "lval": lval, "rval": rval, "lbar": lbar, "rbar": rbar})
                y += 38
            y += 10

    def _build_set_toggle(self):
        team = (self._stats().get("PlayerTeam1") or {}).get("Sets") or []
        sets = sorted({s.get("SetNumber") for s in team if s.get("SetNumber")})
        items = [(_.STATS_MATCH, 0)] + [(_(_.STATS_SET, n=n), n) for n in sets]
        visible = []
        for i in range(SET_BTN_MAX):
            btn = self.getControl(SET_BTN_BASE + i)
            if i < len(items):
                label, num = items[i]
                btn.setLabel(label)
                btn.setVisible(True)
                self._set_map[SET_BTN_BASE + i] = num
                visible.append(btn)
            else:
                btn.setVisible(False)
        for i, btn in enumerate(visible):
            btn.controlLeft(visible[i - 1])
            btn.controlRight(visible[(i + 1) % len(visible)])

    def _add(self, control):
        self.addControl(control)
        self._stat_ctrls.append(control)
        return control

    # --- tab switching / rendering ---

    def _set_tab(self, tab):
        self._tab = tab
        self._indicator.setPosition(TAB_X[tab], 136)
        stats_on = tab == TAB_STATS and self._revealed
        for ctrl in self._stat_ctrls:
            ctrl.setVisible(stats_on)
        for cid in self._set_map:
            self.getControl(cid).setVisible(stats_on)
        self._spoiler.setVisible(tab == TAB_STATS and not self._revealed)
        self.getControl(BODY_ID).setVisible(tab in (TAB_DRAW, TAB_H2H))
        self._render()

    def _render(self):
        if self._tab == TAB_STATS:
            self.getControl(SCORE_ID).setLabel(self._score_text() if self._revealed else "")
            if self._revealed:
                self._render_stats()
        else:
            self.getControl(SCORE_ID).setLabel("")
            self.getControl(BODY_ID).setText(self._draw_text() if self._tab == TAB_DRAW else self._h2h_text())

    def _render_stats(self):
        data = self._stats()
        s1 = _set_stats(data.get("PlayerTeam1") or {}, self._set_num)
        s2 = _set_stats(data.get("PlayerTeam2") or {}, self._set_num)
        avail = CW - BAR_GAP
        for row in self._rows:
            g1 = (s1.get(row["group"]) or {}).get(row["key"])
            g2 = (s2.get(row["group"]) or {}).get(row["key"])
            n1, n2 = _numeric(g1), _numeric(g2)
            row["lval"].setLabel(self._lead(_value(g1, row["key"]), n1 >= n2 and (n1 or n2)))
            row["rval"].setLabel(self._lead(_value(g2, row["key"]), n2 >= n1 and (n1 or n2)))
            total = n1 + n2
            lw = max(int(avail * n1 / total) if total else 0, 1)
            rw = max(int(avail * n2 / total) if total else 0, 1)
            row["lbar"].setWidth(lw)
            row["rbar"].setWidth(rw)
            row["rbar"].setPosition(CX + CW - rw, row["rbar"].getPosition()[1])

    @staticmethod
    def _lead(text, lead):
        return f"[COLOR={TEAL}]{text}[/COLOR]" if lead else text

    # --- data ---

    def _stats(self):
        if "stats" not in self._cache:
            self._cache["stats"] = self._api.match_stats(self._tid, self._year, self._match_id) or {}
        return self._cache["stats"]

    def _player_ids(self):
        data = self._stats()
        return (data.get("PlayerTeam1") or {}).get("PlayerId"), (data.get("PlayerTeam2") or {}).get("PlayerId")

    def _h2h(self):
        if "h2h" not in self._cache:
            p1, p2 = self._player_ids()
            self._cache["h2h"] = (self._api.head_to_head(p1, p2) if p1 and p2 else {}) or {}
        return self._cache["h2h"]

    def _score_text(self):
        data = self._stats()
        t1 = (data.get("PlayerTeam1") or {}).get("Sets") or []
        t2 = {s.get("SetNumber"): s for s in (data.get("PlayerTeam2") or {}).get("Sets") or []}
        parts = []
        for s in t1:
            n = s.get("SetNumber")
            if not n:
                continue
            a, b = s.get("SetScore"), t2.get(n, {}).get("SetScore")
            if a is not None and b is not None:
                parts.append(f"{a}-{b}")
        score = " ".join(parts)
        status = data.get("Status")
        if status and status != "Finished":
            return f"{score}   [COLOR={TEAL}]LIVE[/COLOR]".strip()
        return f"{score}   ({status})".strip() if status else score

    # --- poll ---

    def _poll(self):
        while not self._stop.wait(POLL_SECONDS):
            if (self._cache.get("stats") or {}).get("Status") == "Finished":
                return
            self._cache.pop("stats", None)
            self._stats()
            if self._tab == TAB_STATS and self._revealed:
                self._render()

    # --- draw / head-to-head (text) ---

    def _h2h_text(self):
        data = self._h2h()
        pl, op = data.get("Player") or {}, data.get("Opponent") or {}
        if not pl or not op:
            return _.NO_MATCH_INFO
        header = _(
            _.H2H_RECORD,
            p1=pl.get("LastName"),
            wins1=pl.get("H2HWins", 0),
            wins2=op.get("H2HWins", 0),
            p2=op.get("LastName"),
        )
        lines = [f"[B][COLOR={TEAL}]{header}[/COLOR][/B]", ""]
        for meet in data.get("CountableTournaments") or []:
            lines.append(
                f"{meet.get('TournamentYear')} {meet.get('TournamentTitle')} ({meet.get('RoundName')}): "
                f"{meet.get('WinningLastName')} {meet.get('ResultString') or ''}".rstrip()
            )
        return "\n".join(lines)

    def _draw_text(self):
        if "draw" not in self._cache:
            self._cache["draw"] = self._api.draw(self._tid, self._year) or {}
        ms = (self._cache["draw"] or {}).get("MS") or {}
        lines = []
        for rnd in reversed(ms.get("Rounds") or []):
            fixtures = rnd.get("Fixtures") or []
            if not fixtures:
                continue
            lines.append(f"[B][COLOR={TEAL}]{rnd.get('RoundName')}[/COLOR][/B]")
            for fx in fixtures:
                res = fx.get("Result") or {}
                top = _slot(res.get("TeamTop"), fx.get("DrawLineTop"), fx.get("TopPlaceholderText"))
                if res.get("ResultReason") == "BYE" and not res.get("TeamBottom"):
                    bottom = "(bye)"
                else:
                    bottom = _slot(res.get("TeamBottom"), fx.get("DrawLineBottom"), fx.get("BottomPlaceholderText"))
                if res.get("Winner") == 1:
                    top = f"[B]{top}[/B]"
                elif res.get("Winner") == 2:
                    bottom = f"[B]{bottom}[/B]"
                lines.append(f"  {top} v {bottom}  {res.get('ResultString') or ''}".rstrip())
            lines.append("")
        return "\n".join(lines).strip() or _.NO_MATCH_INFO


def _slot(team, drawline, placeholder):
    if team and team.get("Player"):
        return team["Player"].get("LastName") or ""
    players = (drawline or {}).get("Players") or []
    if players:
        return players[0].get("LastName") or ""
    return placeholder or "?"

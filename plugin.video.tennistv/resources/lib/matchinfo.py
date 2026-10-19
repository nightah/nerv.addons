import os
import threading

import xbmcgui
from slyguy import gui
from slyguy.constants import ADDON_PATH

from .language import _

# Control ids in MatchInfo.xml
TAB_STATS, TAB_DRAW, TAB_H2H = 10, 11, 12
TITLE_ID, SCORE_ID, BODY_ID = 100, 101, 50
TABS = (TAB_STATS, TAB_DRAW, TAB_H2H)
TAB_X = {TAB_STATS: 1448, TAB_DRAW: 1598, TAB_H2H: 1748}

POLL_SECONDS = 20

# Colours (AARRGGBB) matching the Tennis TV web overlay: dark navy panel, teal accent, muted labels.
TEAL = "FF2FB8AC"
WHITE = "FFE6EAF0"
MUTED = "FF8A93A0"
TRACK_BG = "22FFFFFF"

# Layout (1920x1080): a thin right-hand panel.
CONTENT_X = 1448
LVAL_X, LVAL_W = 1448, 90
NAME_X, NAME_W = 1540, 260
RVAL_X, RVAL_W = 1802, 90
TRACK_X, TRACK_W = 1448, 444
START_Y, HEAD_H, ROW_H, BAR_DY, BAR_H = 186, 34, 46, 30, 6
AL_LEFT, AL_RIGHT, AL_CENTRE = 4, 5, 6

SERVICE_ROWS = (
    ("Aces", "Aces"),
    ("Double Faults", "DoubleFaults"),
    ("First Serve", "FirstServe"),
    ("1st Serve Points Won", "FirstServePointsWon"),
    ("2nd Serve Points Won", "SecondServePointsWon"),
    ("Break Points Saved", "BreakPointsSaved"),
    ("Service Games Played", "ServiceGamesPlayed"),
)
RETURN_ROWS = (
    ("1st Return Points Won", "FirstServeReturnPointsWon"),
    ("2nd Return Points Won", "SecondServeReturnPointsWon"),
    ("Break Points Converted", "BreakPointsConverted"),
    ("Return Games Played", "ReturnGamesPlayed"),
)
SECTIONS = (("SERVICE", "ServiceStats", SERVICE_ROWS), ("RETURN", "ReturnStats", RETURN_ROWS))


def _value(stat):
    if not isinstance(stat, dict):
        return "-"
    if "Percent" in stat and stat.get("Divisor"):
        return f"{stat['Dividend']}/{stat['Divisor']} ({round(stat['Percent'])}%)"
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


def _match_totals(team):
    sets = team.get("Sets") or []
    whole = next((s for s in sets if s.get("SetNumber") == 0), None)
    return (whole or (sets[0] if sets else {})).get("Stats") or {}


def _white():
    return os.path.join(ADDON_PATH, "resources", "skins", "Default", "media", "white.png")


class MatchInfo(xbmcgui.WindowXMLDialog):
    @classmethod
    def show(cls, api, match_ref, title):
        try:
            tid, year, match_id = match_ref.split("_", 2)
        except ValueError:
            return
        stats = api.match_stats(tid, year, match_id) or {}
        # A finished match is a replay: hide the score and stats behind a spoiler prompt.
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
        self._stop = threading.Event()
        self._cache = {"stats": stats}
        self._rows = []
        self._stat_ctrls = []

    # --- lifecycle ---

    def onInit(self):
        self.getControl(TITLE_ID).setLabel(self._title)
        self.getControl(TAB_STATS).setLabel(_.TAB_STATS)
        self.getControl(TAB_DRAW).setLabel(_.TAB_DRAW)
        self.getControl(TAB_H2H).setLabel(_.TAB_H2H)
        self._indicator = xbmcgui.ControlImage(TAB_X[TAB_STATS], 162, 142, 3, _white(), colorDiffuse=f"0x{TEAL}")
        self.addControl(self._indicator)
        self._spoiler = xbmcgui.ControlLabel(
            CONTENT_X, 320, TRACK_W, 60, _.SPOILER_HIDDEN, font="font12", textColor=MUTED, alignment=AL_CENTRE
        )
        self.addControl(self._spoiler)
        self._build_rows()
        self._set_tab(TAB_STATS)
        threading.Thread(target=self._poll, daemon=True).start()

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_STOP):
            self.close()

    def onClick(self, control_id):
        if control_id in TABS:
            self._set_tab(control_id)

    def close(self):
        self._stop.set()
        super().close()

    # --- stat row controls (built once, updated on render) ---

    def _build_rows(self):
        y = START_Y
        for heading, group, rows in SECTIONS:
            self._add(xbmcgui.ControlLabel(CONTENT_X, y, TRACK_W, HEAD_H, heading, font="font12", textColor=MUTED))
            y += HEAD_H
            for label, key in rows:
                lval = self._add(xbmcgui.ControlLabel(LVAL_X, y, LVAL_W, 26, "", font="font12", alignment=AL_RIGHT))
                self._add(
                    xbmcgui.ControlLabel(
                        NAME_X, y, NAME_W, 26, label, font="font12", textColor=WHITE, alignment=AL_CENTRE
                    )
                )
                rval = self._add(xbmcgui.ControlLabel(RVAL_X, y, RVAL_W, 26, "", font="font12", alignment=AL_LEFT))
                self._add(
                    xbmcgui.ControlImage(TRACK_X, y + BAR_DY, TRACK_W, BAR_H, _white(), colorDiffuse=f"0x{TRACK_BG}")
                )
                fill = self._add(
                    xbmcgui.ControlImage(TRACK_X, y + BAR_DY, TRACK_W, BAR_H, _white(), colorDiffuse=f"0x{TEAL}")
                )
                self._rows.append({"group": group, "key": key, "lval": lval, "rval": rval, "fill": fill})
                y += ROW_H
            y += 12

    def _add(self, control):
        self.addControl(control)
        self._stat_ctrls.append(control)
        return control

    # --- tab switching / rendering ---

    def _set_tab(self, tab):
        self._tab = tab
        self._indicator.setPosition(TAB_X[tab], 162)
        stats_on = tab == TAB_STATS and self._revealed
        for ctrl in self._stat_ctrls:
            ctrl.setVisible(stats_on)
        self._spoiler.setVisible(tab == TAB_STATS and not self._revealed)
        self.getControl(BODY_ID).setVisible(tab in (TAB_DRAW, TAB_H2H))
        self._render()

    def _render(self):
        if self._tab == TAB_STATS:
            self.getControl(SCORE_ID).setLabel(self._score_text() if self._revealed else "")
            if self._revealed:
                self._render_stats()
        elif self._tab == TAB_DRAW:
            self.getControl(SCORE_ID).setLabel("")
            self.getControl(BODY_ID).setText(self._draw_text())
        else:
            self.getControl(SCORE_ID).setLabel("")
            self.getControl(BODY_ID).setText(self._h2h_text())

    def _render_stats(self):
        data = self._stats()
        s1 = _match_totals(data.get("PlayerTeam1") or {})
        s2 = _match_totals(data.get("PlayerTeam2") or {})
        for row in self._rows:
            g1 = (s1.get(row["group"]) or {}).get(row["key"])
            g2 = (s2.get(row["group"]) or {}).get(row["key"])
            n1, n2 = _numeric(g1), _numeric(g2)
            row["lval"].setLabel(self._coloured(_value(g1), n1 >= n2 and (n1 or n2)))
            row["rval"].setLabel(self._coloured(_value(g2), n2 >= n1 and (n1 or n2)))
            total = n1 + n2
            row["fill"].setWidth(int(TRACK_W * n1 / total) if total else 0)

    @staticmethod
    def _coloured(text, lead):
        return f"[COLOR={TEAL}]{text}[/COLOR]" if lead else text

    def _stats(self):
        if "stats" not in self._cache:
            self._cache["stats"] = self._api.match_stats(self._tid, self._year, self._match_id) or {}
        return self._cache["stats"]

    def _player_ids(self):
        data = self._stats()
        return (data.get("PlayerTeam1") or {}).get("PlayerId"), (data.get("PlayerTeam2") or {}).get("PlayerId")

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
            return f"{score}   [COLOR={TEAL}]* LIVE[/COLOR]".strip()
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
        if "h2h" not in self._cache:
            p1, p2 = self._player_ids()
            self._cache["h2h"] = self._api.head_to_head(p1, p2) if p1 and p2 else {}
        data = self._cache["h2h"] or {}
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

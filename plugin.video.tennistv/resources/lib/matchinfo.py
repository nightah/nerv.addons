import contextlib
import os
import threading

import xbmcgui
from slyguy import gui
from slyguy.constants import ADDON_PATH

from .language import _

# Section tabs / sub-tabs / toggles (ids in MatchInfo.xml)
SEC_LIVE, SEC_DRAW, SEC_KEY = 10, 11, 12
SUB_STATS, SUB_INSIGHTS, SUB_H2H = 13, 14, 15
SET_BASE, SET_MAX = 30, 5
ROUND_BASE, ROUND_MAX = 40, 7
TITLE_ID, BODY_ID = 100, 50
SECTIONS = (SEC_LIVE, SEC_DRAW, SEC_KEY)
SUBS = (SUB_STATS, SUB_INSIGHTS, SUB_H2H)
SEC_X = {SEC_LIVE: 1524, SEC_DRAW: 1648, SEC_KEY: 1772}
SUB_X = {SUB_STATS: 1524, SUB_INSIGHTS: 1650, SUB_H2H: 1776}

POLL_SECONDS = 15

TEAL = "FF2FB8AC"
BLUE = "FF4F9BE8"
P1_DIM, P2_DIM = "802FB8AC", "804F9BE8"
WHITE = "FFE6EAF0"
MUTED = "FF8A93A0"
CARD = "14FFFFFF"
FRAME_BG = "22FFFFFF"

# Layout (1920x1080): a thin right-hand panel.
CX, CW = 1524, 372
CENTRE = CX + CW // 2
LCOL, RCOL = CX + 60, CX + CW - 60  # player column centres
LVAL_X, LVAL_W = 1524, 70
NAME_X, NAME_W = 1598, 232
RVAL_X, RVAL_W = 1826, 70
ROWS_Y = 268
AL_LEFT, AL_RIGHT, AL_CENTRE = 4, 5, 6

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
GROUPS = (("SERVICE", "ServiceStats", SERVICE_ROWS), ("RETURN", "ReturnStats", RETURN_ROWS))
RATIO_KEYS = {"BreakPointsSaved", "BreakPointsConverted"}


def _value(stat, key):
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


def _white():
    return os.path.join(ADDON_PATH, "resources", "skins", "Default", "media", "white.png")


def _headshot(sid):
    path = _media("players", f"{sid}.png")
    return path if sid and os.path.exists(path) else None


def _flag(code):
    path = _media("flags", f"{(code or '').lower()}.png")
    return path if code and os.path.exists(path) else None


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
        self._section, self._sub = SEC_LIVE, SUB_STATS
        self._set_num, self._round_idx = 0, 0
        self._stop = threading.Event()
        self._cache = {"stats": stats}
        self._rows, self._stat_ctrls, self._set_map = [], [], {}
        self._round_ids, self._rounds_built, self._draw_ctrls = [], False, []

    # --- lifecycle ---

    def onInit(self):
        self.getControl(SEC_LIVE).setLabel(_.SEC_LIVE_STATS)
        self.getControl(SEC_DRAW).setLabel(_.TAB_DRAW)
        self.getControl(SEC_KEY).setLabel(_.SEC_KEY)
        self.getControl(SUB_STATS).setLabel(_.TAB_STATS)
        self.getControl(SUB_INSIGHTS).setLabel(_.SUB_INSIGHTS)
        self.getControl(SUB_H2H).setLabel(_.SUB_H2H)
        self._sec_ind = self._mk(xbmcgui.ControlImage(SEC_X[SEC_LIVE], 104, 120, 3, _white(), colorDiffuse=f"0x{TEAL}"))
        self._sub_ind = self._mk(
            xbmcgui.ControlImage(SUB_X[SUB_STATS], 142, 120, 3, _white(), colorDiffuse=f"0x{TEAL}")
        )
        self._spoiler = self._mk(
            xbmcgui.ControlLabel(CX, 360, CW, 60, _.SPOILER_HIDDEN, font="font10", textColor=MUTED, alignment=AL_CENTRE)
        )
        self._build_header()
        self._build_centre()
        self._build_rows()
        self._build_set_toggle()
        self._set_section(SEC_LIVE)
        threading.Thread(target=self._poll, daemon=True).start()

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_STOP):
            self.close()

    def onClick(self, cid):
        if cid in SECTIONS:
            self._set_section(cid)
        elif cid in SUBS:
            self._sub = cid
            self._refresh()
        elif cid in self._set_map:
            self._set_num = self._set_map[cid]
            self._render()
        elif cid in self._round_ids:
            self._round_idx = self._round_ids.index(cid)
            self._render()

    def close(self):
        self._stop.set()
        super().close()

    # --- build (programmatic controls) ---

    def _mk(self, control):
        self.addControl(control)
        return control

    def _stat(self, control):
        self.addControl(control)
        self._stat_ctrls.append(control)
        return control

    def _build_header(self):
        data = self._h2h()
        pl, op = data.get("Player") or {}, data.get("Opponent") or {}
        p1, p2 = self._player_ids()
        for col, sid, person, accent in ((LCOL, p1, pl, TEAL), (RCOL, p2, op, BLUE)):
            self._stat(xbmcgui.ControlImage(col - 32, 148, 64, 64, _white(), colorDiffuse=f"0x{accent}"))
            shot = _headshot(sid) or _white()
            diffuse = {} if _headshot(sid) else {"colorDiffuse": f"0x{FRAME_BG}"}
            self._stat(xbmcgui.ControlImage(col - 30, 150, 60, 60, shot, **diffuse))
            last = person.get("LastName") or ""
            first = person.get("FirstName") or ""
            code = person.get("NatlId") or ""
            self._stat(
                xbmcgui.ControlLabel(col - 62, 216, 124, 22, last, font="font11", textColor=WHITE, alignment=AL_CENTRE)
            )
            self._stat(
                xbmcgui.ControlLabel(col - 62, 240, 124, 20, first, font="font10", textColor=MUTED, alignment=AL_CENTRE)
            )
            flag = _flag(code)
            if flag:
                self._stat(xbmcgui.ControlImage(col - 34, 266, 24, 16, flag))
            self._stat(
                xbmcgui.ControlLabel(col - 6, 264, 48, 20, code, font="font10", textColor=MUTED, alignment=AL_LEFT)
            )

    def _build_centre(self):
        # The score card between the players: a FINISHED/LIVE header and the per-set scores (Option A styling).
        self._status = self._stat(
            xbmcgui.ControlLabel(1640, 184, 140, 22, "", font="font10", textColor=MUTED, alignment=AL_CENTRE)
        )
        self._setlabels = [
            self._stat(xbmcgui.ControlLabel(1640, 208 + i * 24, 140, 22, "", font="font11", alignment=AL_CENTRE))
            for i in range(3)
        ]

    def _render_centre(self):
        status = self._stats().get("Status")
        if status == "Finished":
            self._status.setLabel("[B]FINISHED[/B]")
        elif status:
            self._status.setLabel(f"[B][COLOR={TEAL}]LIVE[/COLOR][/B]")
        else:
            self._status.setLabel("")
        sets = self._set_scores()
        for i, lbl in enumerate(self._setlabels):
            if i < len(sets):
                a, b = sets[i]
                lc = TEAL if a > b else P1_DIM
                rc = BLUE if b > a else P2_DIM
                lbl.setLabel(
                    f"[COLOR={MUTED}]SET {i + 1}[/COLOR]  "
                    f"[COLOR={lc}]{a}[/COLOR] [COLOR={MUTED}]|[/COLOR] [COLOR={rc}]{b}[/COLOR]"
                )
            else:
                lbl.setLabel("")

    def _set_scores(self):
        data = self._stats()
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
            self._stat(xbmcgui.ControlImage(CX, y, CW, 26, _white(), colorDiffuse=f"0x{CARD}"))
            self._stat(
                xbmcgui.ControlLabel(CX, y, CW, 26, heading, font="font10", textColor=MUTED, alignment=AL_CENTRE)
            )
            y += 34
            for label, key in rows:
                lval = self._stat(xbmcgui.ControlLabel(LVAL_X, y, LVAL_W, 22, "", font="font10", alignment=AL_RIGHT))
                self._stat(
                    xbmcgui.ControlLabel(
                        NAME_X, y, NAME_W, 22, label, font="font10", textColor=WHITE, alignment=AL_CENTRE
                    )
                )
                rval = self._stat(xbmcgui.ControlLabel(RVAL_X, y, RVAL_W, 22, "", font="font10", alignment=AL_LEFT))
                lbar = self._stat(xbmcgui.ControlImage(CX, y + 24, 1, 4, _white(), colorDiffuse=f"0x{TEAL}"))
                rbar = self._stat(xbmcgui.ControlImage(CX, y + 24, 1, 4, _white(), colorDiffuse=f"0x{BLUE}"))
                self._rows.append({"group": group, "key": key, "lval": lval, "rval": rval, "lbar": lbar, "rbar": rbar})
                y += 38
            y += 10

    def _build_set_toggle(self):
        team = (self._stats().get("PlayerTeam1") or {}).get("Sets") or []
        sets = sorted({s.get("SetNumber") for s in team if s.get("SetNumber")})
        items = [(_.STATS_MATCH, 0)] + [(_(_.STATS_SET, n=n), n) for n in sets]
        for i in range(SET_MAX):
            btn = self.getControl(SET_BASE + i)
            if i < len(items):
                btn.setLabel(items[i][0])
                btn.setVisible(True)
                self._set_map[SET_BASE + i] = items[i][1]
            else:
                btn.setVisible(False)

    def _build_rounds(self):
        self._rounds_built = True
        ms = (self._draw() or {}).get("MS") or {}
        self._draw_rounds = [r for r in reversed(ms.get("Rounds") or []) if r.get("Fixtures")]
        for i in range(ROUND_MAX):
            btn = self.getControl(ROUND_BASE + i)
            if i < len(self._draw_rounds):
                btn.setLabel(_short_round(self._draw_rounds[i].get("RoundName") or ""))
                btn.setVisible(True)
                self._round_ids.append(ROUND_BASE + i)
            else:
                btn.setVisible(False)

    # --- section / sub switching ---

    def _set_section(self, section):
        self._section = section
        if section == SEC_DRAW and not self._rounds_built:
            self._build_rounds()
        names = {SEC_LIVE: _.SEC_LIVE_STATS, SEC_DRAW: _.TAB_DRAW, SEC_KEY: _.SEC_KEY}
        self.getControl(TITLE_ID).setLabel(names[section])
        self._refresh()

    def _refresh(self):
        live = self._section == SEC_LIVE
        stats_view = live and self._sub == SUB_STATS
        show_stats = stats_view and self._revealed
        for cid in SUBS:
            self.getControl(cid).setVisible(live)
        for cid in self._round_ids:
            self.getControl(cid).setVisible(self._section == SEC_DRAW)
        for cid in self._set_map:
            self.getControl(cid).setVisible(show_stats)
        for ctrl in self._stat_ctrls:
            ctrl.setVisible(show_stats)
        self._spoiler.setVisible(stats_view and not self._revealed)
        if self._section != SEC_DRAW:
            self._clear_draw()
        text_view = (live and self._sub in (SUB_INSIGHTS, SUB_H2H)) or self._section == SEC_KEY
        self.getControl(BODY_ID).setVisible(text_view)
        self._sub_ind.setVisible(live)
        self._sub_ind.setPosition(SUB_X[self._sub], 142)
        self._sec_ind.setPosition(SEC_X[self._section], 104)
        self._render()

    def _render(self):
        if self._section == SEC_LIVE and self._sub == SUB_STATS:
            if self._revealed:
                self._render_stats()
        elif self._section == SEC_LIVE and self._sub == SUB_INSIGHTS:
            self.getControl(BODY_ID).setText(_.INSIGHTS_NOTE)
        elif self._section == SEC_LIVE and self._sub == SUB_H2H:
            self.getControl(BODY_ID).setText(self._h2h_text())
        elif self._section == SEC_DRAW:
            self._render_draw()
        elif self._section == SEC_KEY:
            self.getControl(BODY_ID).setText(_.KEY_NOTE)

    def _render_stats(self):
        data = self._stats()
        self._render_centre()
        s1 = _set_stats(data.get("PlayerTeam1") or {}, self._set_num)
        s2 = _set_stats(data.get("PlayerTeam2") or {}, self._set_num)
        half = CW // 2
        for row in self._rows:
            g1 = (s1.get(row["group"]) or {}).get(row["key"])
            g2 = (s2.get(row["group"]) or {}).get(row["key"])
            n1, n2 = _numeric(g1), _numeric(g2)
            row["lval"].setLabel(
                f"[COLOR={TEAL if n1 >= n2 and (n1 or n2) else P1_DIM}]{_value(g1, row['key'])}[/COLOR]"
            )
            row["rval"].setLabel(
                f"[COLOR={BLUE if n2 >= n1 and (n1 or n2) else P2_DIM}]{_value(g2, row['key'])}[/COLOR]"
            )
            lf, rf = _fills(g1, g2, n1, n2)
            lw, rw = max(int(lf * half), 1), max(int(rf * half), 1)
            y = row["lbar"].getPosition()[1]
            row["lbar"].setWidth(lw)
            row["lbar"].setPosition(CENTRE - lw, y)
            row["rbar"].setWidth(rw)
            row["rbar"].setPosition(CENTRE, y)

    # --- data ---

    def _stats(self):
        if "stats" not in self._cache:
            self._cache["stats"] = self._api.match_stats(self._tid, self._year, self._match_id) or {}
        return self._cache["stats"]

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

    def _score_text(self):
        data = self._stats()
        t1 = (data.get("PlayerTeam1") or {}).get("Sets") or []
        t2 = {s.get("SetNumber"): s for s in (data.get("PlayerTeam2") or {}).get("Sets") or []}
        parts = []
        for s in t1:
            n = s.get("SetNumber")
            if n and s.get("SetScore") is not None and t2.get(n, {}).get("SetScore") is not None:
                parts.append(f"{s['SetScore']}-{t2[n]['SetScore']}")
        score = " ".join(parts)
        status = data.get("Status")
        if status and status != "Finished":
            return f"{score}\n[COLOR={TEAL}]LIVE[/COLOR]".strip()
        return f"{score}\n[COLOR={MUTED}]{status}[/COLOR]".strip() if status else score

    # --- poll ---

    def _poll(self):
        while not self._stop.wait(POLL_SECONDS):
            if (self._cache.get("stats") or {}).get("Status") == "Finished":
                return
            self._cache.pop("stats", None)
            self._stats()
            if self._section == SEC_LIVE and self._sub == SUB_STATS and self._revealed:
                self._render_stats()

    # --- text panes ---

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

    def _clear_draw(self):
        for ctrl in self._draw_ctrls:
            self.removeControl(ctrl)
        self._draw_ctrls = []

    def _render_draw(self):
        # The selected round's fixtures as "flag Last v flag Last  score" rows, with the winner in bold.
        self._clear_draw()
        rounds = getattr(self, "_draw_rounds", [])
        if not rounds:
            return
        rnd = rounds[min(self._round_idx, len(rounds) - 1)]
        head = f"[B][COLOR={TEAL}]{rnd.get('RoundName')}[/COLOR][/B]"
        ctrls = [xbmcgui.ControlLabel(CX, 152, CW, 24, head, font="font11")]
        y = 184
        for fx in rnd.get("Fixtures") or []:
            res = fx.get("Result") or {}
            tn, tc = _slot(res.get("TeamTop"), fx.get("DrawLineTop"), fx.get("TopPlaceholderText"))
            if res.get("ResultReason") == "BYE" and not res.get("TeamBottom"):
                bn, bc = "(bye)", None
            else:
                bn, bc = _slot(res.get("TeamBottom"), fx.get("DrawLineBottom"), fx.get("BottomPlaceholderText"))
            if res.get("Winner") == 1:
                tn = f"[B]{tn}[/B]"
            elif res.get("Winner") == 2:
                bn = f"[B]{bn}[/B]"
            lflag, rflag = _flag(tc), _flag(bc)
            if lflag:
                ctrls.append(xbmcgui.ControlImage(CX, y + 3, 22, 15, lflag))
            ctrls.append(xbmcgui.ControlLabel(CX + 26, y, 118, 22, tn, font="font10", textColor=WHITE))
            ctrls.append(
                xbmcgui.ControlLabel(CX + 146, y, 14, 22, "v", font="font10", textColor=MUTED, alignment=AL_CENTRE)
            )
            if rflag:
                ctrls.append(xbmcgui.ControlImage(CX + 162, y + 3, 22, 15, rflag))
            ctrls.append(xbmcgui.ControlLabel(CX + 188, y, 116, 22, bn, font="font10", textColor=WHITE))
            ctrls.append(
                xbmcgui.ControlLabel(
                    CX + 304,
                    y,
                    68,
                    22,
                    res.get("ResultString") or "",
                    font="font10",
                    textColor=MUTED,
                    alignment=AL_RIGHT,
                )
            )
            y += 26
        for ctrl in ctrls:
            self.addControl(ctrl)
        self._draw_ctrls = ctrls


def _slot(team, drawline, placeholder):
    # Returns (surname, three-letter nationality) for a draw slot.
    if team and team.get("Player"):
        p = team["Player"]
        return (p.get("LastName") or ""), p.get("Nationality")
    players = (drawline or {}).get("Players") or []
    if players:
        return (players[0].get("LastName") or ""), players[0].get("Nationality")
    return (placeholder or "?"), None


def _short_round(name):
    if name.startswith("Round of "):
        return "R" + name.split()[-1]
    return {"Quarterfinal": "QF", "Semifinal": "SF", "Final": "F"}.get(name, name[:3])

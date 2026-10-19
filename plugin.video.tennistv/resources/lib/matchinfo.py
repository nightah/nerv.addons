import threading

import xbmcgui
from slyguy.constants import ADDON_PATH

from .language import _

# Control ids in MatchInfo.xml
TAB_STATS, TAB_DRAW, TAB_H2H = 10, 11, 12
TITLE_ID, SCORE_ID, BODY_ID = 100, 101, 50
TABS = (TAB_STATS, TAB_DRAW, TAB_H2H)

# How often the stats tab refreshes while a live match is on air.
POLL_SECONDS = 20

# (label, service-stat key) and (label, return-stat key); a value is shown as "N" or "N%" from the field itself.
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


def _value(stat):
    # A stat field is {"Number": n}, {"Percent": p, ...} or a save/convert ratio with Dividend/Divisor.
    if not isinstance(stat, dict):
        return "-"
    if "Percent" in stat and stat.get("Divisor"):
        return f"{stat['Dividend']}/{stat['Divisor']} ({round(stat['Percent'])}%)"
    if "Percent" in stat:
        return f"{round(stat['Percent'])}%"
    if "Number" in stat:
        return str(stat["Number"])
    return "-"


def _match_totals(team):
    # The per-player Sets list carries SetNumber 0 for the whole match; fall back to the first set if absent.
    sets = team.get("Sets") or []
    whole = next((s for s in sets if s.get("SetNumber") == 0), None)
    return (whole or (sets[0] if sets else {})).get("Stats") or {}


class MatchInfo(xbmcgui.WindowXMLDialog):
    @classmethod
    def show(cls, api, match_ref, title):
        try:
            tid, year, match_id = match_ref.split("_", 2)
        except ValueError:
            return
        dialog = cls("MatchInfo.xml", ADDON_PATH, "Default", "1080i")
        dialog.setup(api, tid, year, match_id, title)
        dialog.doModal()
        del dialog

    def setup(self, api, tid, year, match_id, title):
        self._api = api
        self._tid, self._year, self._match_id = tid, year, match_id
        self._title = title or ""
        self._tab = TAB_STATS
        self._stop = threading.Event()
        self._cache = {}

    def onInit(self):
        self.getControl(TITLE_ID).setLabel(self._title)
        self._render()
        threading.Thread(target=self._poll, daemon=True).start()

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_STOP):
            self.close()

    def onClick(self, control_id):
        if control_id in TABS:
            self._tab = control_id
            self._render()

    def close(self):
        self._stop.set()
        super().close()

    def _poll(self):
        # Refresh the stats tab for a live match until it finishes or the dialog closes (a replay never polls).
        while not self._stop.wait(POLL_SECONDS):
            if (self._cache.get("stats") or {}).get("Status") == "Finished":
                return
            self._cache.pop("stats", None)
            self._stats()
            if self._tab == TAB_STATS:
                self._render()

    def _render(self):
        if self._tab == TAB_DRAW:
            body, score = self._draw_text(), ""
        elif self._tab == TAB_H2H:
            body, score = self._h2h_text(), ""
        else:
            body, score = self._stats_text()
        try:
            self.getControl(SCORE_ID).setLabel(score)
            self.getControl(BODY_ID).setText(body)
        except Exception:
            pass

    def _stats(self):
        if "stats" not in self._cache:
            self._cache["stats"] = self._api.match_stats(self._tid, self._year, self._match_id) or {}
        return self._cache["stats"]

    def _player_ids(self):
        data = self._stats()
        return (data.get("PlayerTeam1") or {}).get("PlayerId"), (data.get("PlayerTeam2") or {}).get("PlayerId")

    def _stats_text(self):
        data = self._stats()
        t1, t2 = data.get("PlayerTeam1") or {}, data.get("PlayerTeam2") or {}
        s1, s2 = _match_totals(t1), _match_totals(t2)

        lines = []
        for heading, rows, group in (("SERVICE", SERVICE_ROWS, "ServiceStats"), ("RETURN", RETURN_ROWS, "ReturnStats")):
            lines.append(f"[B]{heading}[/B]")
            g1, g2 = s1.get(group) or {}, s2.get(group) or {}
            for label, key in rows:
                lines.append(f"{_value(g1.get(key)):>16}   [B]{label}[/B]   {_value(g2.get(key))}")
            lines.append("")

        score = self._score_text(data)
        if data.get("Status"):
            score = f"{score}   ({data['Status']})" if score else data["Status"]
        return "\n".join(lines).strip(), score

    def _score_text(self, data):
        # Build "6-3 4-6 ..." from each team's per-set SetScore, when present.
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
        return " ".join(parts)

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
        lines = [f"[B]{header}[/B]", ""]
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
            lines.append(f"[B]{rnd.get('RoundName')}[/B]")
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
    # A draw slot shows the played player, else the seeded entrant, else a "Winner of ..." placeholder.
    if team and team.get("Player"):
        return team["Player"].get("LastName") or ""
    players = (drawline or {}).get("Players") or []
    if players:
        return players[0].get("LastName") or ""
    return placeholder or "?"

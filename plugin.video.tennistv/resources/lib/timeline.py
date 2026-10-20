import re
from datetime import datetime, timezone
from urllib.parse import urljoin

# The web player's side panel is an Ease Live overlay fed by a per-match timeline of events stamped in wall-clock
# milliseconds. Each HLS segment carries EXT-X-PROGRAM-DATE-TIME, so a video position maps onto that clock. The
# overlay shows the latest event of each kind at or before (video clock + offset); the video runs about 7s behind
# the data, which the Ease Live project config sets as a -7000ms timecode offset.
TIMECODE_OFFSET_MS = -7000

_PDT = "#EXT-X-PROGRAM-DATE-TIME:"


def variant_url(master, url):
    # The first variant of a master playlist (all variants share the same timing), or None for a media playlist.
    if "#EXT-X-STREAM-INF" not in master:
        return None
    lines = master.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            for nxt in lines[i + 1 :]:
                if nxt and not nxt.startswith("#"):
                    return urljoin(url, nxt.strip())
    return None


def _parse_pdt(value):
    value = value.strip().replace("Z", "+00:00")
    # Python before 3.11 only parses exactly 3 or 6 fraction digits and needs a colon in the offset.
    value = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], value)
    value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:  # a time without a zone is UTC, not the device's local time
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def parse_time(value):
    # An ISO 8601 time in ms since the epoch (0 when missing or unreadable).
    try:
        return _parse_pdt(value)
    except ValueError:
        return 0


def segments(playlist):
    # [(start position in seconds, program date-time in ms)] for every segment that carries a date-time, plus whether
    # the playlist is complete (VOD) or a live window.
    pos, pdt, out = 0.0, None, []
    for line in playlist.splitlines():
        if line.startswith(_PDT):
            pdt = _parse_pdt(line[len(_PDT) :])
        elif line.startswith("#EXTINF:"):
            if pdt is not None:
                out.append((pos, pdt))
            pos += float(line[len("#EXTINF:") :].split(",")[0])
            pdt = None
    return out, pos, "#EXT-X-ENDLIST" in playlist


def wall_clock(segs, position):
    # The program date-time at a position in the video, from the last segment starting at or before it.
    best = None
    for start, pdt in segs:
        if start > position:
            break
        best = (start, pdt)
    if best is None:
        return None
    return best[1] + int((position - best[0]) * 1000)


def position_at(segs, clock):
    # The video position showing a program date-time (the start of the video for anything before it).
    best = None
    for start, pdt in segs:
        if pdt > clock:
            break
        best = (start, pdt)
    if best is None:
        return 0.0
    return best[0] + (clock - best[1]) / 1000


def state_at(events, when):
    # The latest metadata of each event kind ("GameScore#show", "MatchStats#show", ...) at or before when.
    state = {}
    for event in events:
        if event.get("timestamp", 0) > when:
            break
        state[event.get("event")] = event.get("metadata")  # the event's own object: stable while it is the latest
    return state


def live_card(state, team_a_is_p1=True):
    # What the live score card shows, from a timeline state: current set, point score, the current game's points
    # (1 or 2 for who won each), games in the current set, completed sets, who serves and whether it has finished.
    score = (state.get("GameScore#show") or {}).get("gameScore") or {}
    board = score.get("scoreBoard") or []
    if not board:
        return None

    def pair(a, b):
        return (a, b) if team_a_is_p1 else (b, a)

    sets = [
        pair((s.get("teamA") or {}).get("setScore") or 0, (s.get("teamB") or {}).get("setScore") or 0) for s in board
    ]
    # The point list still holds the last game until the next one's first point, so only this game's points count.
    game = sum(sets[-1]) + 1
    points = []
    for p in (state.get("GameEvents#show") or {}).get("gameEvents") or []:
        details = p.get("details") or {}
        winner = details.get("winner")
        if details.get("gameNumber") not in (None, game):
            continue
        if winner in ("teamA", "teamB"):
            points.append(1 if (winner == "teamA") == team_a_is_p1 else 2)
    serve = state.get("CurrentServe#show") or {}
    server = None
    if serve.get("teamAServing") or serve.get("teamBServing"):
        server = 1 if bool(serve.get("teamAServing")) == team_a_is_p1 else 2
    status = state.get("MatchStatus#show") or {}
    return {
        "set": len(board),
        "points": pair(
            str(score.get("gamePointsTeamA") or "0").upper(), str(score.get("gamePointsTeamB") or "0").upper()
        ),
        "rally": points,
        "games": sets[-1],
        "done": sets[:-1],
        "server": server,
        "game": game,  # the number of the game in progress in the current set
        "finished": bool(status.get("isFinished")),
    }


def momentum_games(events, when, current=None):
    # Momentum per finished game, newest first, as (set, game, p1 %, p2 %): the last per-point value of each game.
    # The feed publishes its own per-game chart only every few games, so it is rebuilt from the per-point values,
    # which arrive after every point. The game in progress (current = (set, game)) is left out.
    last = {}
    for event in events:
        if event.get("timestamp", 0) > when:
            break
        if event.get("event") == "MomentumByPoint#show":
            m = event.get("metadata") or {}
            last[(m.get("set"), m.get("game"))] = (m.get("p1_momentum"), m.get("p2_momentum"))
    games = [(s, g, *v) for (s, g), v in last.items() if (s, g) != current and s and g]
    return sorted(games, key=lambda x: (x[0], x[1]), reverse=True)


def insights(state, games, team_a_is_p1=True):
    # The Insights view from a timeline state: momentum now and per finished game (games, from momentum_games, newest
    # first), conversion and steal as (won, played, %), shot quality out of 10 and the balance of power. The feed's
    # p1 is team A.
    def pair(a, b):
        return (a, b) if team_a_is_p1 else (b, a)

    now = state.get("MomentumByPoint#show") or (state.get("Momentum#show") or {}).get("currentGame") or {}
    games = [(s, g, *pair(a, b)) for s, g, a, b in games]
    live = state.get("LiveInsights#show") or {}

    def side(block, key):
        return ((live.get(block) or {}).get("match") or {}).get(key) or {}

    def ratio(block):
        return pair(
            *[
                (side(block, p).get("wins"), side(block, p).get("total"), side(block, p).get("score"))
                for p in ("p1", "p2")
            ]
        )

    shots = [
        (label, *pair(side("shot_quality", "p1").get(key), side("shot_quality", "p2").get(key)))
        for label, key in (("Serve", "serve"), ("Return", "return"), ("Forehand", "forehand"), ("Backhand", "backhand"))
    ]
    power = (live.get("balance_of_power") or {}).get("match") or {}
    p1, p2 = pair(power.get("p1"), power.get("p2"))
    return {
        "momentum": pair(now.get("p1_momentum"), now.get("p2_momentum")) if now else (None, None),
        "games": games,
        "conversion": ratio("conversion"),
        "steal": ratio("steal"),
        "shots": shots,
        "power": (p1, power.get("neutral"), p2),
    }


def playanywhere_event(events):
    # The PlayAnywhere event id behind the overlay's Key Moments (video clips), from the timeline's match info.
    for event in events:
        if event.get("event") == "MatchInfoPlayAnywhere#show":
            pa = ((event.get("metadata") or {}).get("event") or {}).get("id")
            if pa:
                return pa
    return None

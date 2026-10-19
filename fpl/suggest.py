"""Transfer suggestions: best affordable same-position swap for each squad player."""
from dataclasses import dataclass

from fpl.analyse import analyse_squad
from fpl.squad import MAX_PER_CLUB, Squad, SquadError, swap

MIN_NET_GAIN = 0.5
HIT_COST = 4
GRADE_AREA = {"FWD": "attack", "MID": "midfield", "DEF": "defence", "GK": "defence"}

# Best candidate for one out-player: same position, not in the squad, affordable,
# and from a club that is not already full once the out-player has left.
_BEST_IN = """
SELECT p.player_id, p.web_name, COALESCE(x.xp_next3, 0.0) AS xp3
FROM player AS p
JOIN xp_next_cache AS x ON x.player_id = p.player_id
JOIN v_latest_snapshot AS s ON s.player_id = p.player_id
WHERE p.season = (SELECT value FROM meta WHERE key = 'current_season')
  AND p.position = ?
  AND s.now_cost <= ?
  AND p.player_id NOT IN ({squad_ids})
  AND p.team_id NOT IN ({full_clubs})
ORDER BY xp3 DESC, p.player_id
LIMIT ?
"""


@dataclass
class Suggestion:
    out_id: int
    in_id: int
    out_name: str
    in_name: str
    gain3: float
    hit: int
    net_gain3: float
    grade_change: tuple[str, str, str]   # (area, before, after)


def _marks(items):
    """Placeholders for an IN list; an empty list gets one that matches nothing."""
    return ",".join("?" * len(items)) if items else "-1"


def suggest(conn, squad: Squad, k: int = 2) -> list[Suggestion]:
    """Up to k swaps with net 3-gameweek gain above 0.5 xP, each out-player and
    each in-player at most once.

    Leaves squad_pick holding the original squad.
    """
    ids = [p.player_id for p in squad.picks]
    info = {r["player_id"]: r for r in conn.execute(
        f"SELECT p.player_id, p.web_name, p.position, p.team_id, "
        f"       COALESCE(x.xp_next3, 0.0) AS xp3 "
        f"FROM player AS p LEFT JOIN xp_next_cache AS x ON x.player_id = p.player_id "
        f"WHERE p.season = (SELECT value FROM meta WHERE key = 'current_season') "
        f"  AND p.player_id IN ({_marks(ids)})", ids)}
    clubs = {}
    for pid in ids:
        if pid in info:
            clubs[info[pid]["team_id"]] = clubs.get(info[pid]["team_id"], 0) + 1
    hit = 0 if squad.free_transfers >= 1 else HIT_COST

    found = []
    for pick in squad.picks:
        out = info.get(pick.player_id)
        if out is None:
            continue
        full = [t for t, n in clubs.items()
                if n - (t == out["team_id"]) >= MAX_PER_CLUB]
        sql = _BEST_IN.format(squad_ids=_marks(ids), full_clubs=_marks(full))
        # a few runners-up, so two suggestions never name the same incoming player
        for cand in conn.execute(sql, [out["position"], pick.selling_price + squad.bank,
                                       *ids, *full, k]):
            gain3 = cand["xp3"] - out["xp3"]
            if gain3 - hit > MIN_NET_GAIN:
                found.append((gain3 - hit, pick.player_id, cand["player_id"], cand["web_name"],
                              out["web_name"], out["position"], gain3))
    found.sort(key=lambda f: (-f[0], f[1], f[2]))
    result, used_out, used_in = [], set(), set()
    try:
        before = analyse_squad(conn, squad).grades
        for net, out_id, in_id, in_name, out_name, position, gain3 in found:
            if len(result) >= k:
                break
            if out_id in used_out or in_id in used_in:
                continue
            try:
                swapped = swap(squad, out_id, in_id, conn)
            except SquadError:
                continue   # this swap is not valid; try the next candidate
            after = analyse_squad(conn, swapped).grades
            area = GRADE_AREA[position]
            result.append(Suggestion(out_id, in_id, out_name, in_name, gain3, hit, net,
                                     (area, before[area], after[area])))
            used_out.add(out_id)
            used_in.add(in_id)
    finally:
        analyse_squad(conn, squad)   # always put the user's own squad back
    return result

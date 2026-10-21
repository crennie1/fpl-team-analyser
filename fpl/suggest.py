"""Transfer suggestions: best affordable same-position swap for each squad player.

A bench out-player only counts when the incoming player would start (ruling R21):
his xp_next must beat the weakest same-position starter, he takes that starter's
slot, and the gain is measured against that starter.
"""
from dataclasses import dataclass, replace

from fpl.analyse import analyse_squad
from fpl.squad import MAX_PER_CLUB, Squad, SquadError, swap

MIN_NET_GAIN = 0.5
HIT_COST = 4
GRADE_AREA = {"FWD": "attack", "MID": "midfield", "DEF": "defence", "GK": "defence"}

# Best candidate for one out-player: same position, not in the squad, affordable,
# from a club that is not already full once the out-player has left, and (for a
# bench out-player) better next week than the starter he would replace.
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
  AND COALESCE(x.xp_next, 0.0) > ?
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
    starts_instead: str | None = None    # bench out-player: the starter the new man replaces


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
        f"       COALESCE(x.xp_next, 0.0) AS xp, COALESCE(x.xp_next3, 0.0) AS xp3 "
        f"FROM player AS p LEFT JOIN xp_next_cache AS x ON x.player_id = p.player_id "
        f"WHERE p.season = (SELECT value FROM meta WHERE key = 'current_season') "
        f"  AND p.player_id IN ({_marks(ids)})", ids)}
    clubs = {}
    for pid in ids:
        if pid in info:
            clubs[info[pid]["team_id"]] = clubs.get(info[pid]["team_id"], 0) + 1
    hit = 0 if squad.free_transfers >= 1 else HIT_COST

    def weakest_starter(position):
        starters = [p for p in squad.picks
                    if p.is_starter and p.player_id in info
                    and info[p.player_id]["position"] == position]
        return min(starters, key=lambda p: (info[p.player_id]["xp"],
                                            info[p.player_id]["xp3"], p.slot), default=None)

    found = []
    for pick in squad.picks:
        out = info.get(pick.player_id)
        if out is None:
            continue
        full = [t for t, n in clubs.items()
                if n - (t == out["team_id"]) >= MAX_PER_CLUB]
        # the player whose points the newcomer replaces: the out-player himself, or
        # for a bench out-player the weakest starter in his position
        bench_for = None if pick.is_starter else weakest_starter(out["position"])
        if not pick.is_starter and bench_for is None:
            continue
        rival = info[bench_for.player_id] if bench_for else None
        min_xp = rival["xp"] if rival else float("-inf")
        sql = _BEST_IN.format(squad_ids=_marks(ids), full_clubs=_marks(full))
        # a few runners-up, so two suggestions never name the same incoming player
        for cand in conn.execute(sql, [out["position"], pick.selling_price + squad.bank,
                                       *ids, *full, min_xp, k]):
            gain3 = cand["xp3"] - (rival or out)["xp3"]
            if gain3 - hit > MIN_NET_GAIN:
                found.append((gain3 - hit, pick.player_id, cand["player_id"], cand["web_name"],
                              out["web_name"], out["position"], gain3, bench_for))
    found.sort(key=lambda f: (-f[0], f[1], f[2]))
    result, used_out, used_in = [], set(), set()
    try:
        before = analyse_squad(conn, squad).grades
        for net, out_id, in_id, in_name, out_name, position, gain3, bench_for in found:
            if len(result) >= k:
                break
            if out_id in used_out or in_id in used_in:
                continue
            try:
                swapped = swap(squad, out_id, in_id, conn)
            except SquadError:
                continue   # this swap is not valid; try the next candidate
            if bench_for:
                swapped = promote(swapped, in_id, bench_for.player_id)
            after = analyse_squad(conn, swapped).grades
            area = GRADE_AREA[position]
            result.append(Suggestion(out_id, in_id, out_name, in_name, gain3, hit, net,
                                     (area, before[area], after[area]),
                                     info[bench_for.player_id]["web_name"] if bench_for else None))
            used_out.add(out_id)
            used_in.add(in_id)
    finally:
        analyse_squad(conn, squad)   # always put the user's own squad back
    return result


def promote(squad: Squad, in_id: int, starter_id: int) -> Squad:
    """The new bench player and the starter trade slot, starting place and armband."""
    a = next((p for p in squad.picks if p.player_id == in_id), None)
    b = next((p for p in squad.picks if p.player_id == starter_id), None)
    if a is None or b is None:
        raise SquadError("That player is not in your squad")
    picks = []
    for p in squad.picks:
        if p is a:
            p = replace(a, slot=b.slot, is_starter=b.is_starter, is_captain=b.is_captain)
        elif p is b:
            p = replace(b, slot=a.slot, is_starter=a.is_starter, is_captain=a.is_captain)
        picks.append(p)
    return replace(squad, picks=sorted(picks, key=lambda p: p.slot))

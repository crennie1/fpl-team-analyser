"""Load a manager's squad from the FPL API, plus money, rules and swaps."""
from dataclasses import dataclass, replace

from fpl.api import FplApiError

SHAPE = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
MAX_PER_CLUB = 3
MIN_STARTERS = {"DEF": 3, "MID": 2, "FWD": 1}
MAX_FREE_TRANSFERS = 5
NO_COST_CHIPS = ("wildcard", "freehit")


class SquadError(Exception):
    """Message is shown to the user as written."""


@dataclass
class Pick:
    player_id: int
    slot: int
    is_starter: bool
    is_captain: bool
    selling_price: int


@dataclass
class Squad:
    team_id: int
    gw: int
    picks: list
    bank: int
    free_transfers: int
    note: str | None = None


def selling_price(buy: int, now: int) -> int:
    """FPL keeps half of any price rise, rounded down, in tenths of GBP m."""
    return now if now <= buy else buy + (now - buy) // 2


def estimate_free_transfers(history: dict) -> int:
    """Free transfers available for the next gameweek (ruling R6)."""
    chip_weeks = {c["event"] for c in history.get("chips", []) if c["name"] in NO_COST_CHIPS}
    ft = 1
    for row in sorted(history.get("current", []), key=lambda r: r["event"]):
        if row["event"] == 1:
            continue
        if row["event"] not in chip_weeks:
            ft = max(0, ft - row.get("event_transfers", 0))
        ft = min(MAX_FREE_TRANSFERS, ft + 1)
    return ft


def _current_season(conn):
    row = conn.execute("SELECT value FROM meta WHERE key = 'current_season'").fetchone()
    return row[0] if row else None


def _player_info(conn, ids):
    """{player_id: (position, team_id, now_cost or None)} for the current season."""
    season = _current_season(conn)
    info = {}
    for pid in ids:
        row = conn.execute(
            "SELECT p.position, p.team_id, "
            "(SELECT now_cost FROM v_latest_snapshot s WHERE s.player_id = p.player_id) "
            "FROM player p WHERE p.season = ? AND p.player_id = ?", (season, pid)).fetchone()
        if row:
            info[pid] = (row[0], row[1], row[2])
    return info


def _start_prices(client):
    """Season-start price per player from one bootstrap call: now_cost - cost_change_start."""
    return {e["id"]: e["now_cost"] - e["cost_change_start"]
            for e in client.bootstrap().get("elements", [])
            if e.get("now_cost") is not None and e.get("cost_change_start") is not None}


def _price_at(client, conn, player_id, gw, start_prices=None):
    """Price of a player in `gw`: snapshot first, then for gw 1 the bootstrap
    season-start price (`start_prices()`, called lazily), then element-summary history."""
    row = conn.execute(
        "SELECT now_cost FROM player_snapshot WHERE season = ? AND gw = ? AND player_id = ?",
        (_current_season(conn), gw, player_id)).fetchone()
    if row and row[0] is not None:
        return row[0]
    if gw == 1 and start_prices is not None and player_id in start_prices():
        return start_prices()[player_id]
    for h in client.element_summary(player_id).get("history", []):
        if h.get("round") == gw:
            return h["value"]
    return None


def load_squad(client, conn, team_id) -> Squad:
    text = str(team_id).strip()
    if not text.isdigit():
        raise SquadError("Team ID must be a number")
    tid = int(text)
    try:
        entry = client.entry(tid)
    except FplApiError as exc:
        if exc.status == 404:
            raise SquadError(f"No FPL team found with ID {text}") from exc
        raise
    event = entry.get("current_event")
    if not event:
        raise SquadError("Season hasn't started — no squad to analyse yet")

    picks_data = client.entry_picks(tid, event)
    gw, note = event, None
    if picks_data.get("active_chip") == "freehit" and event > 1:
        gw = event - 1
        picks_data = client.entry_picks(tid, gw)
        note = f"Free Hit last week — showing your GW{gw} squad"

    history = client.entry_history(tid)
    transfers = client.entry_transfers(tid)
    first_gw = min((r["event"] for r in history.get("current", [])), default=gw)

    bought = {}  # latest buy cost per player up to the shown gameweek
    for t in sorted(transfers, key=lambda t: (t["event"], t.get("time", ""))):
        if t["event"] <= gw:
            bought[t["element_in"]] = t["element_in_cost"]

    raw = sorted(picks_data["picks"], key=lambda p: p["position"])
    info = _player_info(conn, [p["element"] for p in raw])
    cache = {}

    def start_prices():   # one bootstrap call, only if a GW1 price is needed
        if "prices" not in cache:
            cache["prices"] = _start_prices(client)
        return cache["prices"]

    picks = []
    for p in raw:
        pid = p["element"]
        now = info[pid][2] if pid in info else None
        buy = bought.get(pid)
        if buy is None:
            buy = _price_at(client, conn, pid, first_gw, start_prices)
        if buy is None:
            buy = now
        if now is None:
            now = buy
        if buy is None:
            raise SquadError(f"No price known for player {pid}")
        picks.append(Pick(pid, p["position"], p["position"] <= 11,
                          bool(p.get("is_captain")), selling_price(buy, now)))

    return Squad(tid, gw, picks, picks_data["entry_history"]["bank"],
                 estimate_free_transfers(history), note)


def validate(squad: Squad, conn) -> list[str]:
    problems = []
    info = _player_info(conn, [p.player_id for p in squad.picks])
    unknown = [p.player_id for p in squad.picks if p.player_id not in info]
    if unknown:
        problems.append(f"Unknown players: {', '.join(map(str, unknown))}")
    pos = {pid: v[0] for pid, v in info.items()}

    counts = {k: 0 for k in SHAPE}
    clubs = {}
    for p in squad.picks:
        if p.player_id in info:
            counts[pos[p.player_id]] += 1
            clubs[info[p.player_id][1]] = clubs.get(info[p.player_id][1], 0) + 1
    for k, want in SHAPE.items():
        if counts[k] != want:
            problems.append(f"Squad needs {want} {k}, has {counts[k]}")
    for club, n in sorted(clubs.items()):
        if n > MAX_PER_CLUB:
            row = conn.execute("SELECT short_name FROM team WHERE season = ? AND team_id = ?",
                               (_current_season(conn), club)).fetchone()
            name = row[0] if row else f"team {club}"
            problems.append(f"Too many players from one club ({name} has {n}, max {MAX_PER_CLUB})")
    if squad.bank < 0:
        problems.append(f"Over budget by £{-squad.bank / 10:.1f}m")

    starters = {k: 0 for k in SHAPE}
    for p in squad.picks:
        if p.is_starter and p.player_id in info:
            starters[pos[p.player_id]] += 1
    if sum(starters.values()) != 11 or starters["GK"] != 1:
        problems.append("Starting XI needs 11 players with exactly 1 GK")
    for k, mn in MIN_STARTERS.items():
        if starters[k] < mn:
            problems.append(f"Starting XI needs at least {mn} {k}, has {starters[k]}")
    return problems


def swap(squad: Squad, out_id: int, in_id: int, conn) -> Squad:
    out = next((p for p in squad.picks if p.player_id == out_id), None)
    if out is None:
        raise SquadError("That player is not in your squad")
    if any(p.player_id == in_id for p in squad.picks):
        raise SquadError("That player is already in your squad")
    info = _player_info(conn, [out_id, in_id])
    if in_id not in info or out_id not in info:
        raise SquadError("Unknown player")
    if info[out_id][0] != info[in_id][0]:
        raise SquadError(f"Can only swap players in the same position ({info[out_id][0]} vs {info[in_id][0]})")
    cost = info[in_id][2]
    if cost is None:
        raise SquadError("No current price for that player")
    new_picks = [replace(out, player_id=in_id, selling_price=cost) if p is out else p
                 for p in squad.picks]
    new = replace(squad, picks=new_picks, bank=squad.bank + out.selling_price - cost)
    problems = validate(new, conn)
    if problems:
        raise SquadError("; ".join(problems))
    return new

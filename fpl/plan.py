"""A transfer plan: the fetched squad plus an ordered list of moves, replayed on every rerun."""
from dataclasses import dataclass

from fpl.squad import Squad, SquadError, swap
from fpl.suggest import HIT_COST, promote


@dataclass(frozen=True)
class Move:
    out_id: int
    in_id: int
    promote_over: int | None = None   # starter who drops to the bench (bench picks only)


def build(base: Squad, moves: list[Move], conn) -> Squad:
    """Replay the moves from base in planning mode (budget never blocks)."""
    squad = base
    for m in moves:
        squad = swap(squad, m.out_id, m.in_id, conn, allow_over_budget=True)
        if m.promote_over is not None:
            squad = promote(squad, m.in_id, m.promote_over)
    return squad


def changes(base: Squad, current: Squad) -> list[tuple[int, int]]:
    """(original_out_id, current_in_id) per slot whose player differs from base, in squad order."""
    base_at = {p.slot: p.player_id for p in base.picks}
    now_slot = {p.player_id: p.slot for p in current.picks}
    kept = {p.player_id for p in base.picks}
    pairs = {}
    for p in current.picks:
        if p.player_id in kept:
            continue
        # A promotion moves a kept player into the newcomer's old slot; follow it back to the
        # base player who actually left.
        out = base_at.get(p.slot)
        while out in now_slot:
            out = base_at.get(now_slot[out])
        pairs[out] = p.player_id
    return [(b.player_id, pairs[b.player_id]) for b in base.picks if b.player_id in pairs]


def hit(n_changes: int, free_transfers: int) -> int:
    return HIT_COST * max(0, n_changes - free_transfers)


def extra_hit(base: Squad, current: Squad, out_id: int, in_id: int,
              free_transfers: int) -> int:
    """Points this swap would add to the hit (never negative)."""
    # Only taking out a player still from base opens a new change; replacing an IN player
    # keeps the slot's count the same, or lowers it when in_id is the slot's original.
    opens_slot = any(p.player_id == out_id for p in base.picks)
    n = len(changes(base, current))
    return hit(n + 1, free_transfers) - hit(n, free_transfers) if opens_slot else 0


def undo_last(moves: list[Move]) -> list[Move]:
    return moves[:-1]


def undo_original(base: Squad, moves: list[Move], original_id: int, conn) -> list[Move]:
    """Drop the whole chain of moves that took original_id (and its successors) out."""
    chain = {original_id}
    kept = []
    for m in moves:
        if m.out_id in chain:
            chain.add(m.in_id)
        else:
            kept.append(m)
    build(base, kept, conn)   # raises SquadError if the rest no longer applies
    return kept


def add(base: Squad, moves: list[Move], out_id: int, in_id: int, conn,
        promote_over: int | None = None) -> list[Move]:
    new = [*moves, Move(out_id, in_id, promote_over)]
    build(base, new, conn)
    return new


def summary(base: Squad, current: Squad, base_analysis, plan_analysis, names: dict,
            prices: dict, free_transfers: int) -> dict | None:
    """The plan in numbers (money in GBP m), or None when nothing has changed."""
    pairs = changes(base, current)
    if not pairs:
        return None
    n = len(pairs)
    h = hit(n, free_transfers)
    rows = [{"out_id": o, "out_name": names.get(o), "out_price": round(prices[o], 1),
             "in_id": i, "in_name": names.get(i), "in_price": round(prices[i], 1),
             "diff": round(prices[i] - prices[o], 1)} for o, i in pairs]
    grades = [[area, before, plan_analysis.grades.get(area)]
              for area, before in base_analysis.grades.items()
              if area != "projected" and plan_analysis.grades.get(area) != before]
    bank, real_bank = round(current.bank / 10, 1), round(base.bank / 10, 1)
    return {"changes": rows, "n_changes": n, "ft_used": min(n, free_transfers), "hit": h,
            "bank": bank,
            "compare": {"pts3": [base_analysis.projected3, plan_analysis.projected3],
                        "pts3_after_hits": [base_analysis.projected3, plan_analysis.projected3 - h],
                        "grades": grades, "bank": [real_bank, bank]}}

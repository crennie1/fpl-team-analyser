"""Draw a random sample of public FPL teams as the 'average manager' reference."""
import argparse
import random

from fpl import db
from fpl.api import FplApiError, FplClient


MAX_API_ERRORS = 20


def _fetch_picks(client, entry_id, gw):
    """Return the pick list for one entry, or None if the team or its picks are missing."""
    try:
        client.entry(entry_id)
        picks = client.entry_picks(entry_id, gw).get("picks")
    except FplApiError as exc:
        if exc.status == 404:
            return None
        raise
    return picks or None


def sample(conn, client, season, gw, n=500, seed=None):
    """Replace the season's reference sample with up to n random squads; return the count."""
    total = client.bootstrap()["total_players"]
    rng = random.Random(seed)
    squads = []
    seen = set()
    attempts = 0
    errors = 0
    while len(squads) < n and attempts < 3 * n and len(seen) < total:
        entry_id = rng.randint(1, total)
        if entry_id in seen:
            continue
        seen.add(entry_id)
        attempts += 1
        try:
            picks = _fetch_picks(client, entry_id, gw)
        except FplApiError:
            # Skip a flaky entry, but fail loudly if the API is really down.
            errors += 1
            if errors > MAX_API_ERRORS:
                raise
            continue
        if picks:
            squads.append((entry_id, picks))

    # Only ref: rows are touched, so the user's own squad survives.
    conn.execute(
        "DELETE FROM squad_pick WHERE squad_id IN "
        "(SELECT squad_id FROM reference_squad WHERE season = ?)", (season,))
    conn.execute("DELETE FROM reference_squad WHERE season = ?", (season,))
    for entry_id, picks in squads:
        sid = f"ref:{entry_id}"
        conn.execute("INSERT INTO reference_squad VALUES (?,?,?,?)", (season, gw, sid, entry_id))
        conn.executemany(
            "INSERT INTO squad_pick VALUES (?,?,?,?,?)",
            [(sid, p["element"], p["position"], int(p["position"] <= 11),
              int(bool(p["is_captain"]))) for p in picks])
    conn.commit()
    return len(squads)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/fpl.db")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int)
    args = ap.parse_args(argv)
    conn = db.connect(args.db)
    db.apply_sql(conn, "schema.sql")
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        season, gw = meta["current_season"], int(meta["next_gw"]) - 1
        count = sample(conn, FplClient(), season, gw, args.n, args.seed)
        db.apply_views(conn)
        conn.commit()
    finally:
        conn.close()
    print(f"Reference sample: {count} squads for {season} GW{gw}")


if __name__ == "__main__":
    main()

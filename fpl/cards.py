"""Player-card and opponent-weakness data for the UI (pure data, no HTML).

Every number comes from the database; a missing value stays None.
"""
from fpl.analyse import Analysis

POS_WORD = {"GK": "goalkeepers", "DEF": "defenders", "MID": "midfielders", "FWD": "forwards"}
WEAK_KEY = {"GK": "gk", "DEF": "def", "MID": "mid", "FWD": "fwd"}
_SEASON = "(SELECT value FROM meta WHERE key = 'current_season')"


def ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th ... 11th, 12th, 13th ... 21st."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _meta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _initials(first, web_name):
    """First letter of first_name + first letter of web_name without any "X." prefix (V6)."""
    words = web_name.split()
    if first and first.strip() and len(words) >= 2 and web_name.startswith(first.strip()):
        return (words[0][0] + words[1][0]).upper()          # V6b: "João Pedro" -> JP
    if first and first.strip():
        surname = web_name.split(".", 1)[1] if "." in web_name[:3] else web_name
        return (first.strip()[0] + (surname.strip() or web_name)[0]).upper()
    return web_name[:2].upper()


def _ranks(conn, season, next_gw):
    """{(position, team_id): (pts_pm, rank)}; rank 1 = concedes the most points per match."""
    by_pos = {}
    for r in conn.execute(
            "SELECT team_id, position, pts_pm FROM v_team_conceded "
            "WHERE season = ? AND as_of_gw = ?", (season, next_gw)):
        by_pos.setdefault(r["position"], []).append((r["team_id"], r["pts_pm"]))
    out = {}
    for pos, rows in by_pos.items():
        for team_id, pts in rows:
            rank = None if pts is None else 1 + sum(
                1 for _, o in rows if o is not None and o > pts)
            out[(pos, team_id)] = (pts, rank)
    return out


def weakness_table(conn) -> list[dict]:
    """One row per team: {team, short, gk, def, mid, fwd, rank: {gk, def, mid, fwd}}.

    gk/def/mid/fwd are points conceded per match to that position over the last
    6 loaded gameweeks; rank 1 = leakiest of the league.
    """
    season, next_gw = _meta(conn, "current_season"), _meta(conn, "next_gw")
    ranks = _ranks(conn, season, int(next_gw))
    rows = []
    for t in conn.execute("SELECT team_id, name, short_name FROM team WHERE season = ? "
                          "ORDER BY name", (season,)):
        row = {"team": t["name"], "short": t["short_name"], "rank": {}}
        for pos, key in WEAK_KEY.items():
            pts, rank = ranks.get((pos, t["team_id"]), (None, None))
            row[key] = pts
            row["rank"][key] = rank
        rows.append(row)
    return rows


def _set_pieces(sp):
    if sp is None:
        return None
    groups = {}
    for label, order in (("penalties", sp["penalties_order"]), ("corners", sp["corners_order"]),
                         ("direct free kicks", sp["direct_fk_order"])):
        if order:
            groups.setdefault(order, []).append(label)
    if not groups:
        return None
    return "; ".join(f"{ordinal(o)} choice {', '.join(groups[o])}" for o in sorted(groups))


def player_cards(conn, analysis: Analysis, suggestions: list) -> list[dict]:
    season, next_gw = _meta(conn, "current_season"), int(_meta(conn, "next_gw"))
    ranks = _ranks(conn, season, next_gw)
    sells = {s.out_id: s for s in suggestions}
    last = conn.execute("SELECT last_gw FROM v_last_gw WHERE season = ? AND as_of_gw = ?",
                        (season, next_gw)).fetchone()
    last_gw = last["last_gw"] if last else None
    cards = []
    for pv in analysis.players:
        card = _card(conn, pv, season, next_gw, last_gw, ranks, sells.get(pv.player_id))
        if card is not None:   # None: not in the player table yet (Analysis.missing)
            cards.append(card)
    return cards


def _card(conn, pv, season, next_gw, last_gw, ranks, sug):
    pid = pv.player_id
    p = conn.execute(
        "SELECT p.first_name, p.second_name, p.web_name, p.team_id, t.short_name AS club, "
        "       s.now_cost, s.selected_by_percent, x.xp_next3, x.defcon_chance, x.cs_chance "
        "FROM player AS p JOIN team AS t ON t.season = p.season AND t.team_id = p.team_id "
        "LEFT JOIN v_latest_snapshot AS s ON s.player_id = p.player_id "
        "LEFT JOIN xp_next_cache AS x ON x.player_id = p.player_id "
        "WHERE p.season = ? AND p.player_id = ?", (season, pid)).fetchone()
    if p is None:
        return None
    is_gk = pv.position == "GK"
    chance = p["cs_chance"] if is_gk else p["defcon_chance"]

    fixtures = [{"opp": f["opp"], "home": bool(f["home"]), "fdr": f["fdr"]} for f in conn.execute(
        "SELECT COALESCE(o.short_name, '?') AS opp, f.team_h = :t AS home, "
        "       CASE WHEN f.team_h = :t THEN f.team_h_difficulty ELSE f.team_a_difficulty END AS fdr "
        "FROM fixture AS f "
        "LEFT JOIN team AS o ON o.season = f.season "
        "     AND o.team_id = CASE WHEN f.team_h = :t THEN f.team_a ELSE f.team_h END "
        "WHERE f.season = :s AND f.gw >= :g AND (f.team_h = :t OR f.team_a = :t) "
        "ORDER BY f.gw, f.fixture_id LIMIT 3", {"t": p["team_id"], "s": season, "g": next_gw})]

    form = xg = xa = defcon = None
    if last_gw is not None:
        w = (season, pid, last_gw - 5, last_gw)
        g = conn.execute("SELECT COUNT(*) AS n, SUM(total_points) AS pts FROM player_gw "
                         "WHERE season=? AND player_id=? AND gw BETWEEN ? AND ? AND minutes > 0", w).fetchone()
        form = g["pts"] * 1.0 / g["n"] if g["n"] else None
        st = conn.execute("SELECT COUNT(*) AS n, SUM(xg) AS xg, SUM(xa) AS xa FROM player_gw_stats "
                          "WHERE season=? AND player_id=? AND gw BETWEEN ? AND ?", w).fetchone()
        if st["n"]:
            xg, xa = st["xg"], st["xa"]
    if not is_gk:
        th = conn.execute("SELECT defcon_rate FROM v_player_threat WHERE season=? AND player_id=? "
                          "AND as_of_gw=?", (season, pid, next_gw)).fetchone()
        if th and th["defcon_rate"] is not None:
            defcon = int(round(th["defcon_rate"] * 100))

    weakness = None
    if fixtures:
        nxt = conn.execute(
            "SELECT CASE WHEN team_h = ? THEN team_a ELSE team_h END AS opp_id FROM fixture "
            "WHERE season=? AND gw >= ? AND (team_h = ? OR team_a = ?) ORDER BY gw, fixture_id LIMIT 1",
            (p["team_id"], season, next_gw, p["team_id"], p["team_id"])).fetchone()
        _, rank = ranks.get((pv.position, nxt["opp_id"]), (None, None))
        if rank is not None:
            weakness = (f"{fixtures[0]['opp']} concede the {ordinal(rank)}-most points to "
                        f"{POS_WORD[pv.position]} over the last 6 GWs")

    sp = conn.execute("SELECT penalties_order, corners_order, direct_fk_order FROM set_piece "
                      "WHERE season=? AND player_id=?", (season, pid)).fetchone()

    sell = None
    if sug is not None:
        n = conn.execute(
            "SELECT p.first_name, p.second_name, p.web_name, t.short_name AS club FROM player AS p "
            "JOIN team AS t ON t.season = p.season AND t.team_id = p.team_id "
            "WHERE p.season=? AND p.player_id=?", (season, sug.in_id)).fetchone()
        full = (f"{n['first_name']} {n['second_name']}" if n["first_name"] and n["second_name"]
                else n["web_name"])
        sell = {"to_name": sug.in_name, "to_full_name": full, "to_club": n["club"],
                "gain3": sug.gain3, "hit": sug.hit, "starts_instead_of": sug.starts_instead}

    return {
        "id": pid, "initials": _initials(p["first_name"], p["web_name"]),
        "name": pv.name,
        "full_name": (f"{p['first_name']} {p['second_name']}"
                      if p["first_name"] and p["second_name"] else p["web_name"]),
        "pos": pv.position, "club": p["club"],
        "price": p["now_cost"] / 10 if p["now_cost"] is not None else None,
        "owned": p["selected_by_percent"],
        "xp": pv.xp_next, "xp3": p["xp_next3"], "colour": pv.colour, "flag": pv.flag,
        "starter": pv.is_starter, "captain": pv.is_captain,
        "bar_label": "Clean sheet" if is_gk else "DefCon",
        "bar_pct": None if chance is None else int(round(chance * 100)),
        "fixtures": fixtures,
        "last6": {"form": form, "xg": xg, "xa": xa, "defcon_pct": defcon},
        "weakness": weakness,
        "set_pieces": _set_pieces(sp),
        "sell": sell,
    }

# FPL Team Analyser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a free Streamlit web app. It loads any public FPL team by ID and shows a pitch view with expected points per player, A–E team grades, a projected score against the average manager, and 1–2 affordable transfer suggestions. The forecast behind it is backtested in public.

**Architecture:** Python collects data from the public FPL API and a past-season archive into one SQLite file, `data/fpl.db`. A scheduled GitHub Action refreshes that file and commits it, so storage and hosting cost £0. The forecast, squad metrics and grades are SQL views in `fpl/sql/`, so the owner can read and reproduce them. The Streamlit app copies the database into memory, loads the user's squad from the live API, inserts it into `squad_pick`, and reads results from the views.

**Tech Stack:** Python 3.11, SQLite (stdlib `sqlite3`), `requests`, `streamlit`, `pytest`. No other runtime dependencies.

**Spec:** `docs/2026-10-19-fpl-team-analyser-design.md`, with the approved layout in `docs/mockups/team-analysis-v2.html`

## Global Constraints

- Data comes only from the official FPL API (`https://fantasy.premierleague.com/api/`) and a public past-season archive (vaastav `Fantasy-Premier-League` on GitHub). Never scrape paid FPL tools.
- Running cost: £0. Hosting is Streamlit Community Cloud; scheduled jobs are GitHub Actions; storage is the SQLite file in the repo.
- Be polite to the FPL API: send a `User-Agent`, wait at least 0.5 s between live requests, retry 429/5xx up to 3 times with backoff, and cache responses (in the app with `st.cache_data`, ttl 600 s).
- Never show fake or stale data silently. If an API call fails, the app shows a plain error. If `meta.last_collected` is more than 36 h old, the app shows a warning.
- Wherever practical the forecast, metrics and grades live in SQL views (`fpl/sql/*.sql`); Python only orchestrates.
- Nothing betting-related. No accounts, logins, payments, or AI-written verdict.
- Money is stored as integer tenths of £m, as FPL does (`now_cost` 105 = £10.5m).
- The site must be usable on a phone. Use Streamlit's default responsive columns.
- Tests never touch the network. They use recorded JSON in `tests/fixtures/`.

## Review Focus

1. **Bad team ID** (non-numeric, does not exist, API 404). Expect a plain "No FPL team found with ID …" message, not a stack trace. Pinned in Task 7: `test_load_squad_unknown_id`.
2. **Free Hit last gameweek.** The picks endpoint returns the temporary Free Hit squad. Expect the app to analyse the real squad from the gameweek before. Pinned in Task 7: `test_free_hit_uses_previous_picks`.
3. **Blank and double gameweeks.** A team with 0 fixtures in a gameweek gets 0 expected points; a team with 2 fixtures gets the sum of both. Pinned in Task 4: `test_xp_blank_and_double`.
4. **Players with no recent minutes, or newly added mid-season.** Expect a position default rate and a red flag, not a division-by-zero or NULL. Pinned in Task 4: `test_xp_new_player_uses_position_default`.
5. **API down, or an empty response at season start (gameweek 1 not started).** Expect "FPL data is unavailable right now" or "Season hasn't started — no squad to analyse yet", not a crash. Pinned in Task 10: `test_app_api_down_message` and in Task 7: `test_load_squad_preseason`.

---

## File Structure

```
fpl-team-analyser/
  requirements.txt
  .gitignore
  app.py                       # Streamlit UI only
  fpl/
    __init__.py
    api.py                     # HTTP client: cache, retry, FplApiError
    db.py                      # connect(), apply_sql(), in-memory copy
    sql/schema.sql             # tables
    sql/forecast.sql           # form, fdr multiplier, xP views
    sql/squad.sql              # squad metrics + grade views
    collect.py                 # current-season collector (CLI)
    history.py                 # past-season loader (CLI)
    backtest.py                # backtest + report (CLI)
    reference.py               # reference team sample (CLI)
    squad.py                   # load squad, selling prices, free transfers, rules, swap
    analyse.py                 # analyse_squad(): grades/projection/colours
    suggest.py                 # transfer suggestions
  analysis/
    README.md                  # how to open the DB, owner's workspace
    data_dictionary.md
    starter_queries.sql
  reports/backtest.md          # generated
  data/fpl.db                  # generated, committed by CI
  .github/workflows/collect.yml
  tests/
    fixtures/*.json
    conftest.py                # db_with_sample fixture
    test_*.py
```

---

### Task 1: Project skeleton and API client

**Files:**
- Create: `requirements.txt`, `.gitignore`, `fpl/__init__.py`, `fpl/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces:
  - `class FplApiError(Exception)` with attribute `status: int | None`
  - `class FplClient(session: requests.Session | None = None, min_interval: float = 0.5)`
  - `FplClient.get(path: str) -> dict | list`, where `path` is relative to `https://fantasy.premierleague.com/api/` (for example `"bootstrap-static/"`)
  - Convenience methods: `bootstrap()`, `fixtures()`, `event_live(gw: int)`, `entry(team_id: int)`, `entry_history(team_id: int)`, `entry_picks(team_id: int, gw: int)`, `entry_transfers(team_id: int)`, `element_summary(player_id: int)`

- [ ] **Step 1:** Run `git init` in `fpl-team-analyser/`. Write `requirements.txt` with `requests`, `streamlit` and `pytest`, each with an exact pinned version. Write `.gitignore` with `__pycache__/`, `.venv/`, `.superpowers/` and `*.pyc`.
- [ ] **Step 2: Write failing tests** using a fake session object:
```python
def test_get_returns_json(): ...        # fake 200 {"a":1} -> {"a":1}
def test_get_retries_then_succeeds():   # 503, 503, 200 -> returns body; 3 calls
def test_get_404_raises():              # 404 -> FplApiError with .status == 404, no retry
def test_get_gives_up_after_3_retries(): # 503 x4 -> FplApiError(.status==503); 4 calls total
def test_user_agent_sent():             # header "User-Agent" contains "fpl-team-analyser"
```
- [ ] **Step 3:** Run `pytest tests/test_api.py -v`. Expected: FAIL (module missing).
- [ ] **Step 4:** Implement `fpl/api.py`. Sleep between calls to respect `min_interval`, and inject the sleep function so tests run instantly. Backoff is 1 s, 2 s, then 4 s. A network exception raises `FplApiError(status=None)`.
- [ ] **Step 5:** Run `pytest tests/test_api.py -v`. Expected: PASS.
- [ ] **Step 6: Commit** with the message `feat: FPL API client with retry and polite rate limit`.

---

### Task 2: Schema and current-season collector

**Files:**
- Create: `fpl/db.py`, `fpl/sql/schema.sql`, `fpl/collect.py`, `tests/conftest.py`, `tests/fixtures/bootstrap.json`, `tests/fixtures/fixtures.json`, `tests/fixtures/event_live_1.json`
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: `FplClient` (Task 1)
- Produces:
  - `db.connect(path: str | Path) -> sqlite3.Connection` (`row_factory = sqlite3.Row`, foreign keys on)
  - `db.apply_sql(conn, *files: str)`, which runs `fpl/sql/<file>` in order
  - `db.memory_copy(path) -> sqlite3.Connection`, which uses `backup()` into `:memory:` and then applies `forecast.sql` and `squad.sql`
  - `collect.run(conn, client: FplClient, season: str) -> int`, which returns the number of player-gameweek rows upserted
  - CLI: `python -m fpl.collect --db data/fpl.db --season 2026-27`
  - Tables, all with `season TEXT` as part of the key:
    - `team(season, team_id, name, short_name)`
    - `player(season, player_id, web_name, team_id, position)`. `position` is one of `'GK','DEF','MID','FWD'`, mapped from `element_type` 1–4.
    - `player_snapshot(season, gw, player_id, collected_at, status, chance_next, ep_next, now_cost, selected_by_percent)`. `gw` is the upcoming gameweek at collection time. Keep only the latest snapshot per `(season, gw, player_id)`; the last collection before the deadline wins.
    - `fixture(season, fixture_id, gw, team_h, team_a, team_h_difficulty, team_a_difficulty, finished)`
    - `player_gw(season, gw, player_id, fixture_id, minutes, total_points, was_home, opponent_team, fdr, ep_pre)`. One row per player per fixture. `fdr` is the difficulty from that player's side. `ep_pre` is copied from `player_snapshot.ep_next` for that gameweek, or NULL.
    - `meta(key PRIMARY KEY, value)`, with keys `next_gw`, `last_collected` (ISO UTC) and `current_season`

- [ ] **Step 1:** Record small trimmed fixtures from the real API: 3 teams, 6 players covering all 4 positions, 4 fixtures, and gameweek 1 live data. Commit them under `tests/fixtures/`.
- [ ] **Step 2: Write failing tests:**
```python
def test_collect_loads_players_and_positions(tmp_db, fake_client):
    collect.run(tmp_db, fake_client, "2026-27")
    assert {r["position"] for r in tmp_db.execute("select position from player")} == {"GK","DEF","MID","FWD"}
def test_collect_player_gw_has_fdr_from_player_side(...):  # home player row fdr == team_h_difficulty
def test_collect_is_idempotent(...):  # run twice -> same row counts
def test_collect_sets_meta(...):      # meta next_gw == first event with is_next true; last_collected set
def test_snapshot_ep_copied_to_player_gw_ep_pre(...)
```
- [ ] **Step 3:** Run `pytest tests/test_collect.py -v`. Expected: FAIL.
- [ ] **Step 4:** Implement `schema.sql`, `db.py` and `collect.py`. Fetch `event/{gw}/live/` for every finished gameweek not already in `player_gw`. Use `explain[].fixture` to split points per fixture in double gameweeks.
- [ ] **Step 5:** Run `pytest tests/test_collect.py -v`. Expected: PASS.
- [ ] **Step 6:** Run the collector once against the live API with `python -m fpl.collect --db data/fpl.db --season 2026-27`. Expected: non-zero row count, and `select value from meta where key='next_gw'` matches the FPL website.
- [ ] **Step 7: Commit** `fpl/`, `tests/` and `data/fpl.db` with the message `feat: SQLite schema and current-season collector`.

---

### Task 3: Past-season loader

**Files:**
- Create: `fpl/history.py`, `tests/fixtures/vaastav_merged_gw.csv`, `tests/fixtures/vaastav_fixtures.csv`
- Test: `tests/test_history.py`

**Interfaces:**
- Consumes: the Task 2 schema
- Produces: `history.load(conn, season: str, merged_gw_csv: Path, fixtures_csv: Path, teams_csv: Path) -> int`. It fills `team`, `player`, `fixture` and `player_gw` for that season. `ep_pre` comes from the archive's `xP` column. CLI: `python -m fpl.history --db data/fpl.db --season 2025-26` downloads the CSVs from the vaastav raw GitHub URLs into a temp directory, then loads them.

- [ ] **Step 1: Write failing tests** against small trimmed CSVs:
```python
def test_history_maps_positions(...):     # "GKP"->"GK", "DEF","MID","FWD"
def test_history_ep_pre_from_xP(...):     # row with xP 3.2 -> ep_pre == 3.2
def test_history_fdr_from_fixtures(...):  # away row fdr == team_a_difficulty
def test_history_double_gw_two_rows(...)  # player with 2 fixtures in gw -> 2 player_gw rows
```
- [ ] **Step 2:** Run `pytest tests/test_history.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement with the stdlib `csv` module. Use the newest complete season the archive has, preferring 2025-26 and falling back to 2024-25. Record which season was used in `meta` as `backtest_season`.
- [ ] **Step 4:** Run the tests. Expected: PASS. Then run the CLI for real. Expected: about 25k or more `player_gw` rows for the season.
- [ ] **Step 5: Commit** with the message `feat: load past season from vaastav archive`.

---

### Task 4: Forecast SQL views

**Files:**
- Create: `fpl/sql/forecast.sql`
- Test: `tests/test_forecast.py`

**Interfaces:**
- Consumes: `player_gw`, `fixture`, `player`, `player_snapshot` and `meta`
- Produces these views:
  - `v_fdr_multiplier(season, position, fdr, mult)`
  - `v_player_form(season, player_id, as_of_gw, pts_per_90, start_prob, minutes_last5)`. This uses only gameweeks earlier than `as_of_gw`, so it never sees the future.
  - `v_xp(season, player_id, gw, as_of_gw, xp_model)`. One row per player per target gameweek. It sums over that gameweek's fixtures and returns 0 when there is no fixture.
  - `v_xp_next(player_id, xp_next, xp_next3, start_prob, xp_source)`. This is for the current season and `meta.next_gw`.

**The formula** (put this text, word for word, as a comment at the top of `forecast.sql`, because the owner must be able to explain it):
```
expected points for a fixture =
    start_prob × pts_per_90 × fdr multiplier
start_prob   = minutes in last 5 GWs / 450, capped at 1,
               then × chance_of_playing_next_round/100 when FPL gives one
pts_per_90   = total points per 90 minutes over the last 6 GWs (needs ≥ 180 min);
               otherwise the position average pts_per_90 for that season
fdr mult     = (average points per 90 for that position at that FDR) ÷
               (average points per 90 for that position overall), from the past season
```
- `xp_next3` sums `xp_model` for gameweeks `next_gw` to `next_gw+2`.
- `xp_next` uses `player_snapshot.ep_next` when `meta.forecast_source = 'fpl_ep'`, and `xp_model` otherwise. `forecast_source` is set by Task 5 and defaults to `'model'`.

- [ ] **Step 1: Write failing tests** on a hand-built database (`conftest.db_with_sample`):
```python
def test_start_prob_caps_at_1(...):            # 5 x 90 min -> 1.0 ; 5 x 45 -> 0.5
def test_start_prob_uses_chance_next(...):     # 450 min, chance_next 25 -> 0.25
def test_pts_per_90_uses_only_past(...):       # as_of_gw 4 ignores gw 4+ points
def test_xp_new_player_uses_position_default(...):  # 0 minutes -> pts_per_90 == position avg, start_prob 0 -> xp 0, not NULL
def test_xp_blank_and_double(...):             # team with no fixture gw -> 0 ; two fixtures -> sum of both
def test_fdr_multiplier_mean_is_about_1(...):  # minutes-weighted mean mult per position within 0.05 of 1
def test_xp_next_respects_forecast_source(...) # meta 'fpl_ep' -> xp_next == ep_next
```
- [ ] **Step 2:** Run `pytest tests/test_forecast.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `forecast.sql` with window functions (`ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING` over gameweeks). Aggregate per player per gameweek first, so double gameweeks don't double-count form.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat: explainable expected-points forecast as SQL views`.

---

### Task 5: Backtest and report

**Files:**
- Create: `fpl/backtest.py`, `reports/backtest.md` (generated)
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `v_xp`, `player_gw`, and `meta.backtest_season`
- Produces:
  - `backtest.run(conn, season: str, from_gw: int = 6) -> dict`, which returns `{"model": {"mae": float, "n": int}, "last5_avg": {...}, "fpl_ep": {...}, "winner": str}`
  - `backtest.write_report(result: dict, path: Path)`
  - It sets `meta.forecast_source` to `'fpl_ep'` if `fpl_ep` has the lowest MAE, otherwise `'model'`.
  - CLI: `python -m fpl.backtest --db data/fpl.db`

**What counts:** Score every player-gameweek from `from_gw` onwards where the player was in a squad: minutes > 0 or `start_prob` > 0. Measure the mean absolute error between each prediction and actual `total_points` summed per gameweek. The baselines are:
- `last5_avg`: the mean of the player's last 5 gameweek totals
- `fpl_ep`: `ep_pre`

Rows where `ep_pre` is NULL are excluded from all three methods, so every method is scored on the same rows.

- [ ] **Step 1: Write failing tests:**
```python
def test_backtest_same_rows_for_all_methods(...):  # n equal across methods
def test_backtest_perfect_predictor_mae_zero(...): # sample where ep_pre == actual -> fpl_ep mae 0, winner "fpl_ep"
def test_backtest_sets_forecast_source(...)
def test_report_contains_table(...):  # markdown has "| Method | MAE | Rows |" and all 3 methods
```
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement it. The report states the season, the gameweek range, a table of results, the winner, and one sentence in plain words on what that means for the app. Report the result even if the model loses.
- [ ] **Step 4:** Run the tests. Expected: PASS. Run the CLI on the real database, then open `reports/backtest.md` and check that the numbers are plausible (an MAE of roughly 1.5–3).
- [ ] **Step 5: Commit** with the message `feat: honest backtest against last-5 and FPL ep baselines`.

---

### Task 6: Reference sample and scheduled refresh

**Files:**
- Create: `fpl/reference.py`, `.github/workflows/collect.yml`, `tests/fixtures/entry_picks_*.json`
- Modify: `fpl/sql/schema.sql` (add the reference tables)
- Test: `tests/test_reference.py`

**Interfaces:**
- Consumes: `FplClient`, `collect.run`
- Produces:
  - Tables `squad_pick(squad_id TEXT, player_id, slot INT, is_starter INT, is_captain INT)` and `reference_squad(season, gw, squad_id, entry_id)`. Reference squads use `squad_id = 'ref:<entry_id>'`. The user squad later uses `'user'`.
  - `reference.sample(conn, client, season: str, gw: int, n: int = 500, seed: int | None = None) -> int`. It draws random entry IDs between 1 and `bootstrap.total_players` and skips 404s and IDs whose last-gameweek picks are missing, until it has `n` squads or has tried `3*n` IDs. It replaces the previous sample for that season.
  - Workflow: a daily cron (`0 6 * * *`) plus `workflow_dispatch`. It runs `python -m fpl.collect`, then `python -m fpl.reference` on Tuesdays only, then `python -m fpl.backtest` when a new gameweek has finished. It commits `data/fpl.db` and `reports/backtest.md` if they changed. The token gets `contents: write` permission.

**Reference population** (record this in `analysis/data_dictionary.md` in Task 11): a random sample of 500 active public FPL teams, refreshed weekly. "Average manager" means the mean of this sample.

- [ ] **Step 1: Write failing tests:**
```python
def test_sample_skips_404_and_reaches_n(...)    # fake client: some ids 404 -> still n squads
def test_sample_stops_after_3n_attempts(...)    # all 404 -> returns 0, no infinite loop
def test_sample_replaces_previous(...)          # run twice -> only latest sample rows
```
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement `reference.py` and the workflow.
- [ ] **Step 4:** Run the tests. Expected: PASS. Run `python -m fpl.reference --db data/fpl.db --n 500` once for real (about 5–10 minutes). Expected: 500 squads.
- [ ] **Step 5: Commit** with the message `feat: weekly reference sample and scheduled refresh`.

---

### Task 7: Squad loading, money, rules and swaps

**Files:**
- Create: `fpl/squad.py`, `tests/fixtures/entry_*.json`
- Test: `tests/test_squad.py`

**Interfaces:**
- Consumes: `FplClient`, and the `player` and `player_snapshot` tables
- Produces:
  - `@dataclass Pick(player_id: int, slot: int, is_starter: bool, is_captain: bool, selling_price: int)`
  - `@dataclass Squad(team_id: int, gw: int, picks: list[Pick], bank: int, free_transfers: int, note: str | None)`. `gw` is the gameweek the picks came from. `note` holds text like "Free Hit last week — showing your GW8 squad".
  - `class SquadError(Exception)`. Its message is shown to the user as written.
  - `load_squad(client, conn, team_id: int | str) -> Squad`
  - `selling_price(buy: int, now: int) -> int`, which returns `now if now <= buy else buy + (now - buy) // 2`
  - `estimate_free_transfers(history: dict) -> int`. Start at 1, add 1 each gameweek up to a cap of 5, and subtract `event_transfers` (never below 0, ignoring transfers made under Wildcard or Free Hit). The result is between 0 and 5, and the user can override it in the UI.
  - `validate(squad: Squad, conn) -> list[str]`, which returns the rule violations found:
    - squad shape: 2 GK, 5 DEF, 5 MID and 3 FWD
    - no more than 3 players from one club
    - budget: `bank` ≥ 0
    - starting XI: exactly 1 GK, at least 3 DEF, at least 2 MID and at least 1 FWD
  - `swap(squad: Squad, out_id: int, in_id: int, conn) -> Squad`. It swaps players of the same position only and keeps the slot, starter and captain flags. It returns a new `Squad` with `bank = bank + out.selling_price - in.now_cost`. The new player's `selling_price` is their current `now_cost`. It raises `SquadError` when the result fails `validate`.

- [ ] **Step 1: Write failing tests:**
```python
def test_load_squad_unknown_id(...):      # 404 -> SquadError("No FPL team found with ID 99999999")
def test_load_squad_non_numeric(...):     # "abc" -> SquadError("Team ID must be a number")
def test_load_squad_preseason(...):       # current_event None -> SquadError("Season hasn't started — no squad to analyse yet")
def test_free_hit_uses_previous_picks(...): # active_chip "freehit" at gw 9 -> picks from gw 8, note mentions Free Hit
def test_selling_price_rule():
    assert selling_price(80, 83) == 81
    assert selling_price(80, 85) == 82
    assert selling_price(80, 78) == 78
def test_selling_price_from_transfers(...): # player bought gw5 at 60, now 63 -> 61
def test_free_transfers_cap_and_spend(...): # 6 idle gws -> 5 ; spend 2 next gw -> 4 (after +1)
def test_validate_three_per_club(...)
def test_swap_rejects_cross_position(...)
def test_swap_rejects_over_budget(...)
def test_swap_keeps_captain_flag(...)
```
- [ ] **Step 2:** Run `pytest tests/test_squad.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement it. The buy price comes from `entry_transfers` (`element_in_cost`) for players who were transferred in. For players kept since the first picks, use their `now_cost` at that gameweek. Prefer the `player_snapshot` row for that gameweek, then `element_summary(player).history[round].value`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat: load squad with selling prices, free transfers, rules and swaps`.

---

### Task 8: Squad metrics, grades and projection

**Files:**
- Create: `fpl/sql/squad.sql`, `fpl/analyse.py`
- Test: `tests/test_analyse.py`

**Interfaces:**
- Consumes: `squad_pick`, `v_xp_next`, `fixture`, `player`, `player_snapshot`, `reference_squad`, and `Squad` from Task 7
- Produces:
  - View `v_squad_metrics(squad_id, attack, midfield, defence, fixtures, risk, bench, projected)`:
    - `attack`, `midfield` and `defence` are the sums of `xp_next` over starters at FWD, at MID, and at DEF plus GK.
    - `fixtures` is the mean FDR of the starters' fixtures over `next_gw` to `next_gw+4`. Lower is better.
    - `risk` is the share of the starters' `xp_next` that comes from players with `status != 'a'`, `chance_next < 75`, or `start_prob < 0.6`. Lower is better.
    - `bench` is the sum of `xp_next` over non-starters.
    - `projected` is the starters' `xp_next` plus the captain's `xp_next` again (×2). There are no auto-subs.
  - View `v_squad_grades(squad_id, area, value, pct, grade)`. `pct` is the percentile of the user's value among `ref:%` squads, inverted for `fixtures` and `risk`. Grades: A ≥ 80, B ≥ 60, C ≥ 40, D ≥ 20, otherwise E.
  - `@dataclass PlayerView(player_id, name, position, club, xp_next, colour: Literal['green','amber','red'], flag: str | None, is_starter, is_captain)`
  - `@dataclass Analysis(players: list[PlayerView], grades: dict[str, str], projected: float, average_projected: float, gw: int, note: str | None)`
  - `analyse_squad(conn, squad: Squad) -> Analysis`. It writes the squad to `squad_pick` as `'user'`, replacing any existing rows, then reads the views.
  - Colour rule: red if `xp_next < 2`, or if the player is flagged with `chance_next` ≤ 50; amber if `xp_next < 4`; green otherwise. `flag` holds FPL's news text for any player whose `status != 'a'`.

- [ ] **Step 1: Write failing tests** with a sample database holding 5 reference squads plus a user squad:
```python
def test_projected_doubles_captain(...)
def test_bench_excluded_from_projection(...)
def test_grade_best_squad_gets_A(...)          # user beats all refs on attack -> "A"
def test_fixtures_grade_inverted(...)           # easiest fixtures -> "A"
def test_risk_counts_flagged_starter(...)       # starter status 'i' with xp 5 of total 50 -> risk 0.1
def test_colour_rules(...)                      # xp 1.5 -> red; 3 -> amber; 6 -> green; 6 but chance 25 -> red
def test_average_projected_is_ref_mean(...)
```
- [ ] **Step 2:** Run `pytest tests/test_analyse.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `squad.sql` (use `percent_rank()` over the user plus reference rows) and `analyse.py`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat: squad metrics, relative grades and projection in SQL`.

---

### Task 9: Transfer suggestions

**Files:**
- Create: `fpl/suggest.py`
- Test: `tests/test_suggest.py`

**Interfaces:**
- Consumes: `Squad`, `swap`, `validate` (Task 7), `analyse_squad` (Task 8) and `v_xp_next`
- Produces:
  - `@dataclass Suggestion(out_id, in_id, out_name, in_name, gain3: float, hit: int, net_gain3: float, grade_change: tuple[str, str, str])`. `grade_change` is (area, before, after).
  - `suggest(conn, squad: Squad, k: int = 2) -> list[Suggestion]`

**Algorithm:**
1. For each squad player, consider every same-position player not already in the squad who is affordable (`now_cost` ≤ the out-player's selling price plus bank) and does not break the 3-per-club rule.
2. `gain3 = xp_next3(in) - xp_next3(out)`.
3. `hit` is 0 if `free_transfers` ≥ 1, otherwise 4.
4. `net_gain3 = gain3 - hit`.
5. Keep candidates with `net_gain3` > 0.5. Take the best per out-player, then the top `k` by `net_gain3`, with each out-player used at most once.
6. Show each suggestion's grade effect using the area for that position, comparing `analyse_squad` before and after the swap.

- [ ] **Step 1: Write failing tests:**
```python
def test_suggests_replacing_injured_player(...)   # injured MID xp3 0 -> top suggestion has that out_id
def test_respects_budget(...)                     # best player unaffordable -> not suggested
def test_respects_three_per_club(...)
def test_hit_applied_when_no_free_transfers(...)  # free_transfers 0 -> hit 4, net_gain3 == gain3 - 4
def test_no_suggestion_when_gain_small(...)       # all gains < 0.5 -> []
def test_distinct_out_players(...)
```
- [ ] **Step 2:** Run `pytest tests/test_suggest.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement it. Rank candidates in SQL first (top 10 per position by `xp_next3`) to keep the loop small.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat: affordable transfer suggestions with hit cost`.

---

### Task 10: Streamlit app

**Files:**
- Create: `app.py`
- Test: `tests/test_app.py` (using `streamlit.testing.v1.AppTest`)

**Interfaces:**
- Consumes: `db.memory_copy`, `FplClient`, `load_squad`, `swap`, `analyse_squad`, `suggest`, `SquadError` and `FplApiError`

**Layout** (matching `docs/mockups/team-analysis-v2.html`):
- **Top:** a "Team ID" input and an **Analyse** button. Remember the last team ID in `st.query_params`, so a link like `?team=1234567` is shareable.
- **Banner:** `Squad.note`, and "Analysing your GW{gw} squad".
- **Left column (2/3 width):** the pitch on a green background, drawn with `st.markdown` HTML. Rows are FWD, MID, DEF and GK. Each player is a chip showing `name xp_next` in their colour; the captain gets "(C)" and flagged players get "✚". The bench is a row below the pitch.
- **Right column (1/3 width):** a grades table with Attack, Midfield, Defence, Fixtures (next 5), Injury / rotation risk and Bench, then "Projected: X pts", with "average manager: Y" underneath.
- **Below:** "Suggested moves", as one line per suggestion: `Out → In · +gain over next 3 GWs · Area B− → B+`, plus "(−4 hit)" when it applies. If there are none, show "No transfer clearly worth making this week."
- **Expander "Edit squad":** pick an out-player, then a same-position in-player from a select box that searches by name. Apply it with `swap`. On `SquadError`, show `st.error`. Everything recalculates on rerun. Include a "Free transfers" number input (0–5), defaulting to the estimate.
- **Footer:** "Data: official FPL API · last updated {meta.last_collected}" and the forecast source ("FPL's own predictions" or "this site's model"), linking to `reports/backtest.md` on GitHub.
- **Errors:** `SquadError` shows its message with `st.error`. `FplApiError` shows "FPL data is unavailable right now — try again in a few minutes." If `last_collected` is more than 36 h old, show `st.warning("Player data may be out of date (last updated …)")`.
- **Caching:** `memory_copy` uses `st.cache_resource` (one copy per server). API calls use `st.cache_data(ttl=600)`.

- [ ] **Step 1: Write failing tests** with `AppTest` and a monkeypatched client:
```python
def test_app_renders_grades_and_projection(...)  # 6 grade rows, text contains "Projected"
def test_app_api_down_message(...)               # client raises FplApiError -> error text "FPL data is unavailable right now"
def test_app_bad_id_message(...)                 # "abc" -> "Team ID must be a number"
def test_app_stale_warning(...)                  # last_collected 3 days old -> warning shown
def test_app_swap_recalculates(...)              # apply swap -> projected value changes
```
- [ ] **Step 2:** Run `pytest tests/test_app.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `app.py` as UI only, with no calculations of its own.
- [ ] **Step 4:** Run the tests. Expected: PASS. Then run `streamlit run app.py`, load the owner's real team ID, and check by eye:
  - the pitch matches their FPL team
  - the grades and projection appear
  - the suggestions are affordable
  - it works at phone width (375 px)
- [ ] **Step 5: Commit** with the message `feat: Streamlit app with pitch view, grades, suggestions and squad editing`.

---

### Task 11: Owner's analysis kit, README and deploy notes

**Files:**
- Create: `analysis/README.md`, `analysis/data_dictionary.md`, `analysis/starter_queries.sql`, `README.md`
- Test: `tests/test_starter_queries.py`

**Interfaces:**
- Consumes: every table and view above

- [ ] **Step 1:** Write `analysis/data_dictionary.md`. Describe every table and view in plain English: one line per column, units (money in tenths of £m), the reference population definition (from Task 6) and the forecast formula (copied from Task 4).
- [ ] **Step 2:** Write `analysis/starter_queries.sql` with three commented worked examples answering the spec's questions:
  1. "Do fixtures or form predict points better?" Compare the correlation of FDR against points with the correlation of last-6 pts/90 against points, past season.
  2. "How often does the top expected-points player actually return 6 or more points?"
  3. "Which teams' defenders keep the most clean sheets at home?"

  End the file with 3 open questions, unanswered, for the owner to tackle.
- [ ] **Step 3: Write a failing test** that runs every statement in `starter_queries.sql` against `data/fpl.db` without error and checks each one returns at least 1 row. Run it. Expected: FAIL until the queries exist. Fix the queries until it passes.
- [ ] **Step 4:** Write `analysis/README.md`. It covers how to open `data/fpl.db` in DB Browser for SQLite (free) and in the `sqlite3` command line, and says this folder is the owner's workspace.
- [ ] **Step 5:** Write the top-level `README.md`. It has a one-line pitch, a screenshot placeholder, how it works (data, forecast, grades) and how to run it locally. Its "What I found" and "What I'd do differently" sections are left as clearly marked placeholders for the owner, with prompts but no ghost-written conclusions. Add a "Deploy" section listing the owner's manual steps:
  1. Create a public GitHub repo and push.
  2. Enable Actions.
  3. On share.streamlit.io, sign in with GitHub, choose New app, pick this repo and `app.py`, then Deploy.
- [ ] **Step 6:** Run the full test suite with `pytest -v`. Expected: all PASS.
- [ ] **Step 7: Commit** with the message `docs: analysis kit, data dictionary and README skeleton`.

---

## After the plan

The owner, not the builder, does these steps, because they need the owner's accounts: create the GitHub repo, push, enable Actions, and deploy on Streamlit Community Cloud. The builder can walk them through each step.

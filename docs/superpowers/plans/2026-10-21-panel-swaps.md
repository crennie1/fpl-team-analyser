# Panel Swaps and Planning Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "Edit squad" box with transfer planning on the team sheet: click a player → Replace → pick from every player in that position (👍 suggestions first), with over-budget planning, IN tags, a changes bar, before-vs-after and a transfer list.

**Architecture:** A plan is the fetched squad plus an ordered list of moves, replayed each rerun (`fpl/plan.py`, pure and tested). The team sheet becomes a two-way Streamlit component (`components.declare_component` on a static folder) that sends small action messages; Python applies them to the plan before building the page data, so every number still comes from the existing analysis code and SQL views. All new UI (list, tags, bar, plan section) is drawn by the component's own script in the existing dark style.

**Tech Stack:** Python 3, Streamlit 1.66.0, SQLite views, vanilla JS (no build step), pytest, node for the JS harness tests.

**Spec:** `docs/2026-10-21-panel-swaps-design.md` (approved 21 Oct 2026). Mockup of the agreed page: `.superpowers/brainstorm/97755-1792605994/content/full-page.html` (local, not committed).

## Global Constraints

- Streamlit stays `1.66.0`; no new dependencies in `requirements.txt`; no JS build tools.
- No player photos or Premier League kit images; use the drawn kits (`fpl/ui/kits.py`, `shirt()` in the page script).
- Same dark look as `fpl/ui/team_view.html`; must work at ≈400px wide (panel opens under the tapped row, as now).
- UI only displays: every number comes from `fpl/analyse.py`, `fpl/suggest.py`, `fpl/cards.py`, `fpl/plan.py` and the SQL views.
- Hit = `HIT_COST` (4, from `fpl/suggest.py`) × max(0, changes − free transfers). Changes = players in the plan not in the fetched squad. Chips ignored.
- Planning mode: budget never blocks a swap; the position rule and 3-per-club rule always do. The strict rules elsewhere (suggestion engine) must not weaken.
- 👍: up to 3 per squad player, gain3 > 0 before any hit, affordable from plan bank + out-player's selling price, 3-per-club, and bench rule R21. Same gain formula as the SELL panel.
- Copy, verbatim: "No player in this position gets you back within budget"; "Make these in the FPL app. This site never changes your real team."; "already 3 from this club"; "← back to stats"; "Undo last"; "Reset to my team"; "IN · was <name>".
- Bar, IN tags and plan section appear only when changes > 0, except the free-transfers control, which is always shown.
- Existing tests keep passing: `.venv/bin/pytest -q` (208 before this build). Tests that drove the removed Edit squad box are rewritten, not deleted without replacement.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Don't push in the hours before a gameweek deadline.

## Review Focus

1. **Swap back to the original player** (A → B, then B → A): changes drop to 0, the bar disappears, no hit. Test in Task 2.
2. **Undo a card whose player was swapped twice** (A → B → C): undo restores A, removes both moves, and a later move that now breaks the 3-per-club rule makes undo refuse with that rule's message, leaving the plan unchanged. Test in Task 2.
3. **Plan already over budget**: 👍 only for players who bring the bank back to ≥ 0; when none, the "No player in this position…" line shows; SELL tags vanish rather than erroring. Tests in Tasks 3 and 6.
4. **Bench 👍 promotion then undo**: the newcomer starts in place of the weakest starter; undo restores both players' slots, starter flags and captaincy exactly. Test in Task 2.
5. **Same action delivered twice** (rerun replays the last component value): it must be applied once. Test in Task 5.

---

### Task 1: Over-budget planning in swap and validate

**Files:**
- Modify: `fpl/squad.py` (`validate`, `swap`)
- Test: `tests/test_squad.py`

**Interfaces:**
- Produces: `validate(squad, conn, allow_over_budget: bool = False) -> list[str]`; `swap(squad, out_id, in_id, conn, allow_over_budget: bool = False) -> Squad`. With the flag, the "Over budget by …" problem is skipped; every other problem still raises. Default behaviour unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_swap_over_budget_allowed_in_planning_mode(conn, squad):   # use the module's existing fixtures
    pricey = <same-position player whose now_cost > out.selling_price + squad.bank>
    new = swap(squad, out_id, pricey, conn, allow_over_budget=True)
    assert new.bank < 0

def test_swap_over_budget_still_blocked_by_default(...):
    with pytest.raises(SquadError, match="Over budget"): swap(squad, out_id, pricey, conn)

def test_planning_mode_keeps_club_and_position_rules(...):
    with pytest.raises(SquadError, match="Too many players from one club"):
        swap(squad, out_id, fourth_from_club, conn, allow_over_budget=True)
    with pytest.raises(SquadError, match="same position"):
        swap(squad, out_id, other_position_id, conn, allow_over_budget=True)
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_squad.py -q` — expect the first test to FAIL (unexpected keyword).
- [ ] **Step 3: Implement** the flag in `validate` and pass it through from `swap`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — all pass.
- [ ] **Step 5: Commit** `feat: over-budget planning mode in swap`

---

### Task 2: The plan (moves, undo, reset, hits)

**Files:**
- Create: `fpl/plan.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Consumes: `swap(..., allow_over_budget=True)` (Task 1); `_promote` from `fpl/suggest.py`, renamed to public `promote` (update its one caller).
- Produces:
  - `@dataclass(frozen=True) class Move: out_id: int; in_id: int; promote_over: int | None = None` — `promote_over` is the starter who drops to the bench (bench 👍 picks only).
  - `build(base: Squad, moves: list[Move], conn) -> Squad` — replays moves from `base` with planning-mode `swap`, then `promote` when `promote_over` is set. Raises `SquadError` if a move no longer applies.
  - `changes(base: Squad, current: Squad) -> list[tuple[int, int]]` — `(original_out_id, current_in_id)` per slot where the player differs from base, in move order of first appearance.
  - `hit(n_changes: int, free_transfers: int) -> int` — `HIT_COST * max(0, n_changes - free_transfers)`.
  - `extra_hit(base, current, out_id, in_id, free_transfers) -> int` — hit after this swap minus hit now (never negative).
  - `undo_last(moves) -> list[Move]`; `undo_original(base, moves, original_id, conn) -> list[Move]` — drops every move in that slot's chain (the move that took `original_id` out and any later moves that took its successors out), checks `build` still works, else raises `SquadError` with the rule's message.
  - `add(base, moves, out_id, in_id, conn, promote_over=None) -> list[Move]` — appends and checks `build`; raises `SquadError` on rule breaks.

- [ ] **Step 1: Write the failing tests** (in `tests/test_plan.py`, using the same DB fixtures as `tests/test_suggest.py`):

```python
def test_no_moves_is_base(): assert build(base, [], conn) == base and changes(base, base) == []
def test_swap_back_to_original_cancels_change():
    m = add(base, [], A, B, conn); m = add(base, m, B, A, conn)
    assert changes(base, build(base, m, conn)) == []
def test_chain_counts_once_and_undo_restores_original():
    m = add(base, add(base, [], A, B, conn), B, C, conn)
    assert changes(base, build(base, m, conn)) == [(A, C)]
    assert undo_original(base, m, A, conn) == []
def test_undo_refuses_when_rule_breaks(): ...  # A→B frees a club slot, later X→Y fills it; undo A raises SquadError("Too many players from one club…") and moves unchanged
def test_promotion_and_undo_restore_slots_exactly():
    m = add(base, [], bench_mid, newcomer, conn, promote_over=weakest_starting_mid)
    cur = build(base, m, conn)
    assert pick(cur, newcomer).is_starter and not pick(cur, weakest_starting_mid).is_starter
    assert build(base, undo_original(base, m, bench_mid, conn), conn) == base
def test_hits(): assert hit(2, 1) == 4 and hit(1, 1) == 0 and hit(3, 0) == 12
def test_extra_hit_zero_when_replacing_an_in_player(): ...  # A→B made; extra_hit(base, cur, B, C, ft=0) == 0
def test_undo_last(): assert undo_last([m1, m2]) == [m1] and undo_last([]) == []
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_plan.py -q` — FAIL (module missing).
- [ ] **Step 3: Implement** `fpl/plan.py` with the signatures above; rename `_promote` → `promote` in `fpl/suggest.py`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — all pass.
- [ ] **Step 5: Commit** `feat: transfer plan with undo and hits`

---

### Task 3: 👍 options per player, and 3-week squad points

**Files:**
- Modify: `fpl/suggest.py`, `fpl/sql/squad.sql` (`v_squad_pick_xp`, `v_squad_metrics`), `fpl/analyse.py`, `analysis/data_dictionary.md`
- Test: `tests/test_suggest.py`, `tests/test_analyse.py`

**Interfaces:**
- Produces:
  - `@dataclass class Option: in_id: int; gain3: float; starts_instead: int | None` (player id of the starter he'd replace, bench only).
  - `options_for(conn, squad: Squad, out_id: int, k: int = 3) -> list[Option]` — best `k` by gain3 desc, gain3 > 0, same rules as `suggest` (affordable from `squad.bank + pick.selling_price`, 3-per-club after the out-player leaves, R21 bench rule), no hit applied. Empty when nothing is affordable.
  - `suggest()` behaviour unchanged; both share one private candidate helper so the gain formula exists once.
  - `Analysis.projected3: float` — starters' `xp_next3` + captain's `xp_next3` again, from a new `projected3` column in `v_squad_metrics` (add `xp_next3` to `v_squad_pick_xp`). Grades unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_options_match_sell_gain(conn, squad):
    s = suggest(conn, squad)[0]
    o = next(o for o in options_for(conn, squad, s.out_id) if o.in_id == s.in_id)
    assert o.gain3 == pytest.approx(s.gain3)
def test_options_at_most_three_positive_sorted(): ...  # len <= 3, all gain3 > 0, descending
def test_options_bench_rule_names_starter(): ...        # bench MID: starts_instead == weakest starting MID id
def test_options_over_budget_only_back_within_budget():
    poor = replace(squad, bank=-8)
    assert all(price(o.in_id) <= poor.bank + sp(out) for o in options_for(conn, poor, out))
def test_suggest_over_budget_returns_list_not_error(): assert isinstance(suggest(conn, replace(squad, bank=-50)), list)
def test_projected3_is_starters_plus_captain(): ...      # analyse_squad(...).projected3 == hand sum from xp_next_cache
def test_grades_unchanged_by_projected3_column(): ...    # same grades as before for the fixture squad
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_suggest.py tests/test_analyse.py -q` — FAIL.
- [ ] **Step 3: Implement** helper extraction, `options_for`, the view columns and `Analysis.projected3`; document `projected3` in `analysis/data_dictionary.md`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — all pass.
- [ ] **Step 5: Commit** `feat: per-player replacement options and 3-week squad points`

---

### Task 4: Page data (pool, card extras, plan summary)

**Files:**
- Modify: `fpl/cards.py`; Modify: `fpl/plan.py` (summary)
- Test: `tests/test_cards.py`, `tests/test_plan.py`

**Interfaces:**
- Consumes: `options_for`, `Option` (Task 3); `changes`, `hit`, `extra_hit` (Task 2).
- Produces:
  - `replacement_pool(conn) -> dict[str, list[dict]]` keyed `"GK"|"DEF"|"MID"|"FWD"`; each row `{"id", "name", "full_name", "initials", "club", "price" (£m float), "xp3", "fixtures": [{"opp", "home", "fdr"}] (next 3)}`. Fixtures fetched in one query for all teams, not per player. Cached per database file in the app like `cached_weakness`.
  - `player_cards(...)` gains keyword `extras: dict[int, dict] | None = None`; each card merges `extras.get(id, {})`. Extras per card: `"selling_price"` (£m), `"options": [{"id", "gain3", "hit", "starts_instead_of"}]` (name of that starter), `"was"` (original player's web_name or None), `"original_id"` (int or None).
  - `plan.summary(base, current, base_analysis, plan_analysis, names: dict[int,str], prices: dict[int,float], free_transfers) -> dict | None` — None when no changes; else `{"changes": [{"out_id","out_name","out_price","in_id","in_name","in_price","diff"}], "n_changes", "ft_used", "hit", "bank", "compare": {"pts3": [real, plan], "pts3_after_hits": [real, plan - hit], "grades": [[area, before, after], …only changed], "bank": [real, plan]}}`. Money in £m floats rounded to 0.1.

- [ ] **Step 1: Write the failing tests**

```python
def test_pool_has_every_position_and_fixtures(conn):
    pool = replacement_pool(conn); assert set(pool) == {"GK","DEF","MID","FWD"}
    row = pool["FWD"][0]; assert {"id","name","club","price","xp3","fixtures"} <= row.keys() and len(row["fixtures"]) <= 3
def test_cards_merge_extras(): ...           # card with extras {"was": "X"} has card["was"] == "X"; others None-free
def test_summary_none_without_changes(): assert summary(base, base, a, a, {}, {}, 1) is None
def test_summary_hits_and_only_changed_grades():
    s = summary(...two changes, ft=1...)
    assert s["hit"] == 4 and s["compare"]["pts3_after_hits"][1] == pytest.approx(plan_a.projected3 - 4)
    assert all(b != a for _, b, a in s["compare"]["grades"])
```

- [ ] **Step 2: Run** the two test files — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — all pass.
- [ ] **Step 5: Commit** `feat: page data for replacement list and plan summary`

---

### Task 5: Two-way team sheet and app wiring

**Files:**
- Create: `fpl/ui/team_sheet/index.html` (moved from `fpl/ui/team_view.html` via `git mv`, plus the message bridge)
- Modify: `app.py`, `tests/test_app.py`, `tests/test_ui.py`, `tests/js/*.js`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces:
  - Component: `TEAM_SHEET = components.declare_component("team_sheet", path=str(Path(__file__).parent / "fpl" / "ui" / "team_sheet"))`, mounted as `TEAM_SHEET(payload=payload, key="team_sheet", default=None, on_change=on_sheet_action)`.
  - Page script entry: `render(payload)` draws everything (the harnesses call it instead of relying on `/*DATA*/`). The bridge: on load posts `streamlit:componentReady` (apiVersion 1); on `streamlit:render` calls `render(event.data.args.payload)`; after each draw posts `streamlit:setFrameHeight` with `document.body.scrollHeight`; `send(action)` posts `streamlit:setComponentValue` with `{...action, n: ++counter}`. Bridge code guards `window.parent`/`addEventListener` so the node harnesses still run.
  - Actions: `{"type": "swap", "out_id", "in_id"}`, `{"type": "undo", "original_id"}`, `{"type": "undo_last"}`, `{"type": "reset"}`, `{"type": "set_ft", "ft": 0-5}`.
  - Session state per team: `ss["plan"] = {"team": str, "moves": list[Move], "ft": int, "last_n": int, "error": str | None, "focus_id": int | None}`. Reset when the team ID changes or "Analyse" is pressed (`fresh`).
  - `apply_action(state: dict, action: dict, base: Squad, conn) -> dict` (pure, in `app.py` or `fpl/plan.py`): ignores actions whose `n` ≤ `last_n`; for `swap` it calls `options_for` on the current squad and sets `promote_over` when the chosen `in_id` is an option with `starts_instead`; `SquadError` goes to `state["error"]`, plan unchanged; after a swap `focus_id = in_id`.
  - Payload gains: `"pool"`, `"base_grades"`, `"plan"` (summary or None), `"ft"`, `"bank"` (£m, plan), `"focus_id"`, `"error"`. App stores the payload in `st.session_state["team_payload"]` so tests can read it.
  - Removed: `edit_squad`, `request_swap`, `current_squad`, `candidates`, the "Edit squad" expander and the test-swap caption.

- [ ] **Step 1: Spike check (5 min, no commit):** mount a declared component in a scratch app, confirm `on_change` runs before the script body and `st.session_state["team_sheet"]` holds the posted value, and that `AppTest` runs an app containing it without exceptions. Note the findings in the task report. If `AppTest` cannot run it, wrap the mount so tests can stub it (`if "TEAM_SHEET_STUB" in os.environ`).
- [ ] **Step 2: Write the failing tests**

```python
def test_apply_action_ignores_replayed_n(): ...   # same {"n": 3, ...} twice → one move
def test_apply_action_swap_error_kept_plan_unchanged(): ...  # club-rule break → state["error"] set, moves same
def test_apply_action_bench_option_promotes(): ...           # chosen 👍 for bench MID → Move.promote_over set
def test_apply_action_set_ft_bounds(): ...                   # ft clamped 0..5
def test_app_plan_from_session_moves(env):                   # rewrite of test_app_swap_recalculates
    at = run(); at.session_state["plan"] = {...moves=[Move(USER+10, POOL+10)]...}; at.run()
    p = at.session_state["team_payload"]
    assert p["plan"]["n_changes"] == 1 and "P9110" in [c["name"] for c in p["cards"]]
def test_app_over_budget_plan_shows_not_errors(env): ...     # rewrite of test_app_swap_error_shown: bank < 0 → p["bank"] < 0, no st.error
def test_app_changes_use_free_transfers(env): ...            # rewrite of test_app_test_swaps_use_up_free_transfers: sells carry hit 4 after one change with ft 1
def test_app_has_no_edit_squad_box(env): assert not at.get("expandable")
```

Update `payload(at)` in `tests/test_app.py` to read `at.session_state["team_payload"]`; update `render()` in `tests/test_ui.py` and both harnesses to call `render(payload)`.

- [ ] **Step 3: Run** `.venv/bin/pytest -q` — new tests FAIL.
- [ ] **Step 4: Implement** the bridge, wiring and removals. No new visible UI yet beyond what Tasks 6–7 add; the page must look as today with zero changes.
- [ ] **Step 5: Run** `.venv/bin/pytest -q` — all pass.
- [ ] **Step 6: Check in the browser:** `preview_start` `fpl-app`, open `?team=<a real ID>`, confirm the page looks as before and no console errors.
- [ ] **Step 7: Commit** `feat: two-way team sheet component`

---

### Task 6: Replacement list in the side panel

**Files:**
- Modify: `fpl/ui/team_sheet/index.html`
- Test: `tests/test_ui.py` (node harness)

**Interfaces:**
- Consumes: payload fields from Tasks 4–5; `send(action)` from Task 5.

Behaviour (spec §1–2): a **Replace** button in the stats panel; Replace switches the panel to list mode with "← back to stats"; search box filters by name (case- and accent-insensitive); sort chips "Suggested first" (default), "Pts 3 wks", "Price", "Club"; 👍 section (from `card.options`) showing "+N pts" and ", −4 hit" when `hit`; then all others of that position from `pool`, excluding squad players; row = kit, name, club, next 3 opponents (fdr colours), price, xp3; price amber when `price > bank + selling_price`; rows that break 3-per-club (club count after the out-player leaves ≥ 3) greyed, not clickable, reason "already 3 from this club"; when `card.options` is empty and `bank < 0`, show "No player in this position gets you back within budget"; clicking a row calls `send({type:"swap", out_id, in_id})`. List mode and search text survive a rerun; after a swap the panel shows `focus_id`'s stats. On ≤760px the list opens under the tapped row as the panel does now. Show `payload.error` in the panel's `.warn` style.

- [ ] **Step 1: Write the failing harness tests**

```python
@needs_node
def test_replace_list_puts_options_first_with_thumbs(): ...      # first rows carry 👍 and "+N pts"
def test_replace_list_excludes_squad_and_other_positions(): ...
def test_club_full_rows_greyed_with_reason(): ...                 # "already 3 from this club", no onclick/data-in
def test_amber_price_when_unaffordable(): ...
def test_no_options_over_budget_message(): ...                    # exact copy
def test_hit_shown_on_option(): ...                               # ", −4 hit"
def test_names_escaped_in_list(): ...                             # "<b>" in a name stays text
```

Extend `render_harness.js` with optional args to call `pick(i)`, `openReplace()`, and to capture `send()` calls.

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_ui.py -q` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — all pass.
- [ ] **Step 5: Browser check** at desktop and `resize_window` mobile: Replace → list → pick → team updates; screenshot both.
- [ ] **Step 6: Commit** `feat: replacement list with suggestions in the stats panel`

---

### Task 7: IN tags, changes bar, plan section, grade arrows

**Files:**
- Modify: `fpl/ui/team_sheet/index.html`
- Test: `tests/test_ui.py`

Behaviour (spec §3, mockup `full-page.html`): card with `was` gets blue "IN · was <name>" tag and an "undo" link → `send({type:"undo", original_id})`; bar above the pitch: free transfers control (always shown; − / + or a small number field, 0–5 → `set_ft`), and when `plan` is set: "N changes", "N free transfer(s) used", red "−N pt hit" (only if hit > 0), amber "£X.Xm over budget" (only if bank < 0), "↶ Undo last", "Reset to my team"; "Your plan vs your real team" section under the pitch when `plan` is set: compare table (pts next 3 wks, …after hits, changed grades with ▲/▼, bank) and the Out → In list with price differences and the fixed copy line; grade tiles show ▲/▼ where the letter differs from `base_grades`. Nothing of this (except the free-transfers control) renders when `plan` is null.

- [ ] **Step 1: Write the failing harness tests**

```python
def test_no_plan_no_bar_tags_or_section(): ...            # only the free-transfer control
def test_in_tag_and_undo_send_original_id(): ...
def test_bar_pills_hit_and_over_budget_only_when_nonzero(): ...
def test_plan_section_copy_and_rows(): ...                # exact copy line, one row per change
def test_grade_arrow_when_letter_changes(): ...
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** `.venv/bin/pytest -q` — all pass.
- [ ] **Step 5: Browser check:** make 2 swaps (one over budget), undo one via its card, Undo last, Reset; screenshots desktop + mobile.
- [ ] **Step 6: Commit** `feat: plan bar, IN tags and before-vs-after`

---

### Task 8: Docs and final check

**Files:**
- Modify: `docs/HANDOFF.md` (§2 features, §9 test count), `docs/ROADMAP.md` (mark #2 done), `docs/interview-explainer.md` only if a sentence about "Edit squad" exists, `README.md` feature list if it mentions Edit squad.

- [ ] **Step 1:** `grep -rn "Edit squad" --include=*.md .` and update every hit.
- [ ] **Step 2: Run** `.venv/bin/pytest -q` — all pass; record the new count in HANDOFF §9.
- [ ] **Step 3: Commit** `docs: panel swaps shipped`

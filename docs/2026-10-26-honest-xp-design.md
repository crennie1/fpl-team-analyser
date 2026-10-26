# Honest xP — Design

Date: 2026-10-26
Status: draft, awaiting owner approval
Builds on: panel swaps (live since 26 Oct 2026). Findings: `docs/POLISH.md` item 5.
Mockup (local only): `.superpowers/brainstorm/17936-1793051058/content/xp-breakdown-v2.html`.

## Intent and why

The site's xP is FPL's own "expected points" (`ep_next`). On 26 Oct we found:

1. **It's really FPL's form.** In live FPL data, `ep_next` equals FPL's `form` (average points per game over about 30 days) for 412 of 451 players. It's a backward-looking average, not a forecast. The owner noticed it "feels like lying": it's the main number people use to pick their team, and it has no reasoning behind it.
2. **The backtest that picked it was leaked.** The past-season archive's FPL prediction (`ep_pre`, the vaastav `xP` column) was recorded after each gameweek:
   - It matches the 4-gameweek points average *including* that week (error 0.66 for 2024-25, 0.59 for 2025-26) far better than the average of the weeks before (1.02 / 1.10).
   - Players who scored 12+ jump from about 4 the week before to about 7.5 in that same week.
   - So FPL "won" the backtest (1.37 vs v2's 1.82) by seeing the results.
3. **On a clean week, v2 wins.** For GW8 2026-27, using FPL's prediction saved by our own collector before kick-off (23 Oct) and results from the live API:

   | Method | Error, players who played (298) | Error, all players (422) |
   |---|---|---|
   | v2 | 2.11 | 1.71 |
   | Last-5 average | 2.39 | 2.26 |
   | FPL's prediction | 2.61 | 2.07 |

   This is one gameweek only.

The owner wants each player's xP to show **why** it is that value and **which stats** it's built from. The project is a data-analyst portfolio piece, so the corrected result, and how the leak was found, become part of the story.

## What the owner decided

### 1. xP comes from our own model
Every xP on the site uses the forecast chosen by a clean backtest (see §3), which on current evidence is v2: cards, stats panel, "xP next 3", 👍 options, SELL suggestions, grades and projected points. FPL's number is no longer used as the site's xP anywhere.

### 2. "Why is his xP 4.5?" breakdown in the player panel
As in the mockup:
- **Headline:** the xP number, with a stacked bar showing its parts.
- **One row per part**, each with points and a one-line plain-English reason built from the real inputs. These are v2's own terms, so they add up to the xP (rounding aside):
  - **Playing:** start probability × 2 appearance points. Reason: chance he plays, and minutes in the last 5 gameweeks.
  - **Goals & assists:** start_prob × calib × (xg90 × goal points + xa90 × 3) × opponent ratio. Reason: his xG and xA per 90 over the last 6, and how much the opponent concedes to his position.
  - **Clean sheet:** start_prob × CS points × cs_chance. Reason: the chance, from his team's xG conceded and the opponent's attack. Not shown for forwards, who get 0 clean-sheet points.
  - **DefCon:** start_prob × 2 × defcon_chance. Reason: the chance, from his hit rate in the last 6 and the opponent. Not shown for goalkeepers.
- **Bonus points must be obvious (owner):**
  - an amber warning under the number: "⚠ Bonus points not included. Top attackers often earn 1–2 more a game than this shows.";
  - plus a dashed "Bonus points — not counted" row in the breakdown.
- **"Also not counted" line:** cards, own goals.
- **Comparison strip:** this site's xP, FPL's number labelled "recent form", and his last-5 average.
- **Double gameweek:** one breakdown per fixture, or summed with a note "2 games". The builder decides, as long as the parts still add up.

### 3. Backtest without leaked numbers
- **Archive comparison:** the archive's `ep_pre` is removed from the past-season comparison. Methods there are v1, v2 and last-5 average, on identical rows.
- **Choosing the source:** the source is the lowest-error method of those three (`choose_source` no longer returns `fpl_ep`), per horizon as now.
- **FPL's prediction, fairly:** it's compared only on current-season gameweeks where our collector saved `ep_next` before the deadline (GW8 onwards). Reported separately as "FPL's prediction, saved before kick-off", with the number of gameweeks and players, and labelled a small, growing sample.
- **New "Leak check" section** in `reports/backtest.md`: the three tests above, in plain English, with their numbers, recomputed by the backtest code rather than pasted in.

### 4. The story is rewritten
`README.md`, `docs/interview-explainer.md` and `docs/HANDOFF.md` change to the corrected result:
- **The leak** as a highlight: how it was noticed (the owner's "xP is just recent points"), proven three ways and fixed.
- **New result table:** from the clean backtest.
- **Interview Q&A updated:** "Did your model beat FPL?" now answers with the leak and the clean comparison.

## Goals, non-goals, anti-goals

**Goals:**
- xP is a real forecast with visible reasoning.
- The backtest can't be won by leaked data.
- The portfolio story is true.

**Non-goals (not this build):**
- Adding a bonus-points estimate. That's roadmap #6, because it needs its own honest test.
- Fixing stale daily data (roadmap #10).
- The other polish items in `docs/POLISH.md`.
- Changing v2's formula.

**Anti-goals:**
- Any number on the site still coming from FPL's form while labelled xP.
- A breakdown whose parts don't add up to the xP shown.
- The bonus gap hidden or in small grey text.
- Claims in the docs that the numbers don't support, including overstating one gameweek of clean data.
- Tuning v2 on the season it's tested on.

## Constraints
- Same stack and free hosting: Streamlit 1.66.0, SQLite views, plain JS page, no new dependencies.
- Every number comes from the SQL views and analysis code. The page only displays it.
- The reload guard in `app.py` must keep working. This build changes `fpl/*.py` and `fpl/sql/*.sql`, which is exactly what it handles.
- Must work at about 400px wide, in the same dark style.
- Keep all tests passing (290 now), and add tests for the new rules.
- Don't push in the hours before a gameweek deadline (next: GW9, 31 Oct 11:00 UTC).

## Builder's calls (Claude's, not the owner's)
- **Breakdown data:** the per-player parts come from v2's fixture view, with the input stats needed for the reasons added to it or to a sibling view, so the reasons can't drift from the maths.
- **Comparison strip data:** "FPL's number" is the latest saved `ep_next`, and "last-5 average" uses the same rule as the backtest's last5_avg.
- **Source still chosen by backtest:** the site keeps choosing its source from the backtest (v1, v2 or last-5), so a future clean result could pick v1. The breakdown only appears when the source is v2. Otherwise the panel shows which method is in use.
- **Old meta values and dead code:** any stored `forecast_source*` of `fpl_ep` is treated as v2 until the next backtest run rewrites it. The backtest re-runs as part of this build. The `fpl_ep` branch in `forecast.sql`'s source pick is removed, not left dead.
- **Clean FPL predictions only:**
  - `player_snapshot` is "latest collection wins", so a run after a deadline could overwrite a saved prediction with an already-updated one.
  - The current-season FPL comparison and the comparison strip only use a gameweek's `ep_next` if its `collected_at` is before that gameweek's deadline, taken from FPL's events (store the deadlines if they aren't already).
  - GW8 qualifies: saved 2026-10-23 10:50 UTC, deadline 17:30 UTC.
  - Gameweeks without a pre-deadline snapshot are left out and counted in the report.
- **Horizons:**
  - FPL is dropped from both archive tables, 1-gameweek and 3-gameweek.
  - The clean current-season FPL comparison is 1-gameweek only, because FPL only predicts one week ahead.
- **Missing v2 value:**
  - When v2 has no value for a player, the site falls back to v1 for that player.
  - The panel says "Not enough data for a breakdown; using the simpler model", with no breakdown.
  - This is rare: v2 already uses position averages when a player has under 180 minutes.
- **What the breakdown covers:**
  - It explains the next-gameweek xP only. "xP next 3" stays a plain number.
  - The headline number the breakdown sits under is always the v2 next-gameweek value, so the parts add up to it.
- **Double gameweek:** summed, with a "2 games" note. v2 already sums its fixtures' points, so the parts still add up.
- **Leak check data:**
  - It reads the archive's `ep_pre` directly. Kept in the database for evidence; just not scored.
  - Tests check the leak-check functions on small fixture data, not the real numbers.
- **Small samples:** the current-season FPL comparison is always shown with its sample size (gameweeks and players). Under 5 gameweeks it's labelled "too early to call", matching the existing current-season check's threshold. The docs call GW8 "an early sign from one gameweek", never proof.

## Left to the builder
- Exact wording of the reason lines, within the mockup's style.
- How the breakdown shows on a phone.
- How the current-season FPL comparison is stored and refreshed, and its minimum sample before reporting.
- Updating `analysis/data_dictionary.md` for any new view or column.

# Backtest report

Season: 2025-26. Scoring starts at GW6.
Gameweeks scored (33): 6-38. Rows scored: 13496 per method.

Each method predicts one gameweek ahead using only earlier information. Score is mean
absolute error (MAE) in FPL points per player-gameweek; lower is better. Only players
who were in a squad (minutes > 0 or start probability > 0) are scored.

**How forecast v2 was tested.** Its one fitted parameter (the attacking-points scale
factor `calib_att`, per position) was fitted on the 2024-25 season only
(`python -m fpl.fit`). It is scored here on 2025-26, a season it never saw, so
its result is out of sample. The v2 DefCon and clean-sheet parts have no fitted parameters.

**Why FPL's prediction is not in these tables.** The past-season archive's FPL prediction
(`ep_pre`) was recorded after each gameweek, so it had seen the result (see "Leak check"
below). It is no longer scored here, and rows no longer need it. That means many more
gameweeks are scored than in earlier reports, which only used the few gameweeks with an
archived FPL prediction, so the numbers are not comparable with those reports. FPL's
prediction is compared fairly in "FPL's prediction, saved before kick-off" below.

| Method | MAE | Rows |
|---|---|---|
| SQL model v1 (v_xp) | 1.929 | 13496 |
| Last-5 average | 1.986 | 13496 |
| Forecast v2 (v_xp2) | 1.867 | 13496 |

## 3-gameweek check

Transfer suggestions use points over the next 3 gameweeks, so this table scores
those numbers too. Each start gameweek below has two more gameweeks after it. Every
method predicts the player's points summed over the start gameweek and the next two,
using only gameweeks before the start:

- SQL model v1 / Forecast v2: the model's expected points for the 3 gameweeks added up.
- Last-5 average × fixtures: the last-5 average times his number of fixtures.

Start gameweeks (31): 6-36. Rows scored: 12656 per method.

| Method | MAE | Rows |
|---|---|---|
| SQL model v1 (v_xp), summed over 3 GWs | 4.498 | 12656 |
| Last-5 average × fixtures | 4.634 | 12656 |
| Forecast v2 (v_xp2), summed over 3 GWs | 4.235 | 12656 |

## What the app uses

The app picks its source for each horizon separately: the method with the lowest MAE on
identical rows. A tie goes to the SQL model, then forecast v2. FPL's number is never used.

- **Next gameweek:** forecast v2 (built from xG, xA, clean-sheet chance and DefCon chance). Forecast v2 (v_xp2) had the lowest MAE (1.867), below the next best (SQL model v1 (v_xp), 1.929).
- **Next 3 gameweeks:** forecast v2 (built from xG, xA, clean-sheet chance and DefCon chance). Forecast v2 (v_xp2) had the lowest MAE (4.235), below the next best (SQL model v1 (v_xp), 4.498).

DefCon chance, clean-sheet chance, weaknesses and the last-6 stats are descriptive and
always shown, whichever source is chosen.

## Leak check

Was the archive's FPL prediction made before the gameweek, or recorded after it? Two tests,
recomputed from the database on every run. Only gameweeks the player played are counted,
and a double gameweek's points are added up.

**2024-25.** Over 9706 player-gameweeks, FPL's archived prediction was closer to the player's points average over the 4 gameweeks *including* that week (error 0.655) than to the average over the 4 gameweeks *before* it (error 1.018). A prediction made before kick-off can only know the weeks before. When a player scored 12 or more (184 times), FPL's number for that week averaged 7.19, against 4.19 the week before: it rose with the result. Both point to a number recorded after the gameweek.

**2025-26.** Over 2873 player-gameweeks, FPL's archived prediction was closer to the player's points average over the 4 gameweeks *including* that week (error 0.594) than to the average over the 4 gameweeks *before* it (error 1.096). A prediction made before kick-off can only know the weeks before. When a player scored 12 or more (38 times), FPL's number for that week averaged 7.46, against 3.64 the week before: it rose with the result. Both point to a number recorded after the gameweek.

## FPL's prediction, saved before kick-off

Season 2026-27, one gameweek ahead. FPL's prediction is scored only where our
collector saved it before that gameweek's deadline, so it could not have seen the result.
Every method is scored on the same rows.

Gameweeks (1): 8. Players: 427. Rows: 427 per method.
Gameweeks left out, with no FPL prediction saved before the deadline: 1-7.

| Method | MAE | Rows |
|---|---|---|
| SQL model v1 (v_xp) | 1.947 | 427 |
| Forecast v2 (v_xp2) | 1.832 | 427 |
| Last-5 average | 2.009 | 427 |
| FPL's prediction, saved before kick-off | 2.057 | 427 |

Verdict: too early to call. This is a small, growing sample: under 5 gameweeks, so read it as an early sign, not proof.

## Caveats

- **What was fitted where:** v1's fixture-difficulty (FDR) multipliers and v2's `calib_att`
  were both fitted on 2024-25 and are scored here on 2025-26, a different season, so
  both results are out of sample.
- A player's first appearance has no last-5 history, so those rows are dropped for all methods.
- Double gameweeks: actual points and predictions are summed over both fixtures.
- The comparison covers only the gameweeks listed above, not the whole season.

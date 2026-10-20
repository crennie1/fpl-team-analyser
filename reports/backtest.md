# Backtest report

Season: 2025-26. Scoring starts at GW6.
Gameweeks scored (6): 6, 8-9, 24, 29, 38. Rows scored: 2520 per method.

Each method predicts one gameweek ahead using only earlier information. Score is mean
absolute error (MAE) in FPL points per player-gameweek; lower is better. Only players
who were in a squad (minutes > 0 or start probability > 0) are scored.

**How forecast v2 was tested.** Its one fitted parameter (the attacking-points scale
factor `calib_att`, per position) was fitted on the 2024-25 season only
(`python -m fpl.fit`). It is scored here on 2025-26, a season it never saw, so
its result is out of sample. The v2 DefCon and clean-sheet parts have no fitted parameters.

The past-season archive does not contain FPL's own predictions (`ep_pre`) for the other
gameweeks (listed as zero for every player, so stored as missing). Those gameweeks are
left out for all four methods, so every method is judged on exactly the same rows.
Gameweeks with no FPL prediction (between GW6 and GW38): 7, 10-23, 25-28, 30-37.

| Method | MAE | Rows |
|---|---|---|
| SQL model v1 (v_xp) | 1.876 | 2520 |
| Last-5 average | 1.927 | 2520 |
| FPL ep_pre | 1.371 | 2520 |
| Forecast v2 (v_xp2) | 1.819 | 2520 |

## 3-gameweek check

Transfer suggestions use points over the next 3 gameweeks, so this table scores
those numbers too. Each start gameweek below has an FPL prediction and two more
gameweeks after it. Every method predicts the player's points summed over the
start gameweek and the next two, using only gameweeks before the start:

- SQL model v1 / Forecast v2: the model's expected points for the 3 gameweeks added up.
- Last-5 average × fixtures: the last-5 average times his number of fixtures.
- FPL ep_pre, scaled: FPL's prediction for the start gameweek, scaled by how many
  fixtures he has over the 3 gameweeks and how hard they are (what the app does).

Start gameweeks (5): 6, 8-9, 24, 29. Rows scored: 2093 per method.
This sample is small, so read it as a sanity check as well as a decision input.

| Method | MAE | Rows |
|---|---|---|
| SQL model v1 (v_xp), summed over 3 GWs | 4.242 | 2093 |
| Last-5 average × fixtures | 4.331 | 2093 |
| FPL ep_pre, scaled over 3 GWs (R20) | 3.635 | 2093 |
| Forecast v2 (v_xp2), summed over 3 GWs | 4.047 | 2093 |

## What the app uses

The app picks its source for each horizon separately. Forecast v2 is used for a horizon
only if its MAE is strictly lower than every other method's on identical rows; a tie
stays with the existing source.

- **Next gameweek:** FPL's own prediction (ep). Forecast v2 (1.819) was not strictly better than FPL ep_pre (1.371), so v2 is not used here.
- **Next 3 gameweeks:** FPL's own prediction (ep), scaled by how many fixtures the player has and how hard they are. Forecast v2 (4.047) was not strictly better than FPL ep_pre (3.635), so v2 is not used here.

DefCon chance, clean-sheet chance, weaknesses and the last-6 stats are descriptive and
always shown, whichever source is chosen.

## Current season check

Does the choice above hold on the live season?

Pending until enough gameweeks (about GW12): the current season has fewer than 5 finished gameweeks with an FPL prediction so far.

## Caveats

- **What was fitted where:** v1's fixture-difficulty (FDR) multipliers and v2's `calib_att`
  were both fitted on 2024-25 and are scored here on 2025-26, a different season, so
  both results are out of sample. v1's MAE moved slightly from earlier reports (1.880 to 1.876,
  and FPL's 3-GW 3.630 to 3.635) because the fixture-difficulty multipliers are now fitted on
  the earlier season.
- A player's first appearance has no last-5 history, so those rows are dropped for all methods.
- Double gameweeks: actual points and predictions are summed over both fixtures.
- The comparison covers only the gameweeks listed above, not the whole season.

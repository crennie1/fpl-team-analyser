# Backtest report

Season: 2025-26. Scoring starts at GW6.
Gameweeks scored (6): 6, 8-9, 24, 29, 38. Rows scored: 2520 per method.

Each method predicts one gameweek ahead using only earlier information. Score is mean
absolute error (MAE) in FPL points per player-gameweek; lower is better. Only players
who were in a squad (minutes > 0 or start probability > 0) are scored.

The past-season archive does not contain FPL's own predictions (`ep_pre`) for the other
gameweeks (listed as zero for every player, so stored as missing). Those gameweeks are
left out for all three methods, so every method is judged on exactly the same rows.
Gameweeks with no FPL prediction (between GW6 and GW38): 7, 10-23, 25-28, 30-37.

| Method | MAE | Rows |
|---|---|---|
| SQL model (v_xp) | 1.880 | 2520 |
| Last-5 average | 1.927 | 2520 |
| FPL ep_pre | 1.371 | 2520 |

Winner: **FPL ep_pre**. The model did not beat the better baseline.

What this means for the app: FPL's own prediction was more accurate on these gameweeks, so the app uses FPL's own prediction for next-gameweek points. The 3-gameweek numbers are that same prediction, scaled by how many fixtures the player has and how hard they are.

## 3-gameweek check

Transfer suggestions use points over the next 3 gameweeks, so this table scores
those numbers too. Each start gameweek below has an FPL prediction and two more
gameweeks after it. Every method predicts the player's points summed over the
start gameweek and the next two, using only gameweeks before the start:

- SQL model: the model's expected points for the 3 gameweeks added up.
- Last-5 average × fixtures: the last-5 average times his number of fixtures.
- FPL ep_pre, scaled: FPL's prediction for the start gameweek, scaled by how many
  fixtures he has over the 3 gameweeks and how hard they are (what the app does).

Start gameweeks (5): 6, 8-9, 24, 29. Rows scored: 2093 per method.
This sample is small, so read it as a sanity check, not a verdict.

| Method | MAE | Rows |
|---|---|---|
| SQL model (v_xp), summed over 3 GWs | 4.247 | 2093 |
| Last-5 average × fixtures | 4.331 | 2093 |
| FPL ep_pre, scaled over 3 GWs (R20) | 3.630 | 2093 |

The forecast source is decided by the one-gameweek table above, not by this one.

## Caveats

- **In-sample caveat:** the fixture-difficulty (FDR) multipliers in the model were fit
  on this same season (2025-26), so the model's MAE here is slightly
  optimistic. The baselines have no such advantage.
- A player's first appearance has no last-5 history, so those rows are dropped for all methods.
- Double gameweeks: actual points and predictions are summed over both fixtures.
- The comparison covers only the gameweeks listed above, not the whole season.

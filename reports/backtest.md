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

What this means for the app: FPL's own prediction was more accurate on these gameweeks, so the app uses FPL's own prediction for next-gameweek points and our model for the 3-gameweek suggestions.

## Caveats

- **In-sample caveat:** the fixture-difficulty (FDR) multipliers in the model were fit
  on this same season (2025-26), so the model's MAE here is slightly
  optimistic. The baselines have no such advantage.
- A player's first appearance has no last-5 history, so those rows are dropped for all methods.
- Double gameweeks: actual points and predictions are summed over both fixtures.
- The comparison covers only the gameweeks listed above, not the whole season.

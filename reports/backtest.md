# Backtest report

Season: 2025-26, gameweeks 6 to 38 (scoring starts at GW6).

Each method predicts one gameweek ahead using only earlier information. Score is mean
absolute error (MAE) in FPL points per player-gameweek; lower is better. Only players
who were in a squad (minutes > 0 or start probability > 0) are scored, and only rows
where all three methods have a prediction, so every method is judged on the same rows.

| Method | MAE | Rows |
|---|---|---|
| SQL model (v_xp) | 1.930 | 13496 |
| Last-5 average | 1.986 | 13496 |
| FPL ep_pre | 2.075 | 13496 |

Winner: **SQL model (v_xp)**. The model beat the better baseline.

What this means for the app: The app will use our SQL model for expected points, because it predicted better than both baselines.

## Caveats

- **In-sample caveat:** the fixture-difficulty (FDR) multipliers in the model were fit
  on this same season (2025-26), so the model's MAE here is slightly
  optimistic. The baselines have no such advantage.
- A player's first appearance has no last-5 history, so those rows are dropped for all methods.
- Double gameweeks: actual points and predictions are summed over both fixtures.

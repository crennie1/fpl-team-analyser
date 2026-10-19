# Data dictionary

This file describes every table and view in `data/fpl.db`, in plain English.

Two kinds of things live in the database:

- **Tables** hold stored data (rows that were collected or saved).
- **Views** are saved queries with a name. You `SELECT` from a view like a table, but its rows are worked out fresh from other tables each time. Most of the forecast is built from views.

## Conventions

- **Money** is stored in tenths of a million pounds, as FPL does. `now_cost` of 105 means 10.5m. Divide by 10 to show pounds.
- **Season** is text like `2025-26`. The database holds two:
  - `2025-26` is the past season. It is complete and is used for the backtest.
  - `2026-27` is the current season. It is loaded gameweek by gameweek.
- **GW** means gameweek (FPL's round of matches, numbered 1 to 38).
- **FDR** means Fixture Difficulty Rating. FPL's own score from 1 (easy) to 5 (hard) for how tough a match is for one side.
- **pts/90** means points per 90 minutes played. It lets you compare players with different playing time.
- **MAE** means mean absolute error: the average size of the gap between a prediction and the real points, ignoring whether it was too high or too low. Lower is better.
- **Percentile** means "what share of the reference squads you beat". 70 means you beat 70 percent of them.
- **Positions** are `GK`, `DEF`, `MID`, `FWD`.
- A **double gameweek** gives a player two fixtures in one GW (two rows in `player_gw`). A **blank gameweek** gives none.

## Tables

### `meta`
Small settings the code reads. One row per setting.

| Column | Meaning |
|---|---|
| `key` | Setting name. |
| `value` | Setting value, as text. |

Keys in use:

| Key | Meaning |
|---|---|
| `current_season` | The live season (`2026-27`). |
| `backtest_season` | The past season used to test and fit the model (`2025-26`). |
| `next_gw` | The upcoming gameweek number. |
| `last_collected` | When the data was last refreshed (UTC time). The app warns if this is over 36 hours old. |
| `forecast_source` | Which forecast the app shows for next week: `fpl_ep` (FPL's own number) or `model` (ours). Chosen by the backtest. Currently `fpl_ep`. |

### `team`
Premier League clubs, per season.

| Column | Meaning |
|---|---|
| `season` | Season. |
| `team_id` | FPL's club number. It can change between seasons. |
| `name` | Full club name. |
| `short_name` | Three-letter code, for example `ARS`. |

### `player`
Every player registered in a season.

| Column | Meaning |
|---|---|
| `season` | Season. |
| `player_id` | FPL's player number (also called `element`). |
| `web_name` | The name FPL shows on screen. |
| `team_id` | The player's club now (join to `team`). |
| `position` | `GK`, `DEF`, `MID` or `FWD`. |

### `player_snapshot`
What FPL said about each player at the time of a data collection. Latest collection wins (see the view `v_latest_snapshot`).

| Column | Meaning |
|---|---|
| `season` | Season. |
| `gw` | The upcoming gameweek when the snapshot was taken. |
| `player_id` | Player. |
| `collected_at` | When the snapshot was taken (UTC). |
| `status` | `a` available, `d` doubtful, `i` injured, `s` suspended, `u` unavailable. |
| `chance_next` | FPL's percent chance (0 to 100) that he plays next round. Empty (NULL) when FPL gives none, which counts as "not flagged". |
| `ep_next` | FPL's own expected points for next gameweek. |
| `now_cost` | Price in tenths of a million (105 = 10.5m). |
| `selected_by_percent` | Percent of all FPL managers who own him. |
| `news` | FPL's injury or availability text. Empty when there is none. |

### `fixture`
One row per match.

| Column | Meaning |
|---|---|
| `season` | Season. |
| `fixture_id` | FPL's match number. |
| `gw` | Gameweek the match is in. Empty if not yet scheduled. |
| `team_h` | Home club (`team_id`). |
| `team_a` | Away club (`team_id`). |
| `team_h_difficulty` | FDR for the home side. |
| `team_a_difficulty` | FDR for the away side. |
| `finished` | 1 if played, 0 if not. |

### `player_gw`
What a player did in one match. A player in a double gameweek has two rows for that GW.

| Column | Meaning |
|---|---|
| `season` | Season. |
| `gw` | Gameweek. |
| `player_id` | Player. |
| `fixture_id` | The match. |
| `minutes` | Minutes played. |
| `total_points` | FPL points scored in that match. |
| `was_home` | 1 if his team was at home, else 0. |
| `opponent_team` | The opposing club (`team_id`). |
| `fdr` | Difficulty of the match **from the player's side**. |
| `ep_pre` | FPL's expected-points prediction made before the match. Only the past season has this. Empty (NULL) when missing. |

About `ep_pre`: in the past-season archive some gameweeks list 0 for every player. A prediction of zero for everyone is not real, it is missing data. So those whole gameweeks are stored as NULL. A single player with 0 in a gameweek that has other predictions stays 0, because that is a real prediction.

### `squad_pick`
The players in a squad. A squad is 15 players.

| Column | Meaning |
|---|---|
| `squad_id` | Whose squad. `user` is the person using the app. `ref:<entry_id>` is one of the reference squads (see `reference_squad`). |
| `player_id` | Player. |
| `slot` | Place in the squad, 1 to 15. Slots 1 to 11 start, 12 to 15 are the bench. |
| `is_starter` | 1 if he starts, 0 if on the bench. |
| `is_captain` | 1 for the captain. His points count double. |

### `reference_squad`
The "average manager" sample. These are the squads that grades are measured against.

**Reference population:** a random sample of up to 500 real public FPL teams, drawn by picking random team numbers from 1 up to the total number of players. Each is the team's picks for the most recent finished gameweek. The sample is replaced every Tuesday. Because it is random, it is mostly ordinary managers, not top ranked ones.

| Column | Meaning |
|---|---|
| `season` | Season. |
| `gw` | Gameweek the picks were taken from. |
| `squad_id` | `ref:<entry_id>`, links to `squad_pick`. |
| `entry_id` | FPL's team number for that manager. |

### `xp_next_cache`
A saved copy of the view `v_xp_next`, taken after each data load. It is a table (not a view) because the full forecast chain is too slow to rerun every time someone edits a squad in the app. If you edit data by hand, the copy goes out of date until the next collection refreshes it. The columns are the same as `v_xp_next`.

| Column | Meaning |
|---|---|
| `player_id` | Player. |
| `xp_next` | Expected points next gameweek. |
| `xp_next3` | Expected points over the next 3 gameweeks. |
| `start_prob` | Chance he starts, 0 to 1. |
| `xp_source` | `fpl_ep` or `model`: where the numbers came from. |

## The forecast: how expected points are worked out

For one fixture:

```
expected points = start_prob x pts_per_90 x FDR multiplier
```

- **start_prob** (chance he starts, 0 to 1) = minutes played in the last 5 loaded gameweeks, divided by 450, capped at 1. For the upcoming gameweek only, it is then multiplied by FPL's `chance_next` / 100 when FPL gives one.
- **pts_per_90** = his total points per 90 minutes over the last 6 loaded gameweeks. This needs at least 180 minutes. Below that, the average pts/90 for his position that season is used instead.
- **FDR multiplier** = (average pts/90 for that position at that FDR) divided by (average pts/90 for that position overall). It is worked out once from the past season (`backtest_season`) and applied to every season. An easy match gives a number above 1 and a hard match gives a number below 1.

Form windows count **back from the last loaded gameweek**, by gameweek number. A gameweek still in progress is never counted as zero minutes. The "last 5" minutes window is `last_gw - 4` to `last_gw`, and the "last 6" points window is `last_gw - 5` to `last_gw`.

A blank gameweek gives 0. A double gameweek adds both fixtures.

**What the app shows.** When `meta.forecast_source` is `fpl_ep`:

- `xp_next` is FPL's own `ep_next`.
- `xp_next3` is `ep_next` scaled by the fixtures: `ep_next x (sum of FDR multipliers over his fixtures in the next 3 gameweeks) / (sum of FDR multipliers over his fixtures in the next gameweek)`.
- If he has no fixture next gameweek, or `ep_next` is empty, both numbers fall back to the model.

When `forecast_source` is `model`, both numbers come from the model. `xp_source` says which was used.

**Honest caveat.** The FDR multipliers were fitted on the same past season that the backtest scores, so the model's backtest error is a little too good. FPL's own prediction and the last-5 average have no such advantage. See `reports/backtest.md`.

## Views

Views build on each other. The chain is:

```
v_as_of_grid, v_latest_snapshot, v_fdr_multiplier
   -> v_last_gw -> v_position_avg -> v_player_form
   -> v_target_fixture -> v_xp_fixture -> v_xp -> v_xp_next
                                                    |
                                          (copied into xp_next_cache)
                                                    |
v_squad_pick_xp + v_squad_fixtures -> v_squad_metrics -> v_squad_area_value -> v_squad_grades
```

"As of gameweek N" always means: use only gameweeks **before** N, so a forecast never sees the future.

### `v_as_of_grid`
Every (season, gameweek) that can be forecast from. One row per gameweek that has fixtures.

| Column | Meaning |
|---|---|
| `season` | Season. |
| `as_of_gw` | The gameweek we forecast from. |

### `v_latest_snapshot`
The newest `player_snapshot` row per player, current season only. Same columns as `player_snapshot`.

### `v_fdr_multiplier`
How much each difficulty rating shifts a player's output (the FDR multiplier above).

| Column | Meaning |
|---|---|
| `season` | The backtest season it was fitted on. |
| `position` | `GK`, `DEF`, `MID` or `FWD`. |
| `fdr` | Difficulty rating, 1 to 5. |
| `mult` | The multiplier. Above 1 means better than average. Only matches where the player played count. |

### `v_last_gw`
The last loaded gameweek before each `as_of_gw`.

| Column | Meaning |
|---|---|
| `season` | Season. |
| `as_of_gw` | Forecast-from gameweek. |
| `last_gw` | Latest gameweek that has player data before it. |

### `v_position_avg`
Fallback pts/90 for each position, using only gameweeks before `as_of_gw`.

| Column | Meaning |
|---|---|
| `season` | Season. |
| `position` | Position. |
| `as_of_gw` | Forecast-from gameweek. |
| `pts_per_90` | Average points per 90 minutes for that position. Empty at GW1 (no history). |

### `v_player_form`
Each player's form as at each gameweek.

| Column | Meaning |
|---|---|
| `season` | Season. |
| `player_id` | Player. |
| `as_of_gw` | Forecast-from gameweek. |
| `pts_per_90` | His own rate over the last 6 gameweeks, or the position average if he has under 180 minutes. |
| `start_prob_base` | Chance he starts, before the injury-news adjustment. |
| `chance_factor` | FPL's `chance_next` / 100 for the upcoming gameweek, otherwise 1. |
| `start_prob` | `start_prob_base x chance_factor`. Used for the upcoming gameweek itself. |
| `minutes_last5` | Minutes in the last 5 loaded gameweeks (max 450). |

### `v_target_fixture`
The fixtures a player has in a target gameweek, with the difficulty from his side. If he already has `player_gw` rows for that gameweek, those are used (so the club is right even after a mid-season move). Otherwise the `fixture` table and his current club are used.

| Column | Meaning |
|---|---|
| `season` | Season. |
| `player_id` | Player. |
| `gw` | Target gameweek. |
| `fixture_id` | The match. |
| `fdr` | Difficulty from his side. |

### `v_xp_fixture`
Expected points per player, per fixture, for the target gameweeks `as_of_gw` to `as_of_gw + 2`. A gameweek with no fixture gets one row with `fixture_id` empty and `xp` 0.

| Column | Meaning |
|---|---|
| `season` | Season. |
| `player_id` | Player. |
| `as_of_gw` | Forecast-from gameweek. |
| `gw` | Target gameweek. |
| `fixture_id` | The match, empty for a blank. |
| `xp` | Model expected points for that fixture. The injury-news adjustment applies to the upcoming gameweek only. |
| `mult` | The fixture's FDR multiplier alone (0 for a blank). Used to scale FPL's number. |

### `v_xp`
Model expected points per player per target gameweek. A blank gives 0 and a double sums both fixtures.

| Column | Meaning |
|---|---|
| `season` | Season. |
| `player_id` | Player. |
| `gw` | Target gameweek. |
| `as_of_gw` | Forecast-from gameweek. |
| `xp_model` | Model expected points. |

### `v_xp_next`
What the app shows: current season, upcoming gameweek. See "What the app shows" above. This is the view that is copied into `xp_next_cache`.

| Column | Meaning |
|---|---|
| `player_id` | Player. |
| `xp_next` | Expected points next gameweek. |
| `xp_next3` | Expected points over the next 3 gameweeks. |
| `start_prob` | Chance he starts, 0 to 1. |
| `xp_source` | `fpl_ep` or `model`. |

### `v_squad_pick_xp`
Each squad pick with the player's position, expected points and risk flag.

| Column | Meaning |
|---|---|
| `squad_id` | Squad. |
| `player_id` | Player. |
| `slot` | Squad place, 1 to 15. |
| `is_starter` | 1 if he starts. |
| `is_captain` | 1 for the captain. |
| `position` | His position. |
| `team_id` | His club. |
| `xp_next` | Expected points next gameweek (0 if missing). |
| `is_flagged` | 1 if he is a risk: status is not `a`, or `chance_next` is under 75, or `start_prob` is under 0.6. |

### `v_squad_fixtures`
How hard each squad's run of fixtures is.

| Column | Meaning |
|---|---|
| `squad_id` | Squad. |
| `fixtures` | Average FDR of the starters' fixtures from the next gameweek to 4 gameweeks later (5 gameweeks). Lower is easier. |

### `v_squad_metrics`
One row per squad with seven numbers.

| Column | Meaning |
|---|---|
| `squad_id` | Squad. |
| `attack` | Sum of `xp_next` over starting forwards. |
| `midfield` | Sum of `xp_next` over starting midfielders. |
| `defence` | Sum of `xp_next` over starting defenders and the starting goalkeeper. |
| `fixtures` | Average fixture difficulty (see above). Lower is better. |
| `risk` | Share of the starters' expected points that come from flagged players. Lower is better. |
| `bench` | Sum of `xp_next` over the bench. |
| `projected` | Starters' `xp_next` plus the captain's `xp_next` again (captain counts double). No automatic substitutions. |

### `v_squad_area_value`
The same seven numbers in "long" form: one row per squad and area. This lets every area be graded the same way.

| Column | Meaning |
|---|---|
| `squad_id` | Squad. |
| `area` | `attack`, `midfield`, `defence`, `fixtures`, `risk`, `bench` or `projected`. |
| `higher_is_better` | 1 for most areas, 0 for `fixtures` and `risk`. |
| `value` | The number for that squad and area. |

### `v_squad_grades`
Each non-reference squad compared with the reference squads of the current season.

**Percentile rule:** `pct = 100 x (reference squads strictly worse than you + half of those equal to you) / (number of reference squads)`. "Worse" means lower for attack, midfield, defence, bench and projected, and higher for fixtures and risk. With no reference squads, there are no grades.

| Column | Meaning |
|---|---|
| `squad_id` | Squad being graded (for example `user`). |
| `area` | The area graded. |
| `value` | The squad's number for that area. |
| `pct` | Percentile, 0 to 100. |
| `grade` | Letter from the percentile: A is 80 or more, B is 60 to under 80, C is 40 to under 60, D is 20 to under 40, E is under 20. |

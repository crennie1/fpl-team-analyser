# FPL Team Analyser

Type in your Fantasy Premier League team ID and see how your squad grades against the average manager, plus the single transfers that would add the most expected points.

> **Screenshot:** _add a screenshot of the app here after it is deployed._
> Suggested: the grades table and the pitch view. Save it as `docs/screenshot.png` and replace this note with `![App screenshot](docs/screenshot.png)`.

**Live app:** _add the Streamlit link here after deploying._

## What v2 adds

- **Richer data:** expected goals (xG), expected assists (xA), clean sheets, DefCon (FPL's defensive-contribution bonus) and set-piece takers, stored for every player and gameweek.
- **Forecast v2:** an explainable expected-points model built from those stats (formula in `fpl/sql/forecast_v2.sql`). Its one fitted setting is fitted on 2024-25 and scored on 2025-26. It had the lowest error of the methods tested, so every xP on the site now comes from v2. Click a player to see his xP split into its parts (playing, goals and assists, clean sheet, DefCon), with a clear warning that bonus points are not included.
- **A leak found and fixed:** an earlier backtest said FPL's own prediction beat my models. It had been recorded after the matches, so it had seen the results. The backtest no longer uses it, and FPL's prediction is now only compared on numbers saved before kick-off. Details below.
- **Opponent weaknesses:** points each club concedes to goalkeepers, defenders, midfielders and forwards over the last 6 gameweeks.
- **New team view:** dark player cards with drawn club kits and a click-for-stats panel that also works on a phone.

New to the project? Read the plain-English walkthrough in [`docs/interview-explainer.md`](docs/interview-explainer.md).

## How it works

Plain English first. Jargon is explained as it appears.

### 1. Data

- **Official FPL API** (`https://fantasy.premierleague.com/api/`): players, fixtures, prices, injury news, and what each player scored in each match. It is free and public.
- **Past-season archive** (the public `vaastav/Fantasy-Premier-League` project on GitHub): last season's results, used to test the forecast honestly.
- Everything is stored in one **SQLite** file, `data/fpl.db`. SQLite is a database that lives in a single file, so there is no server to run or pay for.
- A **GitHub Action** (a scheduled job on GitHub, free) refreshes the data every day. It saves the new file back to the repo only when a gameweek has finished, in the 48 hours before a deadline, or on Tuesdays (when the reference sample is refreshed), so the repo does not grow by a full copy of the database every day.
- The app never shows fake or stale data quietly. If the FPL site is down it says so, and it warns if the data is over 36 hours old.

### 2. Forecast

Expected points for one match are:

```
expected points = chance he starts  x  his points per 90 minutes  x  fixture difficulty multiplier
```

- **Chance he starts:** how many of the last 5 gameweeks' minutes he played (adjusted by FPL's injury news for next week).
- **Points per 90 minutes:** his own rate over the last 6 gameweeks, or the position average if he has played too little.
- **Fixture difficulty multiplier:** FDR is FPL's 1-to-5 difficulty rating for a match. The multiplier says how much easier or harder matches change a player's points, learned from last season.

The forecast is written as a chain of SQL **views** (saved, named queries) in `fpl/sql/forecast.sql`. Python only runs them.

**Which forecast the app uses.** I backtested (tested on past data, looking only at what was known beforehand) three methods on the 2025-26 season: the SQL model (v1), forecast v2, and a simple last-5-gameweeks average. The score is **MAE** (mean absolute error: the average gap between prediction and real points; lower is better). All three are scored on the same 13496 player-gameweeks (gameweeks 6-38). The app uses whichever method has the lowest error, separately for next gameweek and for the next 3 gameweeks (the numbers behind the transfer suggestions). FPL's own number is never used.

| Method | Next gameweek | Next 3 gameweeks |
|---|---|---|
| Forecast v2 | **1.867** | **4.235** |
| SQL model v1 | 1.929 | 4.498 |
| Last-5 average | 1.986 | 4.634 |

v2 won both, so `meta.forecast_source_1gw` and `meta.forecast_source_3gw` are both `v2`.

**Forecast v2.** The v2 model (`fpl/sql/forecast_v2.sql`) adds up four parts: appearance points, goals and assists (from xG and xA, adjusted for the opponent), clean-sheet points and DefCon points. Its one fitted setting is learned on 2024-25 and scored on 2025-26, a season it never saw. It does not include bonus points, so the player panel says so plainly.

**Why FPL's prediction is not in that table.** Earlier versions of this app showed FPL's own "expected points", because an earlier backtest said it beat my models. The past-season archive's FPL prediction turned out to be recorded after each gameweek, so it had seen the result. The backtest report now has a **Leak check** section that proves this from the data, and compares FPL's prediction fairly only on numbers our own collector saved before kick-off. So far that is one gameweek (GW8 of 2026-27), where v2 had the lowest error: an early sign from one gameweek, not proof. The report labels it "too early to call" until 5 gameweeks are in.

**Results so far:** see [`reports/backtest.md`](reports/backtest.md) for the full scores, the leak check, the fair comparison with FPL, and the caveats.

### 3. Grades

The app shows six grades: attack, midfield, defence, fixtures, risk and bench (defined in `analysis/data_dictionary.md`). Projected points are shown as a number next to the average manager's, not as a grade. Each grade is compared with a random sample of about 500 real FPL squads (the reference squads, refreshed weekly).

A **percentile** is the share of those squads you beat. A grade comes from it: A is the top 20 percent (80 or higher), B is 60 to 80, C is 40 to 60, D is 20 to 40, E is the bottom 20. For fixtures and risk, lower is better, so the comparison flips.

### Suggestions

The app shows the best single moves. Each move is checked on its own against your current squad (so do not assume you can make both). It respects your budget, the 3-players-per-club limit, and counts the points cost of an extra transfer.

You can also plan swaps straight from the team sheet. Click a player to see a Replace list with 👍 marks on the picks that look worth it, try a swap, and the sheet shows your plan next to your real team (points, grades and money before and after). You can plan a move that costs more than your bank allows; it just shows a warning that you are over budget.

## How to run locally

You need Python 3.11 or newer.

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Then open the address Streamlit prints (usually http://localhost:8501).

Run the tests with:

```
.venv/bin/pytest -v
```

The tests never use the internet. They use recorded sample data in `tests/fixtures/`.

## Explore the data yourself

The `analysis/` folder is a SQL workspace: a data dictionary, three worked example queries and three open questions. Start with [`analysis/README.md`](analysis/README.md).

## What I found

> **Owner: write this section yourself.** Nothing is filled in on purpose.
>
> Prompts to get you started:
> - How did you notice that FPL's archived prediction had seen the results, and what changed once it was removed?
> - What did you find in `analysis/starter_queries.sql`? Which result surprised you?
> - What did you learn about fixtures versus form?
> - What would you tell an FPL manager based on the data?

## What I'd do differently

> **Owner: write this section yourself.** Nothing is filled in on purpose.
>
> Prompts to get you started:
> - What data is missing that would make the forecast better (for example, goals, expected goals, set-piece duties)?
> - What are the weak points in the test (sample size, in-sample fitting)?
> - If you started again, what would you build or measure first?
> - What would you do with more time?

## Deploy

These steps need your own accounts, so you do them. Ask for help with any step.

1. **Create a public GitHub repo and push.** Sign in to GitHub, create a new public repository, then push this project to it.
2. **Enable Actions.** In the repo, open the **Actions** tab and enable workflows. This turns on the daily data refresh (`.github/workflows/collect.yml`).
3. **Deploy the app.** Go to https://share.streamlit.io and sign in with GitHub. Choose **New app**, pick this repo and `app.py`, then click **Deploy**.

Two things to know:

- **The scheduled refresh only runs from the default branch.** GitHub ignores the schedule on any other branch. This project was built on a branch called `build`, so merge that work into `main` **before** step 2. Otherwise the daily refresh will not start.
- **Optional: link the footer to the backtest report.** In the Streamlit app settings, open **Secrets** and add a line like this (use your own repo address):

  ```
  REPO_URL = "https://github.com/YOUR-NAME/YOUR-REPO"
  ```

  The footer then links to `reports/backtest.md`. Without it, the footer shows plain text.

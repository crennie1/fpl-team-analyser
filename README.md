# FPL Team Analyser

Type in your Fantasy Premier League team ID and see how your squad grades against the average manager, plus the single transfers that would add the most expected points.

> **Screenshot:** _add a screenshot of the app here after it is deployed._
> Suggested: the grades table and the pitch view. Save it as `docs/screenshot.png` and replace this note with `![App screenshot](docs/screenshot.png)`.

**Live app:** _add the Streamlit link here after deploying._

## What v2 adds

- **Richer data:** expected goals (xG), expected assists (xA), clean sheets, DefCon (FPL's defensive-contribution bonus) and set-piece takers, stored for every player and gameweek.
- **Forecast v2:** an explainable expected-points model built from those stats (formula in `fpl/sql/forecast_v2.sql`). Its one fitted setting is fitted on 2024-25 and scored on 2025-26. It beat my v1 model and the simple baseline but not FPL's own prediction, so the app still uses FPL's numbers and shows v2's DefCon chance, clean-sheet chance and opponent weaknesses as information.
- **Opponent weaknesses:** points each club concedes to goalkeepers, defenders, midfielders and forwards over the last 6 gameweeks.
- **New team view:** dark player cards with drawn club kits and a click-for-stats panel that also works on a phone.

New to the project? Read the plain-English walkthrough in [`docs/interview-explainer.md`](docs/interview-explainer.md).

## How it works

Plain English first. Jargon is explained as it appears.

### 1. Data

- **Official FPL API** (`https://fantasy.premierleague.com/api/`): players, fixtures, prices, injury news, and what each player scored in each match. It is free and public.
- **Past-season archive** (the public `vaastav/Fantasy-Premier-League` project on GitHub): last season's results, used to test the forecast honestly.
- Everything is stored in one **SQLite** file, `data/fpl.db`. SQLite is a database that lives in a single file, so there is no server to run or pay for.
- A **GitHub Action** (a scheduled job on GitHub, free) refreshes the data every day and saves the new file back to the repo.
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

**Which forecast the app uses.** I backtested (tested on past data, looking only at what was known beforehand) three methods on last season: the SQL model, a simple last-5-gameweeks average, and FPL's own prediction. The score is **MAE** (mean absolute error: the average gap between prediction and real points; lower is better). The app uses whichever source won. At the moment `meta.forecast_source_1gw` and `meta.forecast_source_3gw` are both `fpl_ep`, meaning FPL's own prediction is used for next gameweek, and the 3-gameweek number is that prediction scaled by how many and how hard the next three fixtures are. A second table checks the 3-gameweek numbers behind the transfer suggestions the same way (it does not change which source is used). The full numbers and caveats are in the backtest report.

**Forecast v2.** The v2 model (`fpl/sql/forecast_v2.sql`) is backtested the same way, with its fitted setting learned on 2024-25 and scored on 2025-26. The app uses v2 for a horizon only if its error is strictly lower than every other method's on identical rows. It was not, so `meta.forecast_source_1gw` and `meta.forecast_source_3gw` are both `fpl_ep`.

**Results so far:** see [`reports/backtest.md`](reports/backtest.md) for the backtest scores, the gameweeks covered, and the caveats (including a current-season check that is still pending).

### 3. Grades

The app shows six grades: attack, midfield, defence, fixtures, risk and bench (defined in `analysis/data_dictionary.md`). Projected points are shown as a number next to the average manager's, not as a grade. Each grade is compared with a random sample of about 500 real FPL squads (the reference squads, refreshed weekly).

A **percentile** is the share of those squads you beat. A grade comes from it: A is the top 20 percent (80 or higher), B is 60 to 80, C is 40 to 60, D is 20 to 40, E is the bottom 20. For fixtures and risk, lower is better, so the comparison flips.

### Suggestions

The app shows the best single moves. Each move is checked on its own against your current squad (so do not assume you can make both). It respects your budget, the 3-players-per-club limit, and counts the points cost of an extra transfer.

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
> - What did the backtest show about FPL's own prediction versus our model? Why might that be?
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

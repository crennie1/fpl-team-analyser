# FPL Team Analyser — Design

Date: 2026-10-19
Status: approved by owner 2026-10-19

## Intent and why

The owner wants a project that does two jobs:

1. **Gets them hired.** It is a portfolio piece for data analyst roles first, with AI/tech roles as a secondary target. It must survive an interviewer saying "walk me through this".
2. **Could make money later.** It is free for now. Paid features are a possible future, not part of this design.

Their previous project, a vibe-coded appointment app for waste-management businesses, never reached a real user. This one must actually work on real data and be used, first by the owner.

The owner plays Fantasy Premier League (FPL), holds a Man City season ticket and plays football. The trigger moment was transferring in a player who got injured the same gameweek. That was bad luck rather than a missed signal, so injury prediction is not the goal.

## What it is

A free web app. The user enters their FPL team ID and gets an analysis of their current squad:

- **Pitch view.** All 15 players laid out by position: the starting XI on the pitch and the bench below it. Each player shows expected points for the next gameweek and is coloured green, amber or red (good, weak, problem). Injured or doubtful players are flagged. The captain is marked.
- **Team grades.** Letter grades for Attack, Midfield, Defence, Fixtures (next 5 gameweeks), Injury/rotation risk and Bench.
- **Projection.** The team's projected points for the next gameweek, shown next to the projected average manager score.
- **Suggested moves.** One or two specific player swaps that the user can afford. Each shows the expected points gained over the next 3 gameweeks and the effect on the relevant grade.

The approved baseline layout puts the pitch on the left, the grades and projection on the right, and suggestions underneath. The mockup is in `docs/mockups/team-analysis-v2.html`.

## Goals

- Works end to end on real, current FPL data for any public team ID.
- The owner uses it for their own weekly decisions.
- It is publicly hosted and shareable by link.
- Forecast accuracy is measured honestly. Expected points are checked against actual points for past gameweeks and compared with simple baselines (last-5-gameweek average, and FPL's own `ep_next`). The result is reported whether it is good or bad.
- There is a public GitHub repository with a README write-up in the owner's words: the question, the data, the method, what worked and what failed.
- The owner can personally explain and reproduce the analysis part in SQL.

## Non-goals (for now)

- Payments, accounts and logins.
- An AI-written paragraph verdict. It may come later, once the basics work.
- Injury prediction.
- Mini-league features, a chip planner, or a multi-week transfer planner.
- A mobile app. The website must still be usable on a phone.

## Anti-goals (failure even if it "works")

- Anything betting-related.
- A slick demo with fake or stale data. If the data feed fails, the app says so plainly.
- Code the owner can't explain at the level an interviewer would probe: the data flow, the database tables, how expected points and grades are calculated, and how accuracy was measured.
- Scraping or copying data from paid FPL tools.

## How the work is split

The owner does not want to learn to program and is happy to vibe-code. Data analyst interviews test SQL and probe projects, so the work is split this way:

- **The builder (Claude) writes** the data collection, the database setup, the forecast model and the web app.
- **The owner writes**, with help, the SQL analysis queries that answer football questions. Examples: do fixtures or form predict points better? How often does the top expected-points player actually return? These queries and their findings live in a clearly marked `analysis/` folder.
- **The owner writes** the README conclusions in their own words.

The build should make the owner's part easy. That means clear table names, a plain-English data dictionary, and a few starter questions with worked example queries.

## Decided

**Owner's decisions:**
- FPL as the domain. Free for now. Pitch view plus grades as the main screen. Vibe-coded, with the owner owning the analysis and write-up.

**Builder's (Claude's) calls, accepted by the owner:**
- **Language:** Python.
- **Data source:** the official FPL API, which is public and needs no key. Use `bootstrap-static/` for players, teams, status and `ep_next`; `fixtures/` for fixtures and difficulty; `element-summary/{id}/` for player history; `entry/{team_id}/` and `entry/{team_id}/event/{gw}/picks/` for the user's squad.
- **Storage:** a small SQL database (SQLite or DuckDB, the builder's choice) holding a snapshot of every gameweek, so history builds up for the accuracy test and for the owner's SQL work.
- **Web app:** Streamlit, hosted free on Streamlit Community Cloud.
- **Forecast:** start simple, using recent form, minutes/start likelihood, fixture difficulty and position-based scoring. Only add complexity if it beats the baselines in the accuracy test.
- **Grades:** relative, not fixed. A grade reflects how the squad's expected points for that area compare with a reference population. The builder picks the population, for example a sample of public teams or the top 10k, and documents it.
- **Code:** a public GitHub repository.

**More of the builder's calls, settled after the review. The owner should check them:**
- **Suggestions are actionable.** They respect the user's bank, the 3-per-club rule and the number of free transfers. A move that needs an extra transfer shows the -4 cost. Selling prices are estimated from the public `entry/{team_id}/transfers/` history using FPL's selling rule: the buy price plus half of any rise, rounded down to 0.1m. Every suggestion names a specific player swap. Vague advice like "a defender with easier fixtures" is dropped.
- **The forecast and the grades are written as SQL views** over the database wherever practical. That way the owner can read and reproduce the whole chain from raw data to grade in SQL. Python handles fetching data, the website and anything SQL can't reasonably do.
- **The app shows whichever forecast wins the backtest.** If FPL's own `ep_next` beats the custom model over the next gameweek, the app uses `ep_next` for next-gameweek points and the README says so. The custom model is still used for 3-gameweek suggestions, because `ep_next` covers only one gameweek.
- **What each grade measures:**
  - **Attack, Midfield and Defence** are grouped by position (FWD; MID; DEF and GK together). Each compares the starters' total expected points with the reference population.
  - **Fixtures** is the average difficulty of the starters' fixtures over the next 5 gameweeks.
  - **Injury/rotation risk** is the share of the starters' expected points coming from flagged or low-minutes players.
  - **Bench** is the bench's expected points.
  - Every grade is a percentile against the reference population, mapped to A–E.

## Left to the builder

- SQLite vs DuckDB, project structure, and the exact libraries.
- The forecast's exact formula, provided it is explainable in a few sentences and is backtested.
- Grade cut-offs and the reference population for "average manager".
- How past-season data is obtained for backtesting. The FPL API serves the current season only; past seasons need a public archive such as the vaastav Fantasy-Premier-League GitHub dataset. Document the source.
- Visual styling, beyond the approved layout.
- How the data refreshes: on demand with caching, a scheduled job, or both.

## Known constraints

- Before the gameweek deadline, the picks endpoint only shows the previous gameweek's squad. Transfers made this week but not yet locked in won't appear. The app says which gameweek's squad it loaded. **Owner's decision:** users can edit the loaded squad by swapping any player for another. Edits are checked against FPL's squad rules (budget, positions, 3 per club). Grades, projection and suggestions recalculate immediately. That lets the user test a planned transfer before making it.
- **Timeline (owner's decision):** there is no fixed date. Build in the natural order: data collection and storage, then the forecast and backtest, then the website. Don't rush a website built on placeholder numbers.
- The FPL API is unofficial and rate-limits. Cache its responses and be polite with requests.
- The app's own running costs must be £0.

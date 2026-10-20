# FPL Team Analyser v2 — Design

Date: 2026-10-20
Status: draft, awaiting owner approval
Builds on: `docs/2026-10-19-fpl-team-analyser-design.md` (v1, live at fpl-team-analyser.streamlit.app)

## Intent and why

v1 works and is live, but two things hold it back for the owner's goals (data-analyst job, maybe money later):

1. **The forecast is too simple.** It uses only points and minutes, and lost the backtest to FPL's own prediction, so the app currently shows FPL's numbers. A smarter model built on the stats FPL players actually look at (xG, xA, penalties, set pieces, opponent weaknesses, defensive contributions) is a stronger interview story, whether it wins or loses, as long as it's tested honestly.
2. **The team view looks basic.** The owner wants an appealing, modern view where clicking a player shows his stats.

The owner directs the work and has the AI build it. They won't write code, and will explain in interviews what they asked for and why. So the project must also produce a plain-English **interview explainer**.

## What v2 adds

### 1. Richer data
For every player and finished gameweek, store, in addition to v1's minutes and points:
- expected goals (xG), expected assists (xA), expected goal involvements, expected goals conceded
- goals, assists, clean sheets, goals conceded
- **defensive contribution** count (FPL's DefCon stat, 2025-26 onwards) and whether the player reached his threshold

Also store each team's set-piece takers from FPL: penalty order, corners and indirect free kicks order, and direct free kicks order.

The same fields come from the past-season archive (2025-26) where it has them, so the new model can be backtested.

### 2. Opponent weaknesses
For each team, over the last 6 finished gameweeks, show what it concedes **by the scoring player's position** (GK, DEF, MID, FWD):
- FPL points conceded to that position, per match
- xG conceded to that position, where available

Rank teams by each measure. This is the honest free-data version of "Fulham's left side is weak". The free data has no pitch-location information, so left and right flanks are **not** in scope.

### 3. DefCon chance
FPL awards 2 points for defensive work:
- **Defenders:** 10+ clearances, blocks, interceptions and tackles in a match.
- **Midfielders and forwards:** 12+ of those actions, with ball recoveries also counting.

For each player, estimate the chance he reaches his threshold next gameweek:
- start from how often he hit it per appearance in his last 6 matches
- adjust for the opponent (how many defensive actions players face against that team)

Its expected value (chance × 2) feeds into the forecast.

### 4. Forecast v2
An explainable expected-points model built from components:
- **Appearance points** from minutes likelihood, as in v1.
- **Goal and assist threat** from recent xG and xA per 90, scaled by the opponent's weakness against the player's position.
- **Clean-sheet chance** for GK and DEF, from his team's recent xG conceded and the opponent's attacking strength.
- **DefCon** as above.
- **Set-piece bonus** for penalty and set-piece takers.

Every component must be explainable in a sentence or two. Where practical it lives in SQL views, like v1, so the owner can show the chain.

**The honest test (required):** backtest forecast v2 against FPL's own prediction, v1's model and the last-5 average, for both 1-gameweek and 3-gameweek horizons, using the same rules as v1 (identical rows, no lookahead, gameweeks without FPL predictions excluded). The app uses whichever wins for each horizon. The report states the result plainly, including if v2 loses. Once enough current-season gameweeks exist (GW8 onwards has stored FPL predictions), also run an out-of-sample check on this season.

### 5. New team view
Replace the v1 pitch with the approved **dark player-card** design: `docs/mockups/team-view-cards-v5.html`.
- Navy pitch. Each player is a card showing:
  - a club-colour strip along the top
  - a **kit shirt drawn by the app** in club colours, with the player's first and last initials on plain shirts (no Premier League images)
  - position, captain mark and injury flag
  - name and expected points, coloured green, white or red
  - next opponent with (H) or (A), coloured by fixture difficulty
  - a DefCon bar with its percentage
- The bench sits below the pitch.
- A **grades strip** of six tiles above the pitch, with projected points against the average manager beside it.
- **Suggested sells** shown on the pitch: a red outline and a "↘ SELL" tag on the player to sell.
- **Click a player:** a stats panel opens on the right (on phones it slides up from the bottom, with a close button). It shows:
  - full name, position, club, price and ownership, plus any injury note
  - the suggested replacement and points gain, if he's a suggested sell
  - expected points next gameweek and next 3, and DefCon chance
  - a plain-English definition of DefCon chance
  - next 3 fixtures coloured by difficulty
  - last 6 gameweeks: form, xG, xA, DefCon hit rate
  - the next opponent's weakness against his position
  - set-piece duties
- An **"Opponent weaknesses"** view (a tab or section) showing the team table from part 2.
- The squad editor and free-transfer input from v1 stay. They can be restyled to match.

### 6. Interview explainer
`docs/interview-explainer.md`: one or two pages in plain English, covering:
- what the owner asked the AI to build, and why
- the key decisions and trade-offs (for example: why FPL's prediction was used in v1; no left/right data; kits instead of photos)
- how accuracy was tested and what the results were
- what they'd do next

It should be written so the owner can talk through it in an interview.

## Goals
- Every number on screen comes from real, current data. Nothing is invented.
- Forecast v2 is backtested honestly against the baselines, the app uses the winner, and the report shows the result.
- The new view matches the approved mockup, works on desktop and phone, and lets you click any player for stats.
- All v1 behaviour keeps working: squad loading, swaps, suggestions, grades, the daily refresh and the error messages.
- Cost stays £0.

## Non-goals
- Player photos or Premier League kit images (copyright, if the app ever charges).
- Left or right flank weaknesses (no free location data).
- Paid features, accounts, the multi-week planner, mini-league views, chip advice.
- An AI-written text verdict.

## Anti-goals
- Swapping the app's forecast to v2 without it winning the backtest.
- Mockup polish with placeholder numbers in the live app.
- Anything betting-related.
- Breaking the live site: v2 ships only when the full test suite passes.

## Decided
**Owner:** opponent weakness by position (no flank data); DefCon chance with an explanation; dark-card design with drawn kits; click a player to open the stats panel; grades strip; sell markers; next-opponent badge; club strip; phone bottom sheet; no photos anywhere; the owner won't code and will explain via the explainer.

**Builder's calls (Claude), for the owner to check:**
- Same stack (Python, SQLite, SQL views, Streamlit), same repo, and deploys by pushing to `main` as before.
- The new pitch and stats panel are rendered as one self-contained HTML/JS block inside Streamlit, with the squad's data embedded, so clicking a player is instant and needs no server round-trip. The squad editor stays as Streamlit widgets.
- The last 6 gameweeks are the window for form, weaknesses and DefCon, matching v1.

**More builder's calls, settled after review (owner to check):**
- **Fitting vs scoring (honesty).** Any forecast parameter that is fitted to data (the xG/xA scaling, opponent-weakness scaling, clean-sheet formula, and FDR multipliers) is fitted on **2024-25** and scored on **2025-26**, so the backtest result is out-of-sample. This means loading 2024-25 from the archive as well. DefCon chance uses no fitted parameters: it's the player's own past hit rate, with a simple opponent ratio computed only from gameweeks before the one being predicted. The report says all this in plain words.
- **Set pieces.** Who takes set pieces is only known for today; there's no history. So the backtested forecast v2 has **no set-piece bonus**. The bonus is added to the live forecast only after the out-of-sample check on this season shows it helps. Until then, set-piece duties appear in the stats panel as information only.
- **Choosing the forecast.** For each horizon (1 and 3 gameweeks), the app uses v2 only if its MAE is strictly lower than every alternative's. Otherwise it keeps the current winner. DefCon chance, opponent weaknesses and the panel stats are descriptive, so they're always shown whichever model wins.
- **Goalkeepers.** They have no DefCon threshold, so their card shows a "Clean sheet %" bar in the same place, and their panel shows clean-sheet chance instead of DefCon.
- **Shipping.** v2 ships once the 2025-26 backtest is done and all tests pass. The out-of-sample check on this season shows "pending until GW12" in the report and runs automatically once there's enough data. It doesn't hold up the release.

## Left to the builder
- Exact formulas for each forecast component, provided each is explainable and backtested.
- How to read the new fields from the FPL API (`event/{gw}/live` stats) and the archive. If the archive lacks a field for 2025-26, document it and backtest only what's possible.
- Schema changes and the migration of the committed `data/fpl.db` (it must upgrade safely, as v1's `news` column did).
- Exact kit colours and patterns for all 20 clubs, kept recognisable and simple.
- Where the Opponent weaknesses view sits (a tab or a section below).

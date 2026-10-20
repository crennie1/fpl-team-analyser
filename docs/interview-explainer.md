# FPL Team Analyser v2: my interview explainer

I did not write the code. I directed an AI to build it, checked what it produced, and made the calls on what to keep. This page is how I explain that in an interview. Every number below comes from `reports/backtest.md`.

## The goal

Fantasy Premier League (FPL) is a game where you pick a squad of real footballers and score points from what they do in real matches. I wanted a free web app where you type in your team ID and it:

- grades your squad against the average manager,
- suggests the transfers that would add the most points,
- lets you click any player to see his stats.

Version 1 did the first two. Version 2 adds richer stats, a better forecast attempt and a much nicer team view. It still costs nothing to run.

## What I asked the AI to do, and why

- **Build a smarter forecast from the stats FPL players really use.** That means xG (expected goals: how many goals a player's chances "should" have produced) and xA (expected assists, the same idea for passes). It also means clean sheets and **DefCon** (defensive contribution: FPL gives 2 bonus points for a set number of tackles, clearances, blocks and interceptions in a match).
- **Test it honestly.** I wanted the new model to face FPL's own prediction and my v1 model, on matches it had never seen.
- **Show opponent weaknesses.** For each club: how many points it concedes to goalkeepers, defenders, midfielders and forwards.
- **Redesign the team view** as dark player cards with a stats panel. It works on a phone too.
- **Keep it explainable.** Every part of the forecast has to be describable in a sentence or two. The formula is written in plain English at the top of `fpl/sql/forecast_v2.sql`.

## Key decisions and trade-offs

- **v1 used FPL's own prediction.** In v1 I backtested my model against FPL's number. FPL won, so the app used FPL's number. I chose to follow the evidence rather than my own model.
- **Fit on 2024-25, test on 2025-26.** The model has one fitted setting: a scale factor for goal and assist points, set per position (`calib_att`). If you fit a setting and score it on the same season, the result looks better than it should. So I had the AI fit it on 2024-25 and score it on 2025-26, a season it had never seen. That is called **out-of-sample**. I did the same for v1's fixture-difficulty multipliers, which moved v1's score slightly (1.880 to 1.876).
- **v2 is used only if it is strictly better.** The app switches to v2 for a horizon only when its error is lower than every other method's on the same rows. A tie keeps the old source.
- **Fixes found by checking against real data.** The build process checked every step against real data. It caught that one lucky game could show a 95% DefCon chance, so the rate is now pulled toward the position average. Opponent ratios are capped between 0.5 and 2.0. They were set to 1.0 when the stat is too rare to compare, because real data had produced ratios of 20. The goalkeeper scale factor stays at 1.0 because only 4 predicted points were available to fit it.
- **No left or right flank weaknesses.** Free data has no pitch-location information. I asked for weakness by position instead, and I say so openly.
- **Kits are drawn, not photos.** The app draws shirts in club colours with the player's initials. I chose drawn kits over player photos because Premier League images are copyrighted, and that would matter if I ever charged for the app.
- **Set pieces are display-only.** Who takes penalties and corners is only known for today, with no history. I can't backtest a bonus I can't test, so the panel shows it as information and it does not change the forecast.
- **Cost stays at zero.** Same stack as v1: Python, a SQLite file, SQL views, Streamlit and a free daily GitHub job.

## How accurate was it?

The score is **MAE** (mean absolute error): the average gap between predicted and real points per player per gameweek. Lower is better. The 1-gameweek test covered 2520 player-gameweeks in 2025-26 (gameweeks 6, 8-9, 24, 29 and 38). Those are the only ones where the archive has FPL's own predictions. All methods were scored on the same rows.

| Method | Next gameweek | Next 3 gameweeks |
|---|---|---|
| FPL's own prediction | **1.371** | **3.635** |
| My v2 forecast | 1.819 | 4.047 |
| My v1 model | 1.876 | 4.242 |
| Last-5 average (simple baseline) | 1.927 | 4.331 |

(The 3-gameweek column uses 2093 rows. FPL's number is scaled by fixture count and difficulty, which is what the app does.)

The honest reading:

- v2 beat my v1 model and the simple last-5 average, on both horizons.
- v2 did **not** beat FPL's own prediction. FPL's error is about a quarter lower.
- So the app still uses FPL's numbers for both horizons. It shows v2's extra stats (DefCon chance, clean-sheet chance, opponent weaknesses) as information.
- The 3-gameweek sample is small, so I treat it as a sanity check.
- A check on the current season is pending. It runs automatically once about 12 gameweeks are in.

## What I'd do next

- Wait for the current-season check and see if v2 closes the gap.
- Add the set-piece bonus only if the current-season data shows it helps.
- Try to find out why FPL wins. It probably knows things my data does not, such as team news and expected lineups.
- Keep a record over time of the forecast's accuracy.

## Five likely interview questions

**1. Did your model beat FPL's own prediction?**
No. My v2 beat my first model and a simple average, but FPL's prediction had the lowest error (1.371 against 1.819). I reported that plainly, and the app uses FPL's numbers.

**2. Why fit on one season and test on another?**
If you tune a model on the same data you score it on, it looks better than it is. Fitting on 2024-25 and scoring on 2025-26 shows how it handles matches it has never seen.

**3. What is MAE and why use it?**
It is the average size of the gap between predicted and actual points. It is easy to explain, it is in real FPL points, and it does not let a few big misses dominate, compared with squared-error measures.

**4. What are the limits of your analysis?**
The test covers only the gameweeks where FPL's old predictions exist: 6 of the 38 gameweeks scored. The 3-gameweek test is small. There is no left or right flank data. Set pieces have no history, so they are not in the forecast.

**5. How did you work with the AI, and how did you know it was right?**
I set the goal and the rules, such as "fit on one season, test on another" and "use v2 only if strictly better". The build process checked every step against real data. It caught that one lucky game could show a 95% DefCon chance, so the rate is now pulled toward the position average and the opponent adjustment is capped. The SQL is readable, the tests are automated, and every number comes from the database.

(Swap in your own example if you have one.)

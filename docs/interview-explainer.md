# FPL Team Analyser v2: my interview explainer

I did not write the code. I directed an AI to build it, checked what it produced, and made the calls on what to keep. This page is how I explain that in an interview. Every result below comes from `reports/backtest.md`. The two exceptions are labelled where they appear: the live FPL check on 26 Oct, and the old, leaked backtest result.

## The goal

Fantasy Premier League (FPL) is a game where you pick a squad of real footballers and score points from what they do in real matches. I wanted a free web app where you type in your team ID and it:

- grades your squad against the average manager,
- suggests the transfers that would add the most points,
- lets you click any player to see his stats.

Version 1 did the first two. Version 2 adds richer stats, a better forecast attempt and a much nicer team view. It still costs nothing to run.

## What I asked the AI to do, and why

- **Build a smarter forecast from the stats FPL players really use.** That means xG (expected goals: how many goals a player's chances "should" have produced) and xA (expected assists, the same idea for passes). It also means clean sheets and **DefCon** (defensive contribution: FPL gives 2 bonus points for a set number of tackles, clearances, blocks and interceptions in a match).
- **Test it honestly.** I wanted the new model to face my v1 model, a simple average and FPL's prediction, on matches it had never seen.
- **Show opponent weaknesses.** For each club: how many points it concedes to goalkeepers, defenders, midfielders and forwards.
- **Redesign the team view** as dark player cards with a stats panel. It works on a phone too.
- **Keep it explainable.** Every part of the forecast has to be describable in a sentence or two. The formula is written in plain English at the top of `fpl/sql/forecast_v2.sql`.

## Key decisions and trade-offs

- **The site's xP now comes from my own model.** Until 26 Oct the site showed FPL's own "expected points", because an earlier backtest said FPL's number beat my models. That backtest turned out to be leaked (see "The leak" below). Now every xP on the site comes from the method that wins the clean backtest, which is v2. Click a player and the panel shows his xP split into its parts, each with a one-line reason, and a clear warning that bonus points are not included.
- **Fit on 2024-25, test on 2025-26.** The model has one fitted setting: a scale factor for goal and assist points, set per position (`calib_att`). If you fit a setting and score it on the same season, the result looks better than it should. So I had the AI fit it on 2024-25 and score it on 2025-26, a season it had never seen. That is called **out-of-sample**. I did the same for v1's fixture-difficulty multipliers.
- **The best method is used only if it is strictly better.** For each horizon the app uses the method with the lowest error on the same rows. A tie goes to the simpler v1 model.
- **Fixes found by checking against real data.** The build process checked every step against real data. It caught that one lucky game could show a 95% DefCon chance, so the rate is now pulled toward the position average. Opponent ratios are capped between 0.5 and 2.0. They were set to 1.0 when the stat is too rare to compare, because real data had produced ratios of 20. The goalkeeper scale factor stays at 1.0 because only 4 predicted points were available to fit it.
- **No left or right flank weaknesses.** Free data has no pitch-location information. I asked for weakness by position instead, and I say so openly.
- **Kits are drawn, not photos.** The app draws shirts in club colours with the player's initials. I chose drawn kits over player photos because Premier League images are copyrighted, and that would matter if I ever charged for the app.
- **Set pieces are display-only.** Who takes penalties and corners is only known for today, with no history. I can't backtest a bonus I can't test, so the panel shows it as information and it does not change the forecast.
- **Cost stays at zero.** Same stack as v1: Python, a SQLite file, SQL views, Streamlit and a free daily GitHub job.

## The leak: how I found it and fixed it

This is the part of the project I'm proudest of, because it came from looking at the app as a user.

- **How I noticed.** Using the site on 26 Oct, I felt the xP "is just recent points". It was FPL's own number, and when we checked the live FPL data on 26 Oct, FPL's "expected points" equalled its `form` (average points over about 30 days) for 412 of 451 players. A backward-looking average shouldn't beat a real model by a wide margin, yet the old backtest said it did (an error of 1.371 for FPL against 1.819 for v2).
- **Proven two ways.** The past-season archive's FPL prediction was recorded after each gameweek, so it had seen the result:
  1. It matched the player's average over the 4 gameweeks *including* that week far better than the 4 gameweeks *before* it (error 0.655 against 1.018 in 2024-25; 0.594 against 1.096 in 2025-26). A prediction made before kick-off can only know the weeks before.
  2. When a player scored 12 or more, FPL's number for that week jumped with the result: 7.19 against 4.19 the week before in 2024-25, and 7.46 against 3.64 in 2025-26.
- **Separately, a first fair test.** On GW8 of 2026-27, using FPL's predictions our own collector saved before kick-off, v2 had an error of 1.832 against FPL's 2.057. That is an early sign from one gameweek, not proof; it's too early to call.
- **Fixed.** The backtest no longer scores the archive's FPL numbers and has a "Leak check" section that recomputes tests 1 and 2 on every run. FPL's prediction is now compared only where it was saved before the deadline. The site's xP comes from my own model, and each player's panel explains his number.

## How accurate was it?

The score is **MAE** (mean absolute error): the average gap between predicted and real points per player per gameweek. Lower is better. Without the leaked FPL column, the test covers many more gameweeks than before: 13496 player-gameweeks in 2025-26 (gameweeks 6-38). All methods were scored on the same rows.

| Method | Next gameweek | Next 3 gameweeks |
|---|---|---|
| My v2 forecast | **1.867** | **4.235** |
| My v1 model | 1.929 | 4.498 |
| Last-5 average (simple baseline) | 1.986 | 4.634 |

(The 3-gameweek column uses 12656 rows, start gameweeks 6-36.)

FPL's prediction, saved before kick-off, compared fairly on GW8 of 2026-27 (427 players, same rows for every method):

| Method | Next gameweek |
|---|---|
| My v2 forecast | **1.832** |
| My v1 model | 1.947 |
| Last-5 average | 2.009 |
| FPL's prediction, saved before kick-off | 2.057 |

The honest reading:

- v2 beat my v1 model and the simple last-5 average, on both horizons, so the site uses v2.
- On GW8, v2 also beat FPL's prediction. That is an early sign from one gameweek, not proof. The report calls it "too early to call" until 5 gameweeks are in, and it grows each week on its own.
- The old numbers (and the old result that FPL won) are not comparable with these. They used only the few gameweeks the archive had FPL predictions for, and FPL's numbers there had seen the results.
- v2 leaves out bonus points, so it under-rates top attackers. The panel says so in an amber warning.

## What I'd do next

- Watch the fair FPL comparison grow past 5 gameweeks and see if the early sign holds.
- Add a bonus-points estimate, the biggest thing v2 leaves out.
- Add the set-piece bonus only if the current-season data shows it helps.
- Keep a record over time of the forecast's accuracy.

## Five likely interview questions

**1. Did your model beat FPL's prediction?**
At first my backtest said no: FPL's error was 1.371 against 1.819 for v2, so the site used FPL's numbers. Then I noticed the xP on the site looked like recent points, and we proved the archive's FPL prediction was recorded after the matches, so it had seen the results. With that removed, v2 beats my v1 model and a simple average (1.867 against 1.929 and 1.986), so the site now uses v2. On the one gameweek where we have FPL's prediction saved before kick-off, v2 also beat it (1.832 against 2.057). That is an early sign from one gameweek, and I say so.

**2. Why fit on one season and test on another?**
If you tune a model on the same data you score it on, it looks better than it is. Fitting on 2024-25 and scoring on 2025-26 shows how it handles matches it has never seen.

**3. What is MAE and why use it?**
It is the average size of the gap between predicted and actual points. It is easy to explain, it is in real FPL points, and it does not let a few big misses dominate, compared with squared-error measures.

**4. What are the limits of your analysis?**
The fair comparison with FPL is one gameweek so far, so it is an early sign, not proof. The forecast leaves out bonus points, cards and own goals. There is no left or right flank data. Set pieces have no history, so they are not in the forecast.

**5. How did you work with the AI, and how did you know it was right?**
I set the goal and the rules, such as "fit on one season, test on another" and "use a model only if it is strictly better". The build process checked every step against real data. The best example is the leak: I didn't trust a number that felt wrong in use, asked for it to be checked, and the data proved it. The review process caught that one lucky game could show a 95% DefCon chance, so the rate is now pulled toward the position average and the opponent adjustment is capped. The SQL is readable, the tests are automated, and every number comes from the database.

(Swap in your own example if you have one.)

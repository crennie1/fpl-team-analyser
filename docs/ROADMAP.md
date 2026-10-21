# Roadmap

Ranked by impact on the two goals: getting hired as a data analyst, and possibly earning money later. Each item notes its size and a rough build time.

| # | Change | Why it matters | Size | Rough time |
|---|---|---|---|---|
| 1 | **Out-of-sample test on this season** (write-up once ~GW12 data exists) | The strongest interview evidence: an honest test on games no model was tuned on. The report runs it automatically; you post the result. | Small | 30 min |
| 2 | **Swap a player from the stats panel** (click a player, then choose a replacement), **with an over-budget planning mode**: swaps are allowed even when they break the budget, and the app shows a clear "£1.2m over budget" warning instead of blocking, so you can try a dream team, or bring in an expensive player before deciding who to sell. The 3-per-club and position rules still apply. | The feature you'll use most. Makes the app feel finished when you share it. Task card already saved. | Medium | 2.5–3.5 h |
| 3 | **Player strengths/weaknesses + reasons for each grade** (rule-based text from real numbers) | Turns numbers into insight, which is the core analyst skill. Great for screenshots and interviews. | Medium | 2–3 h |
| 4 | **"How it works" page in the app** (method, backtest chart, plain English) | Recruiters see your analysis without opening GitHub. | Small–medium | 1–2 h |
| 5 | **DefCon calibration check** (predicted % vs actual hit rate, last season) | Proves the DefCon numbers are trustworthy, or shows how you fixed them. A strong data story. | Medium | 2–3 h |
| 6 | **Better model attempt** (e.g. bonus points, home/away form, minutes trends), tested against FPL | Interview story whether it wins or loses. Do it after #1 and #5. | Large | Half a day |
| 7 | **Multi-week transfer planner** (2–3 moves across weeks, free transfers and hits) | The most-wanted FPL tool and the natural paid feature. | Large | 1 day+ |
| 8 | **Mini-league view** (your squad vs rivals', who they own that you don't) | Strong user pull and shareable. Another paid-tier candidate. | Large | Half a day–1 day |
| 9 | **Captain and chip advice** (best captain, when to play Bench Boost / Triple Captain) | Weekly-use feature that brings people back. | Medium | Half a day |
| 10 | **Keep the repo small** (move fixed past-season history into its own file) | Stops GitHub growing as data builds up. Needed within a season or two. | Medium | 2 h |
| 11 | **Power BI or Tableau dashboard** on your SQLite data (you build, with help) | Many analyst job ads ask for these tools. Builds your own hands-on skill. | Medium (your time) | A few evenings |
| 12 | **Polish bundle:** friendly date in the footer, grades with +/−, tidier layout at mid widths, remove unused styles, reword one overstated backtest sentence | Small visual and wording fixes from the reviews. | Small | 30–60 min |
| 13 | **Season rollover check** (before August 2027) | Makes sure the switch to 2027-28 picks the right seasons automatically. | Small | 30 min |

## Suggested order over time
- **This week:** #2. Then use the app for a gameweek and update your CV/README (no code).
- **Next 2 weeks:** #3 and #4, then #12 whenever you have half an hour.
- **Around GW12:** #1, then #5.
- **Later / if going paid:** #7, #8, #9, then #6.
- **Before next season:** #10 and #13.
- **Your own learning, any time:** #11.

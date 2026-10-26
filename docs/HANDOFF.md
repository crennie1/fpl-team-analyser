# FPL Team Analyser — Handoff

*Last updated: 21 Oct 2026. To continue in a new Claude session, see "Starting a new session" at the bottom.*

## 1. What it is and why
A free website that analyses any Fantasy Premier League team. It's a **portfolio project for data-analyst job applications**, and could become a paid tool later. The owner (me) directs the AI to build it and doesn't write code. In interviews I explain the decisions and results, not the code.

- **Live site:** https://fpl-team-analyser.streamlit.app (add `?team=YOURID` to open a team directly)
- **Code:** https://github.com/crennie1/fpl-team-analyser
- **On my Mac:** `/Users/conalbird/Claude/fpl-team-analyser`
- **Cost:** £0 (GitHub, GitHub Actions and Streamlit Community Cloud are all free tiers)

## 2. What the site does (v2, live since 20 Oct 2026)
- Enter an FPL team ID to see your squad as **dark player cards**: drawn club kits (no Premier League images, for copyright), initials, expected points (xP), next opponent coloured by difficulty, and a DefCon bar (Clean sheet % for goalkeepers).
- **Click a player** for a stats panel: xP next week and next 3 weeks, DefCon chance (with a plain-English definition), next 3 fixtures, last-6-gameweek form/xG/xA/DefCon hits, the opponent's weakness against his position, and set-piece duties. On a phone the panel opens under the tapped row.
- **Grades strip:** six grades (Attack, Midfield, Defence, Fixtures, Injury risk, Bench) relative to 500 random real FPL teams, plus projected points against the average manager.
- **Sell suggestions** on the pitch: a red "SELL" tag, with the affordable replacement and the 3-week gain shown in the panel.
- **Opponent weaknesses tab:** points and xG each team concedes to GK/DEF/MID/FWD.
- **Swap players from the team sheet:** click a player, then Replace, to see every player in that position with up to 3 👍 suggestions. Going over budget is allowed: an amber warning shows instead of blocking you, while the position and 3-per-club rules still apply. Swapped-in players get an IN tag, and a changes bar shows changes, free transfers used, −4 point hits, any over-budget amount, Undo last, Reset to my team, and a control to set your free transfers.
- **Your plan vs your real team:** points over the next 3 weeks before and after hits, grades that changed (▲/▼), money in the bank, and an Out → In list.

## 3. The honest results (the interview story)
Backtested on the 2025-26 season, tuned only on 2024-25 (so it's "out of sample"). Error is in points; lower is better:

| Method | 1 week | 3 weeks |
|---|---|---|
| FPL's own prediction | **1.371** | **3.635** |
| My v2 model (xG, xA, opponent weakness, clean sheets, DefCon) | 1.819 | 4.047 |
| My v1 model (form + fixtures) | 1.876 | 4.242 |
| Last-5 average | 1.927 | 4.331 |

v2 beat my v1 model and the simple average but **not FPL**, so the site uses FPL's numbers (scaled by fixtures over 3 weeks) and shows v2's extra stats as information. A test on this season's games runs automatically from about gameweek 12.

Interview prep is in `docs/interview-explainer.md`: plain English, with 5 likely questions and answers.

## 4. How it works (one paragraph)
- **Daily (GitHub Actions, 6am UTC):** collects data from the official FPL API into one SQLite file, `data/fpl.db`, which also holds the 2024-25 and 2025-26 archives from the vaastav GitHub dataset.
- **Weekly:** samples 500 real teams to grade against.
- **On a new gameweek:** re-tunes and re-runs the backtest.
- **Saving:** the database is saved to GitHub only on a new gameweek, within 48 hours of a deadline, on Tuesdays, or on a manual run. That keeps the repo small.
- **Calculations:** the forecasts, grades and stats are SQL views, readable in `fpl/sql/`.
- **The site:** Streamlit (`app.py`) loads your team live from FPL and draws the card view (`fpl/ui/team_sheet/index.html`).

## 5. Key decisions (made during the builds)
- FPL's prediction is used wherever it beats my models, and the app only switches to my model if it's *strictly* better.
- Models are tuned on 2024-25 and tested on 2025-26, to avoid "seeing the answers".
- 2025-26 archive gameweeks where FPL's prediction was stored as 0 for every player are treated as missing.
- DefCon % is pulled toward the position average, so one lucky game can't show 95%. Opponent adjustments are capped at 0.5–2×.
- There's no left/right flank analysis, because free data has no pitch locations. Weaknesses are by position instead.
- Set-piece takers are shown as information only, since there's no history to test them.
- Suggestions respect your budget and the 3-per-club rule. A bench sell only counts if the new player would start.

Full detail: `docs/2026-10-19-fpl-team-analyser-design.md` (v1), `docs/2026-10-20-fpl-v2-design.md` (v2), `analysis/data_dictionary.md` (every table, view and formula), `reports/backtest.md` (live results).

## 6. Accounts and access
- **GitHub:** `crennie1`. A personal access token (repo + workflow scopes, **expires about 18 Jan 2027**) is saved in the Mac keychain, so pushes work. When it expires, make a new one in GitHub settings and paste it at the password prompt. Never put it in chat.
- **Streamlit Community Cloud:** signed in with GitHub. The site redeploys automatically about 1–2 minutes after a push to `main`. Secret set: `REPO_URL`.
- **Running it on the Mac:** the browser-pane config is at `/Users/conalbird/Claude/.claude/launch.json` (name `fpl-app`, port 8501).

## 7. What I still need to do (no code)
1. Use the app on my real team each gameweek and note what it got right and wrong.
2. Write the README's **"What I found"** and **"What I'd do differently"** sections in my own words.
3. Add a CV bullet and a LinkedIn post (live link plus the honest backtest result).
4. Practise the explainer answers out loud.
5. Apply for junior data-analyst roles, leading with the live link.

## 8. Plan for future changes
Full ranked list with sizes: `docs/ROADMAP.md`. In short:
1. Test on this season's games (around gameweek 12), 30 min.
2. ✅ **Done 21 Oct 2026:** swap a player from the team sheet, with an over-budget planning mode (budget is a warning, not a block).
3. Player strengths/weaknesses and reasons for each grade, 2–3 h.
4. "How it works" page in the app, 1–2 h.
5. DefCon accuracy check, 2–3 h.
6. Better model attempt, half a day.
7. Multi-week transfer planner (paid candidate), 1 day+.
8. Mini-league view, half a day to a day.
9. Captain and chip advice, half a day.
10. Keep the GitHub repo small, 2 h.
11. Power BI/Tableau dashboard (my own learning).
12. Polish bundle, 30–60 min.
13. Season rollover check, before Aug 2027.

**Timing rules:** small fixes any time; new features after I've used the current version for a gameweek; model changes around gameweek 12. Don't push changes in the hours before a gameweek deadline.

## 9. How builds are done (so a new session follows the same process)
1. **Design check with me first** (questions plus a clickable mockup), then a short design doc that I approve.
2. **Written build plan** saved in `docs/superpowers/plans/`.
3. **Build in small tasks**, each by a fresh helper, each reviewed, with fixes re-checked.
4. **Final whole-project review**, then merge to `main`, push, and check the live site.

Tests: `.venv/bin/pytest -q` (280 passing as of 21 Oct). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Where the swap feature stands:** built and reviewed 21 Oct 2026. The first push (21 Oct) broke the live site because Streamlit kept an old `fpl/suggest.py` loaded, so it was rolled back. It went live again on 26 Oct 2026 with a reload guard in `app.py`: each run fingerprints the `fpl` code and SQL files and reloads everything (and clears caches) when that changes.

## 10. Gotchas
- Some database views use `exp`/`ln` functions that the app adds itself. The plain `sqlite3` command line can't query the v2 views; use Python with `from fpl import db; db.connect('data/fpl.db')`, or DB Browser for SQLite.
- `data/fpl.db` is about 13.5 MB. Saving it daily would bloat the repo, which is why the save rules in section 4 exist.
- Player photos and Premier League kit images are deliberately not used (copyright, if the app ever charges).
- FPL predictions for this season are only stored from gameweek 8 onwards, so this season's test needs about 5 gameweeks of data first.

## Starting a new session
Open Claude Code in `/Users/conalbird/Claude/fpl-team-analyser` and paste:

> Read `docs/HANDOFF.md` and `docs/ROADMAP.md` first. I'm the owner of this FPL Team Analyser. I don't write code, so explain in plain English. Next I want to work on: [roadmap item]. Follow the same process as before: design check with me, a plan, then build with reviews, then push live.

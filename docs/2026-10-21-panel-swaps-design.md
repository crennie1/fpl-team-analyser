# Panel swaps and planning mode — Design

Date: 2026-10-21
Status: draft, awaiting owner approval
Builds on: v2 (live since 20 Oct 2026). Roadmap item #2.
Mockups (local only, not committed): `.superpowers/brainstorm/97755-1792605994/content/` — `replace-layout.html` (option A chosen), `after-swap.html`, `full-page.html` (the agreed whole page).

## Intent and why

The "Edit squad" box under the pitch is clunky: two drop-downs and an Apply button, away from the team sheet. The owner wants to plan transfers where they look at the team: click a player on the team sheet, press Replace, and choose from a big list of every FPL player in that position, with the site's own suggestions marked by a green 👍.

They also want to plan freely. A dream team, or bringing in an expensive player before deciding who to sell, should be allowed even when it breaks the budget, with a clear warning instead of a block.

This is the feature the owner will use most, and it makes the app feel finished when they share it (CV, LinkedIn, interviews).

## What the owner decided

### 1. Replacing a player (in the side panel)
- Click a player on the team sheet. The stats panel opens as now, with a new **Replace** button.
- Replace turns the panel into a **replacement list**, with a "← back to stats" link.
- The list holds **every current-season FPL player in that position** who is not already in the squad. It has:
  - a search box (by name),
  - sort by: Suggested first (default), points next 3 weeks, price, club,
  - per row: club kit/initials, name, club, next 3 opponents, price, points next 3 weeks.
- **👍 Suggested for your team:** up to 3 players at the top of the list, each showing "+N pts" (extra expected points over the next 3 gameweeks vs the player being replaced). They are the best swaps for *this* player in *this* squad, using the same rules as the existing red SELL suggestions: affordable from money in the bank plus the out-player's selling price, the 3-per-club rule, and for a bench player, only if the newcomer would start (rule R21 in `fpl/suggest.py`).
- **When a 👍 shows (owner chose):** always the top 3 players who'd add points (gain above 0 before any hit), not only swaps that beat the hit. If this swap would cost a hit, the row says so: "+3.2 pts, −4 hit". The red SELL tags keep their stricter rule (worth it *after* the hit, by more than 0.5). So a SELL tag means "make this move"; a 👍 means "best options if you replace him".
- **Affordable while over budget (owner chose):** judged against the plan's own money: price ≤ the plan's bank + the out-player's selling price. When the plan is over budget, that means the 👍 goes only to players who'd bring the plan back within budget. If none qualify, the list says "No player in this position gets you back within budget".
- Below them, every other player in that position.
- Players who would break the **3-per-club rule** are shown greyed out with the reason ("already 3 from this club") and can't be picked.
- Click a player in the list to swap them in. The team sheet, grades, projected points and SELL tags update.
- On a phone the panel already opens under the tapped row; the list opens there at full width.

### 2. Planning mode (budget is a warning)
- Swaps are allowed even when they put the squad over budget. An amber "£0.8m over budget" pill shows in the changes bar.
- The position rule and the 3-per-club rule still block a swap.
- Players you can't afford never get a 👍.

### 3. After a swap (all four agreed)
These only appear once at least one swap has been made. With no changes, the page looks as it does today.
- **A. IN tags:** each newly brought-in player gets a blue "IN · was <original player>" tag and an **undo** link on their card.
- **B. Changes bar** above the pitch: number of changes, free transfers used, points hit (−4 per swap beyond free transfers), over-budget amount, and buttons **Undo last** and **Reset to my team**.
- **C. Before vs after** ("Your plan vs your real team"), under the pitch: points next 3 weeks, the same after hits, each grade that changed (▲/▼), and bank.
- **D. Transfer list**, beside C: each swap as "Out £x → In £y" with the price difference, and the line "Make these in the FPL app. This site never changes your real team."
- The grades strip shows ▲/▼ on grades that moved, and the projected-points box shows the plan's points (see "Which points where" below).

### 4. The old Edit squad box is removed
Everything it did now lives on the team sheet.

## Goals, non-goals, anti-goals

**Goals:** plan transfers from the team sheet; see the site's picks for each player at a glance; try over-budget plans; see clearly whether a plan is worth its hits.

**Non-goals (not this build):** saving a plan between visits or sharing it by link (plans last for the browser session, as now); multi-week planning (roadmap #7); captain/chip advice (#9); changing the forecast model.

**Anti-goals (a failure even if it works):**
- Blocking a swap because of budget.
- A 👍 on a player who breaks the budget, the 3-per-club rule, or (for a bench swap) wouldn't start.
- Clutter: the bar, tags and plan section showing when nothing has changed.
- Anything that looks like it changes the user's real FPL team.
- Numbers in the plan section that disagree with the grades strip, or a 👍 "+N" that disagrees with the SELL panel's gain for the same swap.

## Constraints
- Free hosting stays as is (Streamlit Community Cloud, Streamlit 1.66.0). No new paid services.
- No player photos or Premier League kit images (copyright); use the existing drawn kits.
- Same look as the current dark card view (`fpl/ui/team_view.html`).
- Must work on a phone (≈400px wide).
- Every number comes from the existing analysis code and SQL views; the UI only displays.
- Keep the existing tests passing (`.venv/bin/pytest -q`, 208 at last count) and add tests for the new rules.
- Don't push in the hours before a gameweek deadline.

## Builder's calls (made by Claude, not the owner — flag in the plan)
- **Two-way team sheet.** Today the team sheet is a one-way `components.html` page: clicks can't reach Python. It will become a two-way component so Replace, picking a player, undo and reset reach the app. Streamlit 1.66 ships `st.components.v2` (bidirectional, no build step); the builder picks the exact mechanism. The page must still work with no JavaScript build tools.
- **Free transfers box moves into the changes bar** as a small editable number ("Free transfers: 1 ✎"), since the Edit squad box that held it goes. It's shown even with no changes, so the user can correct the estimate. This is the one control visible before any swap.
- **Hits:** points hit = 4 × max(0, swaps − free transfers). "Swaps" counts players in the plan who are not in the real squad. Swapping a player back to the original cancels that change.
- **Undo on a card** restores the original player in that slot, even if the slot was swapped more than once (A → B → C shows "IN · was A"; undo gives A back). **Undo last** reverses the most recent swap only.
- **Unaffordable players** in the list (price above the plan's bank + the out-player's selling price) show their price in amber, so it's clear the swap would leave you over budget, but they can still be picked.
- **Grade area for "Before vs after":** show every grade that changed, plus points and bank always.
- **List size:** all players in the position (up to about 300) are sent to the page; search and sort happen in the browser.
- **The red SELL suggestions stay** and keep working against the current plan, as now.
- Plans live in the Streamlit session, as the current test swaps do.
- **Bench 👍 picks start.** A 👍 for a bench player is measured against the weakest starter in that position (rule R21). Picking it also moves the newcomer into that starter's place in the XI (the existing `_promote`), so the plan's points include the "+N" shown. Undo reverses both. A non-👍 bench swap leaves the newcomer on the bench. Users can't otherwise edit the XI or captain in a plan (non-goal).
- **Which points where.** The projected-points box stays as now: next week, starters, captain counted twice, with no hit taken off. "Before vs after" uses the next 3 weeks on the same basis (starting XI's 3-week expected points, captain counted twice), shown both before and after hits. That needs a new squad-level 3-week total, tested.
- **Chips are ignored.** Hits are always 4 × swaps beyond free transfers. A user on a wildcard can raise the free transfers number.

## Left to the builder
- How the component is wired and how state is held between reruns.
- How `swap()` / `validate()` let over-budget through in planning mode while still enforcing every other rule (the plain rules must not weaken anywhere else, e.g. the suggestion engine).
- How per-player 👍 suggestions reuse `fpl/suggest.py` without duplicating its rules.
- Analysing both the real squad and the plan for "Before vs after" without the two disturbing each other (`analyse_squad` writes the squad to a shared table; `suggest()` already restores it).
- Exact layout at mid widths, empty states, and loading behaviour.

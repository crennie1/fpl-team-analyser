-- =====================================================================
-- Starter queries for data/fpl.db
--
-- Three worked examples, then three open questions for you.
-- Each query ends with ";". Run them one at a time in DB Browser for SQLite
-- (Execute SQL tab -> select one query -> Ctrl+Return / Cmd+Return).
-- The comment under each query says what answer to expect.
--
-- Words used here:
--   correlation  how closely two numbers move together. 0 = not at all.
--                1 = perfectly. Negative = one goes up as the other goes down.
--   r squared    correlation x correlation. Read it as "the share of the
--                ups and downs in points that this one thing explains".
--                (We show r squared because plain SQLite has no square-root
--                function. The "direction" column tells you the sign.)
--   FDR          Fixture Difficulty Rating. FPL's own 1-to-5 score for how
--                hard a match is. 1 = easy, 5 = hard.
--   pts/90       points per 90 minutes played. Puts every player on the same
--                scale, whatever his playing time.
--   view         a saved query with a name. v_player_form is a view: you can
--                SELECT from it as if it were a table.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. Do fixtures or form predict points better? (past season, 2025-26)
--
-- We look at every time a player played in a fixture in GW 7-38.
-- For each one we line up three numbers:
--   points   what he scored in that match
--   fdr      how hard the match was (FPL's rating, known before kick-off)
--   form     his points per 90 over the last 6 gameweeks BEFORE the match
--            (from the view v_player_form, so no peeking at the future)
-- Then we work out how closely fdr and form each move with points.
--
-- We use "fdr_ease" = 6 - fdr, so a higher number means an easier match.
-- That way both measures point the same way and can be compared fairly.
-- ---------------------------------------------------------------------
WITH matches AS (
    SELECT g.total_points            AS points,
           6 - g.fdr                 AS fdr_ease,
           f.pts_per_90              AS form
    FROM player_gw AS g
    JOIN v_player_form AS f
      ON f.season = g.season AND f.player_id = g.player_id AND f.as_of_gw = g.gw
    WHERE g.season = '2025-26'
      AND g.gw >= 7                 -- early gameweeks have too little form data
      AND g.minutes > 0             -- only players who actually played
      AND g.fdr IS NOT NULL
      AND f.pts_per_90 IS NOT NULL
),
sums AS (                            -- the building blocks of a correlation
    SELECT COUNT(*) * 1.0 AS n,
           SUM(points) AS sy,  SUM(points * points) AS syy,
           SUM(fdr_ease) AS sa, SUM(fdr_ease * fdr_ease) AS saa, SUM(fdr_ease * points) AS say,
           SUM(form) AS sb,     SUM(form * form) AS sbb,         SUM(form * points) AS sby
    FROM matches
),
covs AS (                            -- "covariance" = how much two things move together
    SELECT n,
           n * say - sa * sy AS cov_fdr,   n * saa - sa * sa AS var_fdr,
           n * sby - sb * sy AS cov_form,  n * sbb - sb * sb AS var_form,
           n * syy - sy * sy AS var_pts
    FROM sums
)
SELECT 'fixture difficulty (easier = higher)' AS predictor,
       CAST(n AS INTEGER) AS matches,
       CASE WHEN cov_fdr >= 0 THEN 'more points when easier' ELSE 'fewer points when easier' END AS direction,
       ROUND(1.0 * cov_fdr * cov_fdr / (var_fdr * var_pts), 4) AS r_squared
FROM covs
UNION ALL
SELECT 'form (last-6 pts/90)',
       CAST(n AS INTEGER),
       CASE WHEN cov_form >= 0 THEN 'more points when in form' ELSE 'fewer points when in form' END,
       ROUND(1.0 * cov_form * cov_form / (var_form * var_pts), 4)
FROM covs;
-- Expected answer (2 rows, 9,659 matches each):
--   fixture difficulty (easier = higher)   r_squared 0.0166
--   form (last-6 pts/90)                   r_squared 0.0020
-- So in this data, fixture difficulty lines up with match points a little more
-- than form does. Both numbers are tiny: one match is mostly luck.
-- Two things to keep in mind before you draw a conclusion:
--   * This only counts matches a player actually played (minutes > 0). The
--     forecast also asks "will he start?", which this test leaves out.
--   * A single average across all positions can hide differences between
--     goalkeepers, defenders, midfielders and forwards (see open question 2).


-- ---------------------------------------------------------------------
-- 2. How often does the top expected-points player actually return 6+ points?
--
-- "Top expected-points player" = for each gameweek, the player with the
-- highest FPL prediction (ep_pre) in the past season. We then check what he
-- really scored. A "return" here means 6 or more points.
--
-- Only gameweeks where FPL's prediction is stored are used (the archive has
-- real predictions for just some gameweeks; the rest are NULL = missing).
-- If two players tie on the top prediction, we take the one with the lower
-- player_id so each gameweek counts once.
-- ---------------------------------------------------------------------
WITH gw_total AS (                   -- one row per player per gameweek (doubles are summed)
    SELECT season, gw, player_id,
           SUM(ep_pre)       AS ep,
           SUM(total_points) AS points
    FROM player_gw
    WHERE season = '2025-26' AND ep_pre IS NOT NULL
    GROUP BY season, gw, player_id
),
ranked AS (                          -- rank players inside each gameweek, best prediction first
    SELECT gw, player_id, ep, points,
           ROW_NUMBER() OVER (PARTITION BY gw ORDER BY ep DESC, player_id) AS rnk
    FROM gw_total
)
SELECT COUNT(*)                                             AS gameweeks_checked,
       SUM(CASE WHEN points >= 6 THEN 1 ELSE 0 END)         AS returned_6_plus,
       ROUND(100.0 * SUM(CASE WHEN points >= 6 THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_returned_6_plus,
       ROUND(AVG(ep), 2)                                    AS avg_predicted,
       ROUND(AVG(points), 2)                                AS avg_actual
FROM ranked
WHERE rnk = 1;
-- Expected answer (1 row): 11 gameweeks checked (GW 1-6, 8, 9, 24, 29, 38),
-- 9 of them returned 6+ points = 81.8 percent.
-- Average predicted 10.29 points, average actual 10.18.
-- Cautions:
--   * Eleven gameweeks is a tiny sample. Treat the percentage as a lead, not proof.
--   * Some predictions in the archive look high (for example 14.0 for one
--     defender in GW2). That is what the archive holds; we did not change it.
--   * This uses every gameweek that has stored predictions, including GW 1-5.
--     The backtest report scores from GW6 only, so its row counts differ.


-- ---------------------------------------------------------------------
-- 3. Which teams' defenders keep the most clean sheets at home? (2025-26)
--
-- A clean sheet belongs to the whole team: it means the team conceded no
-- goals. The database has no goals or clean-sheet column, so we cannot count
-- them directly. Instead we use the goalkeeper as a stand-in for the defence.
--
-- The proxy: a goalkeeper who played 60+ minutes in a home match and scored
-- 6 or more points. Playing earns him 2 and a clean sheet adds 4, so 6+ usually
-- means a clean sheet. It is not perfect: a keeper can reach 6 through saves
-- and bonus points while still conceding. So read the result as "likely
-- clean sheets", not exact ones.
-- Open question 3 asks you to improve on this.
-- ---------------------------------------------------------------------
SELECT t.name                                              AS team,
       COUNT(*)                                            AS home_matches,
       SUM(CASE WHEN g.total_points >= 6 THEN 1 ELSE 0 END) AS likely_clean_sheets,
       ROUND(100.0 * SUM(CASE WHEN g.total_points >= 6 THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_home_clean_sheets
FROM player_gw AS g
JOIN player AS p ON p.season = g.season AND p.player_id = g.player_id
JOIN fixture AS f ON f.season = g.season AND f.fixture_id = g.fixture_id
JOIN team AS t ON t.season = f.season AND t.team_id = f.team_h
WHERE g.season = '2025-26'
  AND p.position = 'GK'
  AND g.was_home = 1
  AND g.minutes >= 60
GROUP BY t.team_id, t.name
ORDER BY pct_home_clean_sheets DESC, likely_clean_sheets DESC;
-- Expected answer (20 rows, one per team, best first):
--   top: Arsenal 11 of 19 home matches (57.9 percent), then Man City 9 (47.4),
--        then Sunderland 8 (42.1).  bottom: Spurs 2 of 19 (10.5 percent).
-- Nott'm Forest shows 18 matches, not 19: in one of their 19 home matches no
-- goalkeeper has 60+ minutes in the data, so that match is left out.


-- =====================================================================
-- OPEN QUESTIONS (not answered here. These are yours.)
--
-- 1. Do premium players (cost above 9.0m) return more points per million
--    than budget players (under 5.5m)? Hint: player_snapshot.now_cost is in
--    tenths of a million, so 90 means 9.0m.
--
-- 2. Does a player's form (last-6 pts/90) predict his NEXT gameweek better
--    for midfielders than for defenders? Hint: reuse query 1, add
--    p.position from the player table and GROUP BY it.
--
-- 3. Can you build a better clean-sheet measure for query 3? Hint: the
--    fixture table has team_h, team_a and finished. Think about which
--    column you would need to add, and what API data would fill it.
-- =====================================================================

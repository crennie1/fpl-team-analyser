-- =====================================================================
-- Squad metrics, relative grades and projection, as SQL views.
--
-- v_squad_metrics  one row per squad in squad_pick ('user' and 'ref:<entry>')
--   attack    = sum of xp_next over starting FWD
--   midfield  = sum of xp_next over starting MID
--   defence   = sum of xp_next over starting DEF and GK
--   fixtures  = mean FDR of the starters' fixtures, next_gw .. next_gw + 4 (lower is better)
--   risk      = share of the starters' xp_next from flagged players (lower is better)
--               flagged = status not 'a', or chance_next < 75, or start_prob < 0.6
--   bench     = sum of xp_next over the non-starters
--   projected = starters' xp_next + the captain's xp_next again (no auto-subs)
--   projected3 = the same over xp_next3 (the next three gameweeks); not graded
--
-- v_squad_grades   each non-reference squad ranked against the reference
--   squads of the current season: percentile (ruling R15), then a letter.
--
-- Forecast source: xp_next_cache is a snapshot of v_xp_next, refreshed by
-- db.refresh_xp_cache after each data load (collect, history, reference,
-- backtest) and when the app opens the database. It is a table, not a view,
-- because the full forecast chain is too slow to rerun on every squad edit.
--
-- View chain:  v_squad_pick_xp + v_squad_fixtures -> v_squad_metrics -> v_squad_area_value -> v_squad_grades
-- =====================================================================

DROP VIEW IF EXISTS v_squad_grades;
DROP VIEW IF EXISTS v_squad_area_value;
DROP VIEW IF EXISTS v_squad_metrics;
DROP VIEW IF EXISTS v_squad_fixtures;
DROP VIEW IF EXISTS v_squad_pick_xp;


-- One row per squad pick with the player's position, expected points and risk flag.
CREATE VIEW v_squad_pick_xp AS
WITH xp AS MATERIALIZED (   -- read the forecast cache once, not once per pick
    SELECT player_id, xp_next, xp_next3, start_prob FROM xp_next_cache
)
SELECT sp.squad_id, sp.player_id, sp.slot, sp.is_starter, sp.is_captain,
       pl.position,
       pl.team_id,
       COALESCE(x.xp_next, 0.0) AS xp_next,
       COALESCE(x.xp_next3, 0.0) AS xp_next3,
       -- flagged: injured/doubtful, FPL chance below 75%, or unlikely to start
       CASE WHEN COALESCE(sn.status, 'a') <> 'a'
              OR COALESCE(sn.chance_next, 100) < 75
              OR COALESCE(x.start_prob, 1.0) < 0.6
            THEN 1 ELSE 0 END AS is_flagged
FROM squad_pick AS sp
JOIN player AS pl
  ON pl.player_id = sp.player_id
 AND pl.season = (SELECT value FROM meta WHERE key = 'current_season')
LEFT JOIN xp AS x ON x.player_id = sp.player_id
LEFT JOIN v_latest_snapshot AS sn ON sn.player_id = sp.player_id;


-- Mean difficulty (FDR) of each squad's starters' fixtures over the next 5 gameweeks.
CREATE VIEW v_squad_fixtures AS
SELECT sp.squad_id, AVG(tf.fdr) AS fixtures
FROM squad_pick AS sp
JOIN v_target_fixture AS tf
  ON tf.player_id = sp.player_id
 AND tf.season = (SELECT value FROM meta WHERE key = 'current_season')
 AND tf.gw BETWEEN (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
               AND (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw') + 4
WHERE sp.is_starter = 1
GROUP BY sp.squad_id;


CREATE VIEW v_squad_metrics AS
WITH sums AS (       -- all the xp_next sums in one pass over the picks
    SELECT squad_id,
           SUM(CASE WHEN is_starter = 1 AND position = 'FWD'          THEN xp_next ELSE 0 END) AS attack,
           SUM(CASE WHEN is_starter = 1 AND position = 'MID'          THEN xp_next ELSE 0 END) AS midfield,
           SUM(CASE WHEN is_starter = 1 AND position IN ('DEF', 'GK') THEN xp_next ELSE 0 END) AS defence,
           SUM(CASE WHEN is_starter = 0                               THEN xp_next ELSE 0 END) AS bench,
           SUM(CASE WHEN is_starter = 1                               THEN xp_next ELSE 0 END) AS starters_xp,
           SUM(CASE WHEN is_starter = 1 AND is_flagged = 1            THEN xp_next ELSE 0 END) AS flagged_xp,
           SUM(CASE WHEN is_captain = 1                               THEN xp_next ELSE 0 END) AS captain_xp,
           SUM(CASE WHEN is_starter = 1                               THEN xp_next3 ELSE 0 END) AS starters_xp3,
           SUM(CASE WHEN is_captain = 1                               THEN xp_next3 ELSE 0 END) AS captain_xp3
    FROM v_squad_pick_xp
    GROUP BY squad_id
)
SELECT s.squad_id,
       s.attack,
       s.midfield,
       s.defence,
       f.fixtures,
       CASE WHEN s.starters_xp > 0 THEN s.flagged_xp / s.starters_xp ELSE 0.0 END AS risk,
       s.bench,
       s.starters_xp + s.captain_xp AS projected,    -- captain counts double
       s.starters_xp3 + s.captain_xp3 AS projected3
FROM sums AS s
LEFT JOIN v_squad_fixtures AS f ON f.squad_id = s.squad_id;


-- Metrics in long form: one row per (squad, area), so every area is graded the same way.
-- higher_is_better is 0 for fixtures and risk. (One pass over v_squad_metrics.)
CREATE VIEW v_squad_area_value AS
SELECT m.squad_id, a.area, a.higher_is_better,
       CASE a.area WHEN 'attack'    THEN m.attack
                   WHEN 'midfield'  THEN m.midfield
                   WHEN 'defence'   THEN m.defence
                   WHEN 'fixtures'  THEN m.fixtures
                   WHEN 'risk'      THEN m.risk
                   WHEN 'bench'     THEN m.bench
                   WHEN 'projected' THEN m.projected END AS value
FROM v_squad_metrics AS m
CROSS JOIN (
    SELECT 'attack' AS area, 1 AS higher_is_better
    UNION ALL SELECT 'midfield', 1
    UNION ALL SELECT 'defence',  1
    UNION ALL SELECT 'fixtures', 0
    UNION ALL SELECT 'risk',     0
    UNION ALL SELECT 'bench',    1
    UNION ALL SELECT 'projected', 1
) AS a;


CREATE VIEW v_squad_grades AS
WITH refs AS (       -- reference squads of the current season
    SELECT squad_id FROM reference_squad
    WHERE season = (SELECT value FROM meta WHERE key = 'current_season')
),
area_values AS MATERIALIZED (SELECT * FROM v_squad_area_value),   -- computed once
ref_values AS (
    SELECT v.area, v.value
    FROM area_values AS v
    JOIN refs ON refs.squad_id = v.squad_id
),
ref_count AS (
    SELECT area, COUNT(*) AS n FROM ref_values GROUP BY area
),
ranked AS (          -- for each graded squad: how many refs are strictly worse / equal
    SELECT u.squad_id, u.area, u.value, c.n,
           SUM(CASE WHEN (u.higher_is_better = 1 AND r.value < u.value)
                      OR (u.higher_is_better = 0 AND r.value > u.value) THEN 1 ELSE 0 END) AS worse,
           SUM(CASE WHEN r.value = u.value THEN 1 ELSE 0 END) AS equal
    FROM area_values AS u
    JOIN ref_count AS c ON c.area = u.area
    JOIN ref_values AS r ON r.area = u.area
    WHERE u.squad_id NOT IN (SELECT squad_id FROM refs)
      AND u.value IS NOT NULL
    GROUP BY u.squad_id, u.area, u.value, c.n
),
with_pct AS (        -- percentile (R15): ties count half
    SELECT squad_id, area, value,
           100.0 * (worse + 0.5 * equal) / n AS pct
    FROM ranked
)
SELECT squad_id, area, value, pct,
       CASE WHEN pct >= 80 THEN 'A'
            WHEN pct >= 60 THEN 'B'
            WHEN pct >= 40 THEN 'C'
            WHEN pct >= 20 THEN 'D'
            ELSE 'E' END AS grade
FROM with_pct;

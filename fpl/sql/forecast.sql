-- =====================================================================
-- Expected-points forecast, built as a chain of SQL views.
--
-- expected points for a fixture =
--     start_prob × pts_per_90 × fdr multiplier
-- start_prob   = minutes in last 5 GWs / 450, capped at 1,
--                then × chance_of_playing_next_round/100 when FPL gives one
-- pts_per_90   = total points per 90 minutes over the last 6 GWs (needs ≥ 180 min);
--                otherwise the position average pts_per_90 for that season
-- fdr mult     = (average points per 90 for that position at that FDR) ÷
--                (average points per 90 for that position overall), from the past season
--
-- View chain (each one builds on the one above it):
--   v_fdr_multiplier  -> how much each difficulty rating shifts a player's output
--   v_last_gw         -> last loaded gameweek before each as_of_gw
--   v_position_avg    -> fallback points per 90 for players with too little data
--   v_player_form     -> start_prob and pts_per_90 as at a given gameweek
--   v_xp              -> expected points per player per target gameweek
--   v_xp_next         -> the numbers the app shows for the coming gameweek
--
-- "as_of_gw = N" always means: use only gameweeks BEFORE N. Windows count back
-- from the last LOADED gameweek (a gameweek in progress is not yet loaded) and
-- are by gameweek number, not row count, because a player has no row for a
-- gameweek his team blanks in.
-- =====================================================================

-- Leftover view from an earlier version of this file; no longer defined.
DROP VIEW IF EXISTS v_player_gw_agg;
DROP VIEW IF EXISTS v_xp_next;
DROP VIEW IF EXISTS v_last5_next;
DROP VIEW IF EXISTS v_xp;
DROP VIEW IF EXISTS v_xp_fixture;
DROP VIEW IF EXISTS v_target_fixture;
DROP VIEW IF EXISTS v_player_form;
DROP VIEW IF EXISTS v_position_avg;
DROP VIEW IF EXISTS v_last_gw;
DROP VIEW IF EXISTS v_fdr_multiplier;
DROP VIEW IF EXISTS v_latest_snapshot;
DROP VIEW IF EXISTS v_as_of_grid;


-- Every (season, as_of_gw) we can forecast from: each gameweek that has fixtures.
CREATE VIEW v_as_of_grid AS
SELECT DISTINCT season, gw AS as_of_gw
FROM fixture
WHERE gw IS NOT NULL;


-- Most recent snapshot per player for the current season only.
CREATE VIEW v_latest_snapshot AS
SELECT s.*
FROM player_snapshot AS s
WHERE s.season = (SELECT value FROM meta WHERE key = 'current_season')
  AND s.gw = (SELECT MAX(s2.gw) FROM player_snapshot AS s2
              WHERE s2.season = s.season AND s2.player_id = s.player_id);


-- FDR multiplier = points per 90 at that FDR / points per 90 overall,
-- per position. Fitted on meta.fit_season (the season before the backtest
-- season, so the backtest is honest), falling back to backtest_season when only
-- one history season is loaded; then applied to every season.
-- Only rows where the player actually played count.
CREATE VIEW v_fdr_multiplier AS
WITH played AS (
    SELECT pl.position, g.fdr, g.minutes, g.total_points
    FROM player_gw AS g
    JOIN player AS pl ON pl.season = g.season AND pl.player_id = g.player_id
    WHERE g.season = (SELECT COALESCE(MAX(CASE WHEN key = 'fit_season' THEN value END),
                             MAX(CASE WHEN key = 'backtest_season' THEN value END))
                      FROM meta)
      AND g.minutes > 0
      AND g.fdr IS NOT NULL
),
by_fdr AS (          -- points per 90 at each (position, fdr)
    SELECT position, fdr, 90.0 * SUM(total_points) / SUM(minutes) AS pts90
    FROM played
    GROUP BY position, fdr
),
overall AS (         -- points per 90 for the position as a whole
    SELECT position, 90.0 * SUM(total_points) / SUM(minutes) AS pts90
    FROM played
    GROUP BY position
)
SELECT (SELECT COALESCE(MAX(CASE WHEN key = 'fit_season' THEN value END),
                        MAX(CASE WHEN key = 'backtest_season' THEN value END))
        FROM meta) AS season,
       f.position,
       f.fdr,
       f.pts90 / o.pts90 AS mult
FROM by_fdr AS f
JOIN overall AS o ON o.position = f.position
WHERE o.pts90 > 0;


-- Last loaded gameweek before each as_of_gw (ruling R12). The collector loads
-- only finished gameweeks, so a gameweek in progress has no player_gw rows and
-- must not be counted as zero minutes. Windows count back from this gameweek.
CREATE VIEW v_last_gw AS
SELECT gr.season, gr.as_of_gw,
       (SELECT MAX(g.gw) FROM player_gw AS g
        WHERE g.season = gr.season AND g.gw < gr.as_of_gw) AS last_gw
FROM v_as_of_grid AS gr;


-- Fallback rate: points per 90 for each position, as at each as_of_gw.
-- Uses only gameweeks before as_of_gw, so it never sees the future.
-- NULL at as_of_gw 1 (no history); harmless because start_prob is 0 there.
CREATE VIEW v_position_avg AS
WITH per_gw AS (     -- totals per season, position and gameweek
    SELECT g.season, pl.position, g.gw,
           SUM(g.minutes) AS minutes, SUM(g.total_points) AS points
    FROM player_gw AS g
    JOIN player AS pl ON pl.season = g.season AND pl.player_id = g.player_id
    WHERE g.minutes > 0
    GROUP BY g.season, pl.position, g.gw
)
SELECT gr.season, p.position, gr.as_of_gw,
       90.0 * SUM(p.points) / SUM(p.minutes) AS pts_per_90
FROM v_as_of_grid AS gr
JOIN per_gw AS p ON p.season = gr.season AND p.gw < gr.as_of_gw
GROUP BY gr.season, p.position, gr.as_of_gw;


-- Form of each player as at each gameweek, using past gameweeks only.
CREATE VIEW v_player_form AS
WITH windows AS (
    -- Join each (player, as_of_gw) to that player's gameweeks counting back
    -- from last_gw (R12): points window last_gw-5..last_gw, minutes window
    -- last_gw-4..last_gw. The window is by gameweek NUMBER, so a double
    -- gameweek (two rows) adds both fixtures and a blank adds nothing.
    SELECT pl.season, pl.player_id, pl.position, gr.as_of_gw,
           COALESCE(SUM(a.minutes), 0)      AS minutes_last6,
           COALESCE(SUM(a.total_points), 0) AS points_last6,
           COALESCE(SUM(CASE WHEN a.gw >= lg.last_gw - 4 THEN a.minutes END), 0)
               AS minutes_last5
    FROM player AS pl
    JOIN v_as_of_grid AS gr ON gr.season = pl.season
    JOIN v_last_gw AS lg ON lg.season = gr.season AND lg.as_of_gw = gr.as_of_gw
    LEFT JOIN player_gw AS a
           ON a.season = pl.season
          AND a.player_id = pl.player_id
          AND a.gw BETWEEN lg.last_gw - 5 AND lg.last_gw
    GROUP BY pl.season, pl.player_id, pl.position, gr.as_of_gw
),
base AS (
    SELECT w.season, w.player_id, w.as_of_gw, w.minutes_last5,
           -- own rate if he has played at least 180 minutes, else the position average
           CASE WHEN w.minutes_last6 >= 180
                THEN 90.0 * w.points_last6 / w.minutes_last6
                ELSE pa.pts_per_90 END AS pts_per_90,
           -- share of the last 5 loaded GWs' minutes, capped at 1
           MIN(1.0, w.minutes_last5 / 450.0) AS start_prob_base,
           -- FPL's chance of playing (R13: only for the upcoming gameweek itself)
           COALESCE(sn.chance_next / 100.0, 1.0) AS chance_factor
    FROM windows AS w
    LEFT JOIN v_position_avg AS pa
           ON pa.season = w.season AND pa.position = w.position
          AND pa.as_of_gw = w.as_of_gw
    LEFT JOIN v_latest_snapshot AS sn
           ON sn.season = w.season
          AND sn.player_id = w.player_id
          AND w.as_of_gw = (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
)
SELECT season, player_id, as_of_gw, pts_per_90,
       start_prob_base,                          -- unscaled, for gameweeks after as_of_gw
       chance_factor,
       start_prob_base * chance_factor AS start_prob,   -- for the as_of_gw itself
       minutes_last5
FROM base;


-- Fixtures a player has in a target gameweek, with the FDR from his side.
-- Ruling R11: if the player already has player_gw rows for that gameweek, use
-- them (correct club even after a mid-season move); otherwise use the
-- fixture table and the player's current team.
CREATE VIEW v_target_fixture AS
SELECT season, player_id, gw, fixture_id, fdr
FROM player_gw                                   -- already played
UNION ALL
SELECT pl.season, pl.player_id, f.gw, f.fixture_id,
       CASE WHEN f.team_h = pl.team_id THEN f.team_h_difficulty
            ELSE f.team_a_difficulty END
FROM player AS pl
JOIN fixture AS f
  ON f.season = pl.season AND pl.team_id IN (f.team_h, f.team_a)
WHERE NOT EXISTS (SELECT 1 FROM player_gw AS g
                  WHERE g.season = pl.season AND g.player_id = pl.player_id
                    AND g.gw = f.gw);


-- Expected points per fixture = start_prob × pts_per_90 × fdr multiplier.
-- Target gameweeks run from as_of_gw to as_of_gw + 2.
-- One row per (player, as_of_gw, target gw, fixture); gameweeks with no
-- fixture get one row with fixture_id NULL and xp 0.
CREATE VIEW v_xp_fixture AS
SELECT fm.season, fm.player_id, fm.as_of_gw, tg.as_of_gw AS gw, tf.fixture_id,
       CASE WHEN tf.fixture_id IS NULL THEN 0.0          -- blank gameweek
            ELSE COALESCE(fm.start_prob_base
                          * CASE WHEN tg.as_of_gw = fm.as_of_gw   -- chance_next: upcoming GW only (R13)
                                 THEN fm.chance_factor ELSE 1.0 END
                          * fm.pts_per_90 * COALESCE(m.mult, 1.0), 0.0)
       END AS xp
FROM v_player_form AS fm
JOIN player AS pl ON pl.season = fm.season AND pl.player_id = fm.player_id
JOIN v_as_of_grid AS tg                       -- the target gameweeks
  ON tg.season = fm.season
 AND tg.as_of_gw BETWEEN fm.as_of_gw AND fm.as_of_gw + 2
LEFT JOIN v_target_fixture AS tf
  ON tf.season = fm.season AND tf.player_id = fm.player_id AND tf.gw = tg.as_of_gw
LEFT JOIN v_fdr_multiplier AS m
  ON m.position = pl.position AND m.fdr = tf.fdr;


-- Expected points per player per target gameweek (blank -> 0, double -> sum).
CREATE VIEW v_xp AS
SELECT season, player_id, gw, as_of_gw, SUM(xp) AS xp_model
FROM v_xp_fixture
GROUP BY season, player_id, gw, as_of_gw;


-- Mean of each player's last 5 loaded gameweek totals before next_gw (current season;
-- gameweeks with a non-NULL total only, a double gameweek counting as one total).
-- The 'last5_avg' source of v_xp_next, and the app's "last-5 average" comparison.
CREATE VIEW v_last5_next AS
SELECT player_id, AVG(pts) AS avg5
FROM (SELECT player_id, pts,
             ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY gw DESC) AS rn
      FROM (SELECT player_id, gw, SUM(total_points) AS pts
            FROM player_gw
            WHERE season = (SELECT value FROM meta WHERE key = 'current_season')
              AND gw < (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
            GROUP BY player_id, gw)
      WHERE pts IS NOT NULL)
WHERE rn <= 5
GROUP BY player_id;


-- What the app shows: current season, upcoming gameweek.
--
-- In plain English: each horizon has its own source, chosen by the backtest
-- (meta.forecast_source_1gw for xp_next, meta.forecast_source_3gw for xp_next3;
-- an older meta.forecast_source is the fallback for both). FPL's own number is
-- never a source: a stored 'fpl_ep', or no setting at all, is read as 'v2'.
--   'v2'         forecast v2 (v_xp2_next, read through v_xp2_next_cached: the same SQL
--                over table xp2_fixture_next_cache, which db.refresh_xp_cache fills first,
--                so this view needs that table and is only as fresh as it).
--   'model'      the v1 SQL model.
--   'last5_avg'  the player's average total points over his last 5 loaded gameweeks
--                before next_gw (each gameweek's points added up, so a double gameweek
--                is one total), times his fixtures in next_gw (xp_next) or in
--                next_gw .. next_gw + 2 (xp_next3). A blank gameweek counts zero.
-- If the chosen source has no number for a player (no v2 row, a NULL v2 value, or no
-- earlier gameweeks for last5_avg), that player falls back to the model.
--
-- xp_source names what was actually used: 'v2', 'model' or 'last5_avg' when both horizons
-- agree, otherwise the 1-gameweek source then the 3-gameweek one, e.g. 'v2/model'.
-- defcon_chance and cs_chance are descriptive v2 numbers for the upcoming gameweek and
-- always show, whichever source is chosen. cs_display is the clean-sheet chance the app
-- shows: 1 - Π(1 - p) over a double gameweek's fixtures (cs_chance is their sum).
--
-- The season / next_gw filters are written as scalar subqueries on the views
-- below (not as joins to a CTE) so SQLite can push them down and only forecast
-- the one gameweek that is needed, instead of every gameweek of every season.
CREATE VIEW v_xp_next AS
WITH next3 AS (      -- sum of the model over next_gw .. next_gw + 2
    SELECT x.player_id,
           SUM(CASE WHEN x.gw = (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
                    THEN x.xp END) AS xp_model_next,
           SUM(x.xp)               AS xp_model_next3,
           SUM(CASE WHEN x.gw = (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
                    THEN x.fixture_id IS NOT NULL END) AS fixtures_next,
           SUM(x.fixture_id IS NOT NULL) AS fixtures_next3
    FROM v_xp_fixture AS x      -- same totals as v_xp, but SQLite can push the filters into it
    WHERE x.season = (SELECT value FROM meta WHERE key = 'current_season')
      AND x.as_of_gw = (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
      AND x.gw BETWEEN (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
                   AND (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw') + 2
    GROUP BY x.player_id
),
form AS (            -- start_prob for the upcoming gameweek only
    SELECT player_id, start_prob
    FROM v_player_form
    WHERE season = (SELECT value FROM meta WHERE key = 'current_season')
      AND as_of_gw = (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
),
last5 AS (           -- mean of his last 5 loaded gameweek totals before next_gw
    SELECT player_id, avg5 FROM v_last5_next
),
src AS (             -- 'fpl_ep' (old setting) or anything unknown or missing means v2
    SELECT CASE WHEN s1 IN ('model', 'last5_avg') THEN s1 ELSE 'v2' END AS s1,
           CASE WHEN s3 IN ('model', 'last5_avg') THEN s3 ELSE 'v2' END AS s3
    FROM (SELECT COALESCE((SELECT value FROM meta WHERE key = 'forecast_source_1gw'),
                          (SELECT value FROM meta WHERE key = 'forecast_source')) AS s1,
                 COALESCE((SELECT value FROM meta WHERE key = 'forecast_source_3gw'),
                          (SELECT value FROM meta WHERE key = 'forecast_source')) AS s3)
),
pick AS (            -- which number does each horizon use?
    SELECT n.*, l.avg5, v2.xp_v2_next, v2.xp_v2_next3, v2.defcon_chance_next, v2.cs_chance_next,
           v2.cs_display_next,
           (src.s1 = 'v2' AND v2.xp_v2_next IS NOT NULL) AS v1,
           (src.s3 = 'v2' AND v2.xp_v2_next3 IS NOT NULL) AS v3,
           (src.s1 = 'last5_avg' AND l.avg5 IS NOT NULL) AS l1,
           (src.s3 = 'last5_avg' AND l.avg5 IS NOT NULL) AS l3
    FROM next3 AS n
    CROSS JOIN src
    LEFT JOIN last5 AS l ON l.player_id = n.player_id
    LEFT JOIN v_xp2_next_cached AS v2 ON v2.player_id = n.player_id   -- v_xp2_next, cached
),
used AS (
    SELECT p.*,
           CASE WHEN p.l1 THEN 'last5_avg' WHEN p.v1 THEN 'v2' ELSE 'model' END AS used1,
           CASE WHEN p.l3 THEN 'last5_avg' WHEN p.v3 THEN 'v2' ELSE 'model' END AS used3
    FROM pick AS p
)
SELECT p.player_id,
       CASE p.used1 WHEN 'last5_avg' THEN p.avg5 * p.fixtures_next
            WHEN 'v2' THEN p.xp_v2_next ELSE p.xp_model_next END AS xp_next,
       CASE p.used3 WHEN 'last5_avg' THEN p.avg5 * p.fixtures_next3
            WHEN 'v2' THEN p.xp_v2_next3 ELSE p.xp_model_next3 END AS xp_next3,
       fm.start_prob,
       CASE WHEN p.used1 = p.used3 THEN p.used1 ELSE p.used1 || '/' || p.used3 END AS xp_source,
       p.defcon_chance_next AS defcon_chance,
       p.cs_chance_next AS cs_chance,
       p.cs_display_next AS cs_display
FROM used AS p
JOIN form AS fm ON fm.player_id = p.player_id;

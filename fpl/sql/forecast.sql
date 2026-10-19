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
--   v_position_avg    -> fallback points per 90 for players with too little data
--   v_player_form     -> start_prob and pts_per_90 as at a given gameweek
--   v_xp              -> expected points per player per target gameweek
--   v_xp_next         -> the numbers the app shows for the coming gameweek
--
-- "as_of_gw = N" always means: use only gameweeks BEFORE N (N-1 and earlier).
-- Windows are by gameweek number, not by row count, because a player has no
-- row for a gameweek his team blanks in.
-- =====================================================================

DROP VIEW IF EXISTS v_xp_next;
DROP VIEW IF EXISTS v_xp;
DROP VIEW IF EXISTS v_xp_fixture;
DROP VIEW IF EXISTS v_target_fixture;
DROP VIEW IF EXISTS v_player_form;
DROP VIEW IF EXISTS v_position_avg;
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
-- per position. Fitted on the backtest season (ruling R10), then applied
-- to every season. Only rows where the player actually played count.
CREATE VIEW v_fdr_multiplier AS
WITH played AS (
    SELECT pl.position, g.fdr, g.minutes, g.total_points
    FROM player_gw AS g
    JOIN player AS pl ON pl.season = g.season AND pl.player_id = g.player_id
    WHERE g.season = (SELECT value FROM meta WHERE key = 'backtest_season')
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
SELECT (SELECT value FROM meta WHERE key = 'backtest_season') AS season,
       f.position,
       f.fdr,
       f.pts90 / o.pts90 AS mult
FROM by_fdr AS f
JOIN overall AS o ON o.position = f.position
WHERE o.pts90 > 0;


-- Fallback rate: points per 90 for each position within each season.
CREATE VIEW v_position_avg AS
SELECT g.season,
       pl.position,
       90.0 * SUM(g.total_points) / SUM(g.minutes) AS pts_per_90
FROM player_gw AS g
JOIN player AS pl ON pl.season = g.season AND pl.player_id = g.player_id
WHERE g.minutes > 0
GROUP BY g.season, pl.position;


-- Form of each player as at each gameweek, using past gameweeks only.
CREATE VIEW v_player_form AS
WITH windows AS (
    -- Join each (player, as_of_gw) to that player's gameweeks in [as_of-6, as_of-1].
    -- The window is by gameweek NUMBER, so a double gameweek (two rows) just
    -- adds both fixtures' minutes and points, and a blank adds nothing.
    SELECT pl.season, pl.player_id, pl.position, gr.as_of_gw,
           COALESCE(SUM(a.minutes), 0)      AS minutes_last6,
           COALESCE(SUM(a.total_points), 0) AS points_last6,
           COALESCE(SUM(CASE WHEN a.gw >= gr.as_of_gw - 5 THEN a.minutes END), 0)
               AS minutes_last5
    FROM player AS pl
    JOIN v_as_of_grid AS gr ON gr.season = pl.season
    LEFT JOIN player_gw AS a
           ON a.season = pl.season
          AND a.player_id = pl.player_id
          AND a.gw BETWEEN gr.as_of_gw - 6 AND gr.as_of_gw - 1
    GROUP BY pl.season, pl.player_id, pl.position, gr.as_of_gw
)
SELECT w.season,
       w.player_id,
       w.as_of_gw,
       -- own rate if he has played at least 180 minutes, else the position average
       CASE WHEN w.minutes_last6 >= 180
            THEN 90.0 * w.points_last6 / w.minutes_last6
            ELSE pa.pts_per_90 END AS pts_per_90,
       -- share of the last 5 GWs' minutes, capped at 1,
       -- then scaled by FPL's chance of playing (current season, upcoming GW only)
       MIN(1.0, w.minutes_last5 / 450.0)
         * COALESCE(sn.chance_next / 100.0, 1.0) AS start_prob,
       w.minutes_last5 AS minutes_last5
FROM windows AS w
LEFT JOIN v_position_avg AS pa
       ON pa.season = w.season AND pa.position = w.position
LEFT JOIN v_latest_snapshot AS sn
       ON sn.season = w.season
      AND sn.player_id = w.player_id
      AND w.as_of_gw = (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw');


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
            ELSE COALESCE(fm.start_prob * fm.pts_per_90 * COALESCE(m.mult, 1.0), 0.0)
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


-- What the app shows: current season, upcoming gameweek.
-- xp_next uses FPL's own ep_next only when meta.forecast_source = 'fpl_ep'.
CREATE VIEW v_xp_next AS
WITH cfg AS (
    SELECT (SELECT value FROM meta WHERE key = 'current_season')            AS season,
           (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')  AS next_gw,
           COALESCE((SELECT value FROM meta WHERE key = 'forecast_source'), 'model')
                                                                            AS source
),
next3 AS (           -- sum of the model over next_gw .. next_gw + 2
    SELECT x.player_id,
           SUM(CASE WHEN x.gw = cfg.next_gw THEN x.xp_model END) AS xp_model_next,
           SUM(x.xp_model)                                       AS xp_next3
    FROM v_xp AS x, cfg
    WHERE x.season = cfg.season
      AND x.as_of_gw = cfg.next_gw
      AND x.gw BETWEEN cfg.next_gw AND cfg.next_gw + 2
    GROUP BY x.player_id
)
SELECT n.player_id,
       CASE WHEN cfg.source = 'fpl_ep' AND sn.ep_next IS NOT NULL
            THEN sn.ep_next ELSE n.xp_model_next END AS xp_next,
       n.xp_next3,
       fm.start_prob,
       CASE WHEN cfg.source = 'fpl_ep' AND sn.ep_next IS NOT NULL
            THEN 'fpl_ep' ELSE 'model' END AS xp_source
FROM next3 AS n
CROSS JOIN cfg
JOIN v_player_form AS fm
  ON fm.season = cfg.season AND fm.player_id = n.player_id AND fm.as_of_gw = cfg.next_gw
LEFT JOIN v_latest_snapshot AS sn ON sn.player_id = n.player_id;

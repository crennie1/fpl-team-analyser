-- =====================================================================
-- Forecast v2: expected points built from underlying stats (xG, xA, clean
-- sheets, DefCon) instead of past points per 90.
--
-- expected points for ONE fixture =
--   start_prob × [ 2                                   appearance points
--                + calib_att × (xg90 × GOAL_PTS + xa90 × 3) × opp_xg_ratio
--                                                       attacking returns
--                + CS_PTS × cs_chance                   clean-sheet points
--                + 2 × defcon_chance ]                  DefCon bonus
-- A double gameweek sums its fixtures; a blank gameweek is 0.
-- GOAL_PTS: GK 10, DEF 6, MID 5, FWD 4.   CS_PTS: GK/DEF 4, MID 1, FWD 0.
--
-- In plain English, component by component:
--  start_prob    Same as v1: share of the last 5 loaded gameweeks' minutes, capped at 1,
--                times FPL's chance_of_playing for the upcoming gameweek. It is how likely
--                he is to be on the pitch; every other part is "if he plays".
--  2             Points for playing 60+ minutes (assumed for anyone likely to start).
--  xg90, xa90    His expected goals and assists per 90 minutes over the last 6 loaded
--                gameweeks (chance quality, not luck). Under 180 minutes in the window we
--                use the position average instead, as v1 does for points. A goal is worth
--                GOAL_PTS and an assist 3, so xg90 × GOAL_PTS + xa90 × 3 is his typical
--                attacking haul per 90.
--  opp_xg_ratio  How leaky the opponent is to this position: xG that the opponent conceded
--                per match to players of his position, divided by the league average.
--                2.0 means "gives up twice the usual", 1.0 means average (also used when
--                there is no data yet). Ratios are clamped to [0.5, 2.0] so one freak match
--                cannot swing a forecast, and are set to 1.0 when the league average for
--                that position is under 0.05 a match (too rare to compare, e.g. FWD DefCon
--                or GK xG), because dividing by a near-zero average gives huge ratios (V4).
--  calib_att     A single fitted scale factor per position (table model_param, fitted on
--                fit_season by fpl.fit as actual / predicted attacking points; the
--                predicted side is column att_pred of v_xp2_fixture, so fit and forecast
--                cannot drift apart). 1.0 when there is no row.
--  cs_chance     Probability his team keeps a clean sheet. We model goals conceded as a
--                Poisson with mean λ, so P(0 goals) = exp(-λ), where
--                λ = own team's xG conceded per match (last 6) × opponent attack ratio
--                (opponent xG for per match ÷ league average).
--  defcon_chance Probability he reaches the DefCon threshold (DEF 10+, MID/FWD 12+ defensive
--                actions): his hit rate (last 6) × how many hits the opponent concedes to his
--                position relative to the league (defcon_ratio), capped at 0.95. The hit
--                rate is shrunk toward the position average, as if he had 3 extra
--                appearances at that average: (hits + 3 × avg rate) ÷ (apps + 3), so one
--                or two lucky games cannot read as near-certain (ruling V3). GKs have no DefCon (0). It is 0 whenever the data has no
--                DefCon fields (the 2024-25 season). Not fitted: it has no parameters.
--
-- Rules shared by every window below:
--  * "as_of_gw = N" uses only gameweeks BEFORE N: the last 6 loaded gameweeks, counted back
--    from v_last_gw.last_gw by gameweek number (same rule as v1), so there is no look-ahead.
--  * player_gw_stats is per gameweek, so a double gameweek is already summed. To tell which
--    opponent a double gameweek's xG / DefCon hits belong to, v_pf_stat splits the
--    gameweek's numbers between its fixtures in proportion to minutes played in each
--    (equal split if he played none). Points come per fixture, so they need no split.
--  * "per match" = per fixture the team played in the window.
--  * A double gameweek's DefCon chance is 1 - Π(1 - p) over its fixtures; its
--    clean-sheet chance and expected points are plain sums (the app displays the
--    clean-sheet chance as 1 - Π(1 - p) too: cs_display_next).
--
-- View chain:
--   v_pf_stat         one row per player per fixture played: points, split xG, split DefCon
--   v_team_gw, v_team_gw_pos   per gameweek team totals (helpers that keep the windows cheap)
--   v_team_conceded   per match, what players of each position scored AGAINST each team
--   v_team_xg         each team's xG for / against per match, and attack ratio vs league
--   v_opp_weakness    conceded stats as ratios to the league average (NULL -> 1.0)
--   v_player_threat   xg90, xa90, DefCon rate for each player
--   v_xp2_slot        a row per player and fixture (a blank gameweek has fixture_id NULL)
--   v_xp2_fixture     every component and the expected points, per fixture
--   v_cs_chance, v_defcon_chance, v_xp2   per player per gameweek
--   v_xp2_next        what the app shows (current season, upcoming gameweek)
--   v_xp2_breakdown_next  v_xp2_next's upcoming-gameweek number split into its four parts
--
-- SQL functions `exp` and `ln` come from SQLite's math functions (3.35+) or, where the
-- build lacks them, fpl.db.register_functions registers Python's math.exp / math.log (V1).
-- =====================================================================

DROP VIEW IF EXISTS v_xp2_breakdown_next;
DROP VIEW IF EXISTS v_xp2_next;
DROP VIEW IF EXISTS v_xp2;
DROP VIEW IF EXISTS v_defcon_chance;
DROP VIEW IF EXISTS v_cs_chance;
DROP VIEW IF EXISTS v_xp2_fixture;
DROP VIEW IF EXISTS v_xp2_slot;
DROP VIEW IF EXISTS v_player_threat;
DROP VIEW IF EXISTS v_opp_weakness;
DROP VIEW IF EXISTS v_team_xg;
DROP VIEW IF EXISTS v_team_conceded;
DROP VIEW IF EXISTS v_team_gw_pos;
DROP VIEW IF EXISTS v_team_gw;
DROP VIEW IF EXISTS v_pf_stat;

-- Speeds up the stats joins used below.
CREATE INDEX IF NOT EXISTS idx_pgs_player ON player_gw_stats (season, player_id, gw);
CREATE INDEX IF NOT EXISTS idx_pgs_gw ON player_gw_stats (season, gw);
CREATE INDEX IF NOT EXISTS idx_player_gw_gw ON player_gw (season, gw);


-- One row per player per fixture he has a player_gw row for (including 0 minutes).
CREATE VIEW v_pf_stat AS
WITH fixture_share AS (
    -- his share of the gameweek's minutes that came in this fixture (1.0 for a single)
    SELECT g.season, g.gw, g.player_id, g.fixture_id, g.was_home, g.opponent_team,
           g.total_points,
           COALESCE(g.minutes * 1.0 / NULLIF(SUM(g.minutes) OVER w, 0),
                    1.0 / COUNT(*) OVER w) AS share
    FROM player_gw AS g
    WINDOW w AS (PARTITION BY g.season, g.gw, g.player_id)
)
SELECT s.season, s.gw, s.fixture_id, s.player_id, pl.position,
       CASE WHEN s.was_home = 1 THEN f.team_h ELSE f.team_a END AS team_id,   -- his club that day
       s.opponent_team AS opp_id,
       s.total_points AS pts,
       s.share * st.xg AS xg,                         -- NULL without a stats row (unknown, not 0)
       s.share * st.defcon_hits AS defcon_hits       -- stays NULL when the season has no DefCon data
FROM fixture_share AS s
JOIN player AS pl ON pl.season = s.season AND pl.player_id = s.player_id
JOIN fixture AS f ON f.season = s.season AND f.fixture_id = s.fixture_id
LEFT JOIN player_gw_stats AS st
       ON st.season = s.season AND st.gw = s.gw AND st.player_id = s.player_id;


-- Per team and gameweek: matches played, xG its own players created (xg_for) and xG its
-- opponents' players created (xg_against). Aggregating per gameweek first keeps the
-- 6-gameweek windows below cheap.
CREATE VIEW v_team_gw AS
WITH per_fixture AS (    -- one row per team per fixture: the xG each side created
    SELECT season, gw, fixture_id, team_id, SUM(xg) AS xg_for,
           SUM(SUM(xg)) OVER (PARTITION BY season, fixture_id) - SUM(xg) AS xg_against
    FROM v_pf_stat
    GROUP BY season, gw, fixture_id, team_id
)
SELECT season, gw, team_id, COUNT(*) AS matches,
       SUM(xg_for) AS xg_for, SUM(xg_against) AS xg_against
FROM per_fixture
GROUP BY season, gw, team_id;


-- Per team, gameweek and position: what that position's players scored AGAINST the team.
-- Every position has a row for every gameweek the team played (0 when nothing scored).
CREATE VIEW v_team_gw_pos AS
WITH positions(position) AS (VALUES ('GK'), ('DEF'), ('MID'), ('FWD')),
against AS (
    SELECT season, gw, opp_id AS team_id, position,
           SUM(pts) AS pts, SUM(xg) AS xg, SUM(defcon_hits) AS defcon_hits
    FROM v_pf_stat
    GROUP BY season, gw, opp_id, position
)
SELECT m.season, m.gw, m.team_id, p.position, m.matches,
       COALESCE(a.pts, 0) AS pts,
       CASE WHEN a.team_id IS NULL THEN 0 ELSE a.xg END AS xg,   -- NULL: no stats rows
       a.defcon_hits
FROM v_team_gw AS m
CROSS JOIN positions AS p
LEFT JOIN against AS a
       ON a.season = m.season AND a.gw = m.gw AND a.team_id = m.team_id
      AND a.position = p.position;


-- What players of each position scored AGAINST each team, per match, in the last 6
-- loaded gameweeks before as_of_gw.
CREATE VIEW v_team_conceded AS
SELECT lg.season, c.team_id, lg.as_of_gw, c.position,
       SUM(c.pts) * 1.0 / SUM(c.matches) AS pts_pm,
       SUM(c.xg) / SUM(c.matches) AS xg_pm,
       SUM(c.defcon_hits) / SUM(c.matches) AS defcon_pm        -- NULL without DefCon data
FROM v_last_gw AS lg
JOIN v_team_gw_pos AS c
  ON c.season = lg.season AND c.gw BETWEEN lg.last_gw - 5 AND lg.last_gw
GROUP BY lg.season, c.team_id, lg.as_of_gw, c.position;


-- Each team's attack and defence in xG terms, per match, last 6 loaded gameweeks.
--   xg_for_pm  xG its own players created      xgc_pm  xG its opponents created
--   atk_ratio  xg_for_pm / league average (1.0 = average attack)
CREATE VIEW v_team_xg AS
WITH teams AS (
    SELECT season, team_h AS team_id FROM fixture
    UNION
    SELECT season, team_a FROM fixture
),
per_match AS (
    SELECT lg.season, lg.as_of_gw, t.team_id,
           SUM(t.xg_for) / SUM(t.matches) AS xg_for_pm,
           SUM(t.xg_against) / SUM(t.matches) AS xgc_pm
    FROM v_last_gw AS lg
    JOIN v_team_gw AS t
      ON t.season = lg.season AND t.gw BETWEEN lg.last_gw - 5 AND lg.last_gw
    GROUP BY lg.season, lg.as_of_gw, t.team_id
),
complete AS (            -- a row for every team and as_of_gw (NULLs where no matches yet)
    SELECT t.season, t.team_id, g.as_of_gw, p.xg_for_pm, p.xgc_pm
    FROM teams AS t
    JOIN v_as_of_grid AS g ON g.season = t.season
    LEFT JOIN per_match AS p
           ON p.season = t.season AND p.team_id = t.team_id AND p.as_of_gw = g.as_of_gw
)
SELECT season, team_id, as_of_gw, xg_for_pm, xgc_pm,
       xg_for_pm / NULLIF(AVG(xg_for_pm) OVER (PARTITION BY season, as_of_gw), 0) AS atk_ratio
FROM complete;


-- How generous each team is to each position, relative to the league average
-- (league average = mean over teams). 1.0 where there is nothing to compare.
-- Every (team, position, as_of_gw) has a row, so joins never drop a fixture.
CREATE VIEW v_opp_weakness AS
WITH teams AS (
    SELECT season, team_h AS team_id FROM fixture
    UNION
    SELECT season, team_a FROM fixture
),
positions(position) AS (VALUES ('GK'), ('DEF'), ('MID'), ('FWD')),
joined AS (
    SELECT t.season, t.team_id, g.as_of_gw, p.position, c.pts_pm, c.xg_pm, c.defcon_pm
    FROM teams AS t
    JOIN v_as_of_grid AS g ON g.season = t.season
    CROSS JOIN positions AS p
    LEFT JOIN v_team_conceded AS c
           ON c.season = t.season AND c.team_id = t.team_id
          AND c.as_of_gw = g.as_of_gw AND c.position = p.position
)
SELECT season, team_id, as_of_gw, position,
       -- ratio = team / league, but 1.0 if the league average is under 0.05 a match, else
       -- clamped to [0.5, 2.0] (ruling V4)
       COALESCE(MAX(0.5, MIN(2.0, pts_pm / CASE WHEN AVG(pts_pm) OVER lg >= 0.05
                                               THEN AVG(pts_pm) OVER lg END)), 1.0) AS pts_ratio,
       COALESCE(MAX(0.5, MIN(2.0, xg_pm / CASE WHEN AVG(xg_pm) OVER lg >= 0.05
                                              THEN AVG(xg_pm) OVER lg END)), 1.0) AS xg_ratio,
       COALESCE(MAX(0.5, MIN(2.0, defcon_pm / CASE WHEN AVG(defcon_pm) OVER lg >= 0.05
                                                  THEN AVG(defcon_pm) OVER lg END)), 1.0) AS defcon_ratio
FROM joined
WINDOW lg AS (PARTITION BY season, as_of_gw, position);   -- the league, for that position


-- Each player's underlying numbers, last 6 loaded gameweeks before as_of_gw.
--   xg90, xa90   per 90 minutes; position average if under 180 minutes in the window
--   defcon_rate  DefCon hit rate shrunk toward the position average (V3); NULL for a GK, with no appearances, or no data
--   defcon_hits, defcon_apps  the raw hits and appearances behind defcon_rate (NULL for a GK)
--   team_xgc_pm  xG his (current) team concedes per match
CREATE VIEW v_player_threat AS
WITH window_totals AS (
    SELECT pl.season, pl.player_id, pl.position, pl.team_id, gr.as_of_gw,
           COALESCE(SUM(s.minutes), 0) AS minutes,
           COALESCE(SUM(s.xg), 0) AS xg,
           COALESCE(SUM(s.xa), 0) AS xa,
           SUM(s.defcon_hits) AS hits,
           COALESCE(SUM(s.apps), 0) AS apps
    FROM player AS pl
    JOIN v_as_of_grid AS gr ON gr.season = pl.season
    JOIN v_last_gw AS lg ON lg.season = gr.season AND lg.as_of_gw = gr.as_of_gw
    LEFT JOIN player_gw_stats AS s
           ON s.season = pl.season AND s.player_id = pl.player_id
          AND s.gw BETWEEN lg.last_gw - 5 AND lg.last_gw
    GROUP BY pl.season, pl.player_id, pl.position, pl.team_id, gr.as_of_gw
),
with_position_avg AS (   -- position-average rates, the fallback for little game time
    SELECT w.*,
           90.0 * SUM(xg) OVER pos / NULLIF(SUM(minutes) OVER pos, 0) AS pos_xg90,
           90.0 * SUM(xa) OVER pos / NULLIF(SUM(minutes) OVER pos, 0) AS pos_xa90,
           SUM(hits) OVER pos * 1.0 / NULLIF(SUM(apps) OVER pos, 0) AS pos_defcon_rate
    FROM window_totals AS w
    WINDOW pos AS (PARTITION BY season, position, as_of_gw)
)
SELECT w.season, w.player_id, w.as_of_gw,
       CASE WHEN w.minutes >= 180 THEN 90.0 * w.xg / w.minutes ELSE w.pos_xg90 END AS xg90,
       CASE WHEN w.minutes >= 180 THEN 90.0 * w.xa / w.minutes ELSE w.pos_xa90 END AS xa90,
       CASE WHEN w.position = 'GK' OR w.apps = 0 THEN NULL
            ELSE (w.hits + 3 * w.pos_defcon_rate) / (w.apps + 3) END AS defcon_rate,
       CASE WHEN w.position = 'GK' THEN NULL ELSE w.hits END AS defcon_hits,
       CASE WHEN w.position = 'GK' THEN NULL ELSE w.apps END AS defcon_apps,
       tx.xgc_pm AS team_xgc_pm
FROM with_position_avg AS w
LEFT JOIN v_team_xg AS tx
       ON tx.season = w.season AND tx.team_id = w.team_id AND tx.as_of_gw = w.as_of_gw;


-- One row per player, as_of_gw, target gameweek (as_of_gw .. as_of_gw + 2) and fixture;
-- a blank gameweek is one row with fixture_id NULL. start_prob is his chance of playing
-- in that gameweek (chance_next applies to the upcoming gameweek only, R13, as in v1);
-- minutes_last5 is the minutes count it comes from (for the breakdown's reason line).
CREATE VIEW v_xp2_slot AS
WITH slots AS (
    SELECT fm.season, fm.player_id, fm.as_of_gw, tg.as_of_gw AS gw, tf.fixture_id,
           f.team_h, f.team_a,
           -- his club in that fixture: the one he played for if it is already played (so a
           -- mid-season move is handled), otherwise his current club
           CASE WHEN g.fixture_id IS NOT NULL
                THEN CASE WHEN g.was_home = 1 THEN f.team_h ELSE f.team_a END
                ELSE pl.team_id END AS team_id,
           fm.start_prob_base * CASE WHEN tg.as_of_gw = fm.as_of_gw
                                     THEN fm.chance_factor ELSE 1.0 END AS start_prob,
           fm.minutes_last5
    FROM v_player_form AS fm                -- CROSS JOIN: keep this join order (see header note)
    CROSS JOIN player AS pl ON pl.season = fm.season AND pl.player_id = fm.player_id
    CROSS JOIN v_as_of_grid AS tg
      ON tg.season = fm.season AND tg.as_of_gw BETWEEN fm.as_of_gw AND fm.as_of_gw + 2
    LEFT JOIN v_target_fixture AS tf       -- his fixtures that gameweek (R11); NULL = blank
           ON tf.season = fm.season AND tf.player_id = fm.player_id AND tf.gw = tg.as_of_gw
    LEFT JOIN fixture AS f ON f.season = tf.season AND f.fixture_id = tf.fixture_id
    LEFT JOIN player_gw AS g
           ON g.season = tf.season AND g.player_id = tf.player_id
          AND g.gw = tf.gw AND g.fixture_id = tf.fixture_id
)
SELECT season, player_id, as_of_gw, gw, fixture_id, team_id,
       CASE WHEN team_id = team_h THEN team_a ELSE team_h END AS opp_id,   -- the other side
       start_prob, minutes_last5
FROM slots;


-- Every component and the expected points, per fixture slot (see the formula at the top).
-- Written as two halves, played slots and blank slots, so that every join to the heavier
-- views is an inner join: only then can SQLite push a season / as_of_gw filter all the way
-- down and forecast one gameweek instead of every gameweek of every season.
-- app_pts, att_pts, cs_pts and defcon_pts are xp_v2's four terms, each times start_prob
-- (their sum is xp_v2 up to float rounding); the inputs behind them (xg90 .. defcon_apps,
-- minutes_last5, opp_id) are passed through for the app's breakdown (v_xp2_breakdown_next).
CREATE VIEW v_xp2_fixture AS
WITH components AS (
    SELECT s.season, s.player_id, s.as_of_gw, s.gw, s.fixture_id, pl.position,
           s.start_prob, s.minutes_last5, s.opp_id,
           th.xg90, th.xa90, th.defcon_hits, th.defcon_apps,
           ow.xg_ratio AS opp_xg_ratio, own.xgc_pm AS own_xgc_pm, opp.atk_ratio AS opp_atk_ratio,
           CASE pl.position WHEN 'MID' THEN 1 WHEN 'FWD' THEN 0 ELSE 4 END AS cs_pts_per,
           exp(-(own.xgc_pm * COALESCE(opp.atk_ratio, 1.0))) AS cs_chance,
           CASE WHEN th.defcon_rate IS NULL THEN 0.0
                ELSE MIN(0.95, th.defcon_rate * ow.defcon_ratio) END AS defcon_chance,
           -- attacking points: calibrated (goals + assists) x opponent leakiness
           COALESCE(mp.value, 1.0)
             * (COALESCE(th.xg90, 0) * CASE pl.position WHEN 'GK' THEN 10 WHEN 'MID' THEN 5 WHEN 'FWD' THEN 4 ELSE 6 END
                + COALESCE(th.xa90, 0) * 3)
             * ow.xg_ratio AS att_term,
           -- the same attacking term with calib 1.0: what fit.py calibrates against
           (COALESCE(th.xg90, 0) * CASE pl.position WHEN 'GK' THEN 10 WHEN 'MID' THEN 5 WHEN 'FWD' THEN 4 ELSE 6 END
                + COALESCE(th.xa90, 0) * 3)
             * ow.xg_ratio AS att_raw
    FROM v_xp2_slot AS s
    CROSS JOIN player AS pl ON pl.season = s.season AND pl.player_id = s.player_id
    CROSS JOIN v_player_threat AS th
      ON th.season = s.season AND th.player_id = s.player_id AND th.as_of_gw = s.as_of_gw
    CROSS JOIN v_opp_weakness AS ow
      ON ow.season = s.season AND ow.team_id = s.opp_id
     AND ow.as_of_gw = s.as_of_gw AND ow.position = pl.position
    CROSS JOIN v_team_xg AS own
      ON own.season = s.season AND own.team_id = s.team_id AND own.as_of_gw = s.as_of_gw
    CROSS JOIN v_team_xg AS opp
      ON opp.season = s.season AND opp.team_id = s.opp_id AND opp.as_of_gw = s.as_of_gw
    LEFT JOIN model_param AS mp ON mp.name = 'calib_att' AND mp.position = pl.position
    WHERE s.fixture_id IS NOT NULL
)
SELECT season, player_id, as_of_gw, gw, fixture_id, position, start_prob,
       cs_chance, defcon_chance,
       start_prob * ( 2.0 + att_term
                    + cs_pts_per * COALESCE(cs_chance, 0)
                    + 2.0 * defcon_chance ) AS xp_v2,
       start_prob * att_raw AS att_pred,     -- expected attacking points at calib 1.0 (for fit.py)
       start_prob * 2.0 AS app_pts,
       start_prob * att_term AS att_pts,
       start_prob * cs_pts_per * COALESCE(cs_chance, 0) AS cs_pts,
       start_prob * 2.0 * defcon_chance AS defcon_pts,
       minutes_last5, opp_id, xg90, xa90, opp_xg_ratio, own_xgc_pm, opp_atk_ratio,
       defcon_hits, defcon_apps
FROM components
UNION ALL                -- blank gameweeks score nothing
SELECT s.season, s.player_id, s.as_of_gw, s.gw, NULL, pl.position, s.start_prob,
       0.0, 0.0, 0.0, 0.0,
       0.0, 0.0, 0.0, 0.0,
       s.minutes_last5, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
FROM v_xp2_slot AS s
JOIN player AS pl ON pl.season = s.season AND pl.player_id = s.player_id
WHERE s.fixture_id IS NULL;


-- Clean-sheet chance per gameweek: sum over his fixtures (blank -> 0).
CREATE VIEW v_cs_chance AS
SELECT season, player_id, gw, as_of_gw, SUM(cs_chance) AS cs_chance
FROM v_xp2_fixture
GROUP BY season, player_id, gw, as_of_gw;


-- DefCon chance per gameweek: 1 - Π(1 - p) over his fixtures; blank or GK -> 0.
-- The product is taken as exp(Σ ln(1 - p)); p <= 0.95 keeps ln's argument above 0.
CREATE VIEW v_defcon_chance AS
SELECT season, player_id, gw, as_of_gw,
       1.0 - exp(SUM(ln(1.0 - defcon_chance))) AS defcon_chance
FROM v_xp2_fixture
GROUP BY season, player_id, gw, as_of_gw;


-- Expected points per player per target gameweek (blank -> 0, double -> sum).
CREATE VIEW v_xp2 AS
SELECT season, player_id, gw, as_of_gw, SUM(xp_v2) AS xp_v2
FROM v_xp2_fixture
GROUP BY season, player_id, gw, as_of_gw;


-- What the app shows: current season, upcoming gameweek (next_gw .. next_gw + 2 for
-- the 3-gameweek total). Filters are scalar subqueries so SQLite forecasts only that one
-- gameweek rather than every gameweek of every season.
CREATE VIEW v_xp2_next AS
SELECT player_id,
       SUM(CASE WHEN gw = (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
                THEN xp_v2 END) AS xp_v2_next,
       SUM(xp_v2) AS xp_v2_next3,
       -- DefCon chance in the upcoming gameweek: 1 - Π(1 - p), as in v_defcon_chance
       1.0 - exp(SUM(CASE WHEN gw = nxt THEN ln(1.0 - defcon_chance) END)) AS defcon_chance_next,
       SUM(CASE WHEN gw = nxt THEN cs_chance END) AS cs_chance_next,
       -- what the app shows as "Clean sheet %": P(at least one clean sheet) = 1 - Π(1 - p)
       -- (the sum above can pass 100% in a double gameweek; it stays the input to xP)
       CASE WHEN MAX(CASE WHEN gw = nxt THEN cs_chance END) >= 1.0 THEN 1.0
            ELSE 1.0 - exp(SUM(CASE WHEN gw = nxt THEN ln(1.0 - cs_chance) END)) END
         AS cs_display_next
FROM (SELECT *, (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw') AS nxt
      FROM v_xp2_fixture
      WHERE season = (SELECT value FROM meta WHERE key = 'current_season')
        AND as_of_gw = (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
        AND gw BETWEEN (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
                   AND (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw') + 2)
GROUP BY player_id;



-- The upcoming gameweek's v2 number split into the four parts the app explains, one row
-- per player (current season, as_of_gw = gw = next_gw; filters are scalar subqueries, as
-- in v_xp2_next, so SQLite forecasts that one gameweek only).
--   app_pts, att_pts, cs_pts, defcon_pts  v_xp2_fixture's parts (each x start_prob),
--                summed over the gameweek's fixtures; they add up to total (float rounding)
--   total        SUM(xp_v2), the same sum as v_xp2_next.xp_v2_next
--   n_fixtures   0 blank, 1, 2 double (the app's "2 games" note)
--   xg90 .. defcon_apps  the inputs, from his first fixture (by fixture_id); opponent
--                ratios and chances can differ in a double gameweek's second fixture
--   opp_short    opponents' short names, comma-joined in fixture_id order; NULL when blank
CREATE VIEW v_xp2_breakdown_next AS
WITH fx AS (
    SELECT x.*, t.short_name AS opp_name,
           ROW_NUMBER() OVER (PARTITION BY x.player_id ORDER BY x.fixture_id) AS rn
    FROM v_xp2_fixture AS x
    LEFT JOIN team AS t ON t.season = x.season AND t.team_id = x.opp_id
    WHERE x.season = (SELECT value FROM meta WHERE key = 'current_season')
      AND x.as_of_gw = (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
      AND x.gw = (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'next_gw')
)
SELECT player_id,
       COUNT(fixture_id) AS n_fixtures,
       MAX(start_prob) AS start_prob,
       MAX(minutes_last5) AS minutes_last5,
       SUM(app_pts) AS app_pts,
       SUM(att_pts) AS att_pts,
       SUM(cs_pts) AS cs_pts,
       SUM(defcon_pts) AS defcon_pts,
       SUM(xp_v2) AS total,
       MAX(CASE WHEN rn = 1 THEN xg90 END) AS xg90,
       MAX(CASE WHEN rn = 1 THEN xa90 END) AS xa90,
       MAX(CASE WHEN rn = 1 THEN opp_xg_ratio END) AS opp_xg_ratio,
       MAX(CASE WHEN rn = 1 THEN own_xgc_pm END) AS own_xgc_pm,
       MAX(CASE WHEN rn = 1 THEN opp_atk_ratio END) AS opp_atk_ratio,
       MAX(CASE WHEN rn = 1 AND fixture_id IS NOT NULL THEN cs_chance END) AS cs_chance,
       MAX(CASE WHEN rn = 1 AND fixture_id IS NOT NULL THEN defcon_chance END) AS defcon_chance,
       MAX(CASE WHEN rn = 1 THEN defcon_hits END) AS defcon_hits,
       MAX(CASE WHEN rn = 1 THEN defcon_apps END) AS defcon_apps,
       group_concat(opp_name, ', ') AS opp_short     -- fx rows arrive in rn order
FROM fx
GROUP BY player_id;

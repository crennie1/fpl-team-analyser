CREATE TABLE IF NOT EXISTS team (
    season TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    PRIMARY KEY (season, team_id)
);

CREATE TABLE IF NOT EXISTS player (
    season TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    web_name TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    position TEXT NOT NULL CHECK (position IN ('GK','DEF','MID','FWD')),
    first_name TEXT,
    second_name TEXT,
    PRIMARY KEY (season, player_id)
);

-- gw is the upcoming gameweek at collection time; latest collection wins.
CREATE TABLE IF NOT EXISTS player_snapshot (
    season TEXT NOT NULL,
    gw INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    collected_at TEXT NOT NULL,
    status TEXT,
    chance_next INTEGER,
    ep_next REAL,
    now_cost INTEGER,            -- tenths of GBP m, as FPL does
    selected_by_percent REAL,
    news TEXT,                   -- FPL's injury/availability text, NULL when none
    PRIMARY KEY (season, gw, player_id)
);

CREATE TABLE IF NOT EXISTS fixture (
    season TEXT NOT NULL,
    fixture_id INTEGER NOT NULL,
    gw INTEGER,
    team_h INTEGER NOT NULL,
    team_a INTEGER NOT NULL,
    team_h_difficulty INTEGER,
    team_a_difficulty INTEGER,
    finished INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (season, fixture_id)
);

-- One row per player per fixture. fdr is the difficulty from the player's side.
CREATE TABLE IF NOT EXISTS player_gw (
    season TEXT NOT NULL,
    gw INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    fixture_id INTEGER NOT NULL,
    minutes INTEGER,
    total_points INTEGER,
    was_home INTEGER,
    opponent_team INTEGER,
    fdr INTEGER,
    ep_pre REAL,
    PRIMARY KEY (season, gw, player_id, fixture_id)
);

-- One row per player per gameweek, summed over that gameweek's fixtures.
-- apps = fixtures with minutes > 0; defcon_hits = fixtures where the player hit his
-- position's DefCon threshold (NULL defcon_* when the source has no such data).
CREATE TABLE IF NOT EXISTS player_gw_stats (
    season TEXT NOT NULL,
    gw INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    minutes INTEGER,
    starts INTEGER,
    xg REAL,
    xa REAL,
    xgi REAL,
    xgc REAL,
    goals INTEGER,
    assists INTEGER,
    clean_sheets INTEGER,
    goals_conceded INTEGER,
    defcon_actions INTEGER,
    defcon_hits INTEGER,
    apps INTEGER,
    PRIMARY KEY (season, gw, player_id)
);

-- Latest set-piece duties snapshot only (1 = first choice).
CREATE TABLE IF NOT EXISTS set_piece (
    season TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    penalties_order INTEGER,
    corners_order INTEGER,
    direct_fk_order INTEGER,
    collected_at TEXT,
    PRIMARY KEY (season, player_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Speeds up per-player lookups used by the forecast views.
CREATE INDEX IF NOT EXISTS idx_player_gw_player ON player_gw (season, player_id, gw);
CREATE INDEX IF NOT EXISTS idx_fixture_gw ON fixture (season, gw);
CREATE INDEX IF NOT EXISTS idx_snapshot_player ON player_snapshot (season, player_id, gw);

-- Squads: 'ref:<entry_id>' rows are the weekly reference sample; the app adds 'user'.
CREATE TABLE IF NOT EXISTS squad_pick (
    squad_id TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    is_starter INTEGER NOT NULL,
    is_captain INTEGER NOT NULL,
    PRIMARY KEY (squad_id, slot)
);

CREATE TABLE IF NOT EXISTS reference_squad (
    season TEXT NOT NULL,
    gw INTEGER NOT NULL,
    squad_id TEXT NOT NULL,
    entry_id INTEGER NOT NULL,
    PRIMARY KEY (season, squad_id)
);

-- Forecast snapshot: a copy of v_xp_next taken after each data load by
-- db.refresh_xp_cache. The squad views read this table so the app is fast.
CREATE TABLE IF NOT EXISTS xp_next_cache (
    player_id INTEGER PRIMARY KEY,
    xp_next REAL,
    xp_next3 REAL,
    start_prob REAL,
    xp_source TEXT
);

-- Fitted forecast parameters (written by the backtest fit; a missing row means factor 1.0).
-- e.g. name 'calib_att', position 'MID': scales the xG/xA part of forecast v2.
CREATE TABLE IF NOT EXISTS model_param (
    name TEXT NOT NULL,
    position TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (name, position)
);

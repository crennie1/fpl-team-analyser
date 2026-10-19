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

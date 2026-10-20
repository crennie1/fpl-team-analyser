# Analysis workspace

This folder is your workspace. Write your own SQL here, keep your notes here, and save your findings here. The app and the daily refresh never touch this folder, so nothing you do here can break them.

## What is in here

| File | What it is |
|---|---|
| `data_dictionary.md` | Plain-English guide to every table and view in the database. Start here. |
| `starter_queries.sql` | Three worked example queries with the answers to expect, plus three open questions for you. |

## The database

All the data is in one file: `data/fpl.db`. It is a SQLite database. It holds two past seasons (2024-25 and 2025-26), the current season (2026-27) and the forecast, built as SQL views.

**Tip:** the refresh job changes this file every day. Work on a copy if you want to be safe, or open it read-only (see below).

## Open it in DB Browser for SQLite (free, with buttons)

1. Download DB Browser for SQLite from https://sqlitebrowser.org (free).
2. Open it. Choose **Open Database**. Pick `data/fpl.db`. To be safe, use **File > Open Database Read Only** instead.
3. The **Database Structure** tab lists all tables and views.
4. The **Browse Data** tab shows rows. Pick a table or view from the drop-down.
5. The **Execute SQL** tab is where you write queries. Type or paste one, select it, then press Ctrl+Return (Cmd+Return on a Mac).

## Open it in the command line

On a Mac, `sqlite3` is already installed. In Terminal, go to the project folder and run:

```
sqlite3 -readonly data/fpl.db
```

Handy commands inside it:

```
.tables                      -- list tables and views
.schema player_gw            -- show how one table is built
.headers on                  -- show column names
.mode column                 -- line the output up
SELECT * FROM v_xp_next ORDER BY xp_next DESC LIMIT 10;
.quit                        -- leave
```

You can also run a whole file:

```
sqlite3 -readonly -header -column data/fpl.db < analysis/starter_queries.sql
```

## Good habits

- Always `LIMIT` a query while you are exploring (for example `LIMIT 20`). Some tables have tens of thousands of rows.
- Run starter queries one at a time and compare your answer with the comment under each.
- Note that command-line `sqlite3` has no square-root function. The starter queries avoid it on purpose.
- Write down what you find and why it might be wrong. That is what you will talk about in interviews.

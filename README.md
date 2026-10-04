# Page

Book tracking and recommendations. This repo holds the data pipeline that loads the full
[Open Library](https://openlibrary.org/developers/dumps) catalog into a local PostgreSQL 16.

Nothing from the dumps is discarded: `works`, `editions` and `authors` keep the full original
record in a `raw jsonb` column plus the dump `revision`; the typed columns are cleaned
conveniences extracted from it. Lines that cannot be parsed go to `logs/bad_lines.log`.

## Requirements (Windows)

- Python 3.11+
- Docker Desktop with the WSL2 backend (needs CPU virtualization enabled in the BIOS)
- About 100 GB free disk for the full run (about 13 GB of downloads plus the database)

## One-time setup (PowerShell)

```powershell
cd C:\javad\code\page
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env      # then edit .env: set the same password in POSTGRES_PASSWORD and DATABASE_URL
docker compose up -d
docker compose ps                # page-db should be Up
```

Postgres listens on **localhost:5433** (not 5432, to avoid clashing with a local install).
Open a SQL shell any time with: `docker exec -it page-db psql -U page -d page`

## Sample run (minutes) - do this first

```powershell
.\.venv\Scripts\python.exe scripts\download.py --sample      # first 100k lines of each dump (~40 MB)
.\.venv\Scripts\python.exe scripts\load.py --reset --sample  # drops and recreates tables, then loads
.\.venv\Scripts\python.exe scripts\clean.py                  # builds work_popularity
.\.venv\Scripts\python.exe scripts\build_indexes.py          # indexes + catalog view
.\.venv\Scripts\python.exe scripts\validate.py
```

The sample's works and editions cover different key ranges, so searches and the catalog count
are only meaningful after the full load.

## Full run (hours)

```powershell
.\.venv\Scripts\python.exe scripts\download.py               # ~12.7 GB, asks to confirm, resumable
.\.venv\Scripts\python.exe scripts\load.py --reset
.\.venv\Scripts\python.exe scripts\clean.py
.\.venv\Scripts\python.exe scripts\build_indexes.py
.\.venv\Scripts\python.exe scripts\validate.py
```

- If a download is interrupted, run the same command again: it resumes from the `.part` file.
- Keep the files in `data/` so you can reload without downloading again.
- Dumps are regenerated monthly. To refresh, delete the old `.gz` files, re-download and reload.

## Layout

| Path | Purpose |
|---|---|
| `docker-compose.yml`, `.env.example` | Postgres 16, tuned for bulk loading |
| `scripts/download.py` | Resumable downloads with progress; `--sample` streams only the first lines |
| `scripts/load.py` | Streams each `.gz` line by line, cleans, loads with `COPY` |
| `scripts/clean.py` | Rebuilds `work_popularity` from ratings and the reading log |
| `scripts/build_indexes.py` | Runs `sql/indexes.sql` then `sql/views.sql`, then `ANALYZE` |
| `scripts/validate.py` | Row counts, catalog size, sample searches, ISBN lookup, top 20 |
| `sql/schema.sql` | Tables |
| `sql/indexes.sql` | ISBN, author, full-text and trigram (`pg_trgm`) indexes |
| `sql/views.sql` | `catalog` materialized view: the books worth showing |

## Cleaning rules

- **ISBNs**: hyphens and spaces stripped, trailing `x` uppercased, only well-formed 10/13 digit values kept, de-duplicated. Originals remain in `raw`.
- **Descriptions**: a plain string or a `{type, value}` object becomes plain text.
- **Publish dates**: the first 4-digit year between 1000 and next year; the original string is kept in `publish_date_raw`.
- **Subjects**: lowercased, whitespace collapsed, de-duplicated; kept per kind (subject / place / person / time).
- **Covers**: `-1` (removed) filtered out. URL: `https://covers.openlibrary.org/b/id/{cover_id}-M.jpg`
- **Shelves**: `want-to-read`, `currently-reading`, `already-read`; any other shelf is kept as a lowercase slug.

## Popularity

`work_popularity` has the rating count, average rating, and want-to-read / currently-reading /
already-read counts per work. `popularity_score` is their sum (every rating or shelf add counts once).

## Catalog

`catalog` lists works that have a non-blank title, at least one author, and at least one edition
with an ISBN or a cover (or a work-level cover). Refresh after a reload with
`REFRESH MATERIALIZED VIEW CONCURRENTLY catalog;` (`build_indexes.py` recreates it).

## Troubleshooting

- `docker compose up` fails with a 500 error: Docker Desktop's engine is not running. Start it and wait for "Engine running".
- "Virtualization support not detected": enable Intel VT-x / AMD-V in the BIOS.
- `wsl --update` reports `REGDB_E_CLASSNOTREG`: let it repair WSL when prompted, then restart.

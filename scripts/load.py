"""Stream Open Library dumps into Postgres with COPY.

  python scripts/load.py --sample            # data/sample/*.gz (first 100k lines each)
  python scripts/load.py                     # full dumps from data/
  python scripts/load.py --reset --sample    # drop all tables, recreate, then load
  python scripts/load.py --only works authors

Files are read line by line (never fully in memory). Cleaning happens here; rows that
can't be parsed are written to logs/bad_lines.log and loading continues.
"""
import argparse
import gzip
import json
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from tqdm import tqdm

import common as c

SAMPLE_LINES = 100_000
BATCH = 20_000  # records per COPY flush

TABLE_COLS = {
    "authors": ["key", "name", "birth_date", "death_date", "revision", "last_modified", "raw"],
    "works": ["key", "title", "subtitle", "description", "first_publish_year", "cover_id",
              "covers", "revision", "last_modified", "raw"],
    "work_authors": ["work_key", "author_key"],
    "work_subjects": ["work_key", "kind", "subject"],
    "editions": ["key", "work_key", "title", "isbn_10", "isbn_13", "pages", "publish_date_raw",
                 "publish_year", "language", "publisher", "cover_id", "covers", "revision",
                 "last_modified", "raw"],
    "edition_authors": ["edition_key", "author_key"],
    "ratings": ["work_key", "edition_key", "rating", "rated_on"],
    "reading_log": ["work_key", "edition_key", "shelf", "logged_on"],
}
ALL_TABLES = list(TABLE_COLS) + ["work_popularity"]

SHELVES = {
    "want to read": "want-to-read",
    "currently reading": "currently-reading",
    "already read": "already-read",
}


class BadLine(Exception):
    pass


# ------------------------------------------------------------------ parsing

def split_ol(line: bytes):
    """type, key, revision, last_modified, json  ->  (key, revision, last_modified, dict, raw_json_text)"""
    parts = line.rstrip(b"\r\n").split(b"\t", 4)
    if len(parts) != 5:
        raise BadLine(f"expected 5 columns, got {len(parts)}")
    _type, key, rev, lm, js = (p.decode("utf-8") for p in parts)
    js = js.replace("\\u0000", "")  # jsonb cannot store NUL
    try:
        d = json.loads(js)
    except json.JSONDecodeError as e:
        raise BadLine(f"bad json: {e}")
    if not isinstance(d, dict):
        raise BadLine("json is not an object")
    try:
        revision = int(rev)
    except ValueError:
        revision = None
    try:
        datetime.fromisoformat(lm)
        last_modified = lm
    except ValueError:
        last_modified = None
    return key, revision, last_modified, d, js


def handle_author(line: bytes):
    key, rev, lm, d, js = split_ol(line)
    yield "authors", (key, c.text(d.get("name")), c.text(d.get("birth_date")),
                      c.text(d.get("death_date")), rev, lm, js)


SUBJECT_FIELDS = (("subject", "subjects"), ("place", "subject_places"),
                  ("person", "subject_people"), ("time", "subject_times"))


def handle_work(line: bytes):
    key, rev, lm, d, js = split_ol(line)
    cov = c.covers(d.get("covers"))
    yield "works", (key, c.text(d.get("title")), c.text(d.get("subtitle")),
                    c.description(d.get("description")),
                    c.year(d.get("first_publish_date")),
                    cov[0] if cov else None, cov, rev, lm, js)

    seen = set()
    for a in d.get("authors") or []:
        ak = c.key_of(a.get("author")) if isinstance(a, dict) else None
        if ak and ak not in seen:
            seen.add(ak)
            yield "work_authors", (key, ak)

    seen = set()
    for kind, field in SUBJECT_FIELDS:
        for s in d.get(field) or []:
            s = c.subject(s)
            if s and (kind, s) not in seen:
                seen.add((kind, s))
                yield "work_subjects", (key, kind, s)


def handle_edition(line: bytes):
    key, rev, lm, d, js = split_ol(line)
    works = d.get("works") or []
    work_key = c.key_of(works[0]) if works else None
    langs = d.get("languages") or []
    lang = c.key_of(langs[0]) if langs else None
    lang = lang.rsplit("/", 1)[-1] if lang else None
    pubs = d.get("publishers") or []
    pub = c.text(pubs[0]) if pubs and isinstance(pubs[0], str) else None
    pdate = c.text(d.get("publish_date"))
    cov = c.covers(d.get("covers"))
    yield "editions", (key, work_key, c.text(d.get("title")),
                       c.isbn10s(d.get("isbn_10")), c.isbn13s(d.get("isbn_13")),
                       c.pages(d.get("number_of_pages")), pdate, c.year(pdate),
                       lang, pub, cov[0] if cov else None, cov, rev, lm, js)

    seen = set()
    for a in d.get("authors") or []:
        ak = c.key_of(a)
        if ak and ak not in seen:
            seen.add(ak)
            yield "edition_authors", (key, ak)


def _nullable(v: str):
    return None if v == "\\N" or v == "" else v


def handle_rating(line: bytes):
    parts = line.decode("utf-8").rstrip("\r\n").split("\t")
    if len(parts) != 4:
        raise BadLine(f"expected 4 columns, got {len(parts)}")
    work, ed, rating, when = parts
    try:
        r = int(rating)
    except ValueError:
        raise BadLine("rating not an integer")
    if not 1 <= r <= 5:
        raise BadLine(f"rating out of range: {r}")
    yield "ratings", (work, _nullable(ed), r, c.parse_date(when))


def handle_reading_log(line: bytes):
    parts = line.decode("utf-8").rstrip("\r\n").split("\t")
    if len(parts) != 4:
        raise BadLine(f"expected 4 columns, got {len(parts)}")
    work, ed, shelf, when = parts
    shelf_n = shelf.strip().lower()
    if not shelf_n:
        raise BadLine("empty shelf")
    shelf_n = SHELVES.get(shelf_n) or shelf_n.replace(" ", "-")  # keep unknown shelves too
    yield "reading_log", (work, _nullable(ed), shelf_n, c.parse_date(when))


DUMPS = {
    # name: (filename, handler, tables it fills)
    "authors": ("ol_dump_authors_latest.txt.gz", handle_author, ["authors"]),
    "works": ("ol_dump_works_latest.txt.gz", handle_work, ["works", "work_authors", "work_subjects"]),
    "editions": ("ol_dump_editions_latest.txt.gz", handle_edition, ["editions", "edition_authors"]),
    "ratings": ("ol_dump_ratings_latest.txt.gz", handle_rating, ["ratings"]),
    "reading-log": ("ol_dump_reading-log_latest.txt.gz", handle_reading_log, ["reading_log"]),
}


# ------------------------------------------------------------------ loading

def copy_rows(conn, table, rows):
    cols = ", ".join(TABLE_COLS[table])
    with conn.cursor() as cur, cur.copy(f"COPY {table} ({cols}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)


def flush(conn, buf, bad, source, counts):
    """COPY each table's buffered rows. If a batch is rejected, retry row by row."""
    for table, rows in buf.items():
        if not rows:
            continue
        try:
            with conn.transaction():
                copy_rows(conn, table, rows)
            counts[table] = counts.get(table, 0) + len(rows)
        except psycopg.Error as e:
            c_log.warning("%s: batch COPY into %s failed (%s); retrying row by row",
                          source, table, str(e).splitlines()[0])
            for r in rows:
                try:
                    with conn.transaction():
                        copy_rows(conn, table, [r])
                    counts[table] = counts.get(table, 0) + 1
                except psycopg.Error as e2:
                    bad.add(f"{source}:{table}", 0, "db: " + str(e2).splitlines()[0], repr(r))
        rows.clear()


def load_dump(conn, name, path: Path, limit, bad, append):
    _, handler, tables = DUMPS[name]
    source = path.name
    if not append:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE " + ", ".join(tables))
    buf = {t: [] for t in tables}
    counts, n_lines, n_bad, pending = {}, 0, 0, 0

    with gzip.open(path, "rb") as fh, tqdm(total=limit, unit="line", desc=name,
                                           unit_scale=True, mininterval=2) as bar:
        for lineno, line in enumerate(fh, 1):
            if limit and lineno > limit:
                break
            n_lines = lineno
            try:
                for table, row in handler(line):
                    buf[table].append(row)
            except BadLine as e:
                n_bad += 1
                bad.add(source, lineno, str(e), line)
            except Exception as e:  # never crash on one line
                n_bad += 1
                bad.add(source, lineno, f"{type(e).__name__}: {e}", line)
            pending += 1
            bar.update(1)
            if pending >= BATCH:
                flush(conn, buf, bad, source, counts)
                pending = 0
        flush(conn, buf, bad, source, counts)
    conn.commit()
    c_log.info("%s: %s lines read, %s bad, loaded %s", name, f"{n_lines:,}", n_bad,
               {t: f"{v:,}" for t, v in counts.items()})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", action="store_true", help="read data/sample and cap at --lines per file")
    ap.add_argument("--lines", type=int, default=SAMPLE_LINES)
    ap.add_argument("--only", nargs="+", choices=DUMPS)
    ap.add_argument("--reset", action="store_true", help="drop ALL tables and recreate schema first")
    ap.add_argument("--append", action="store_true", help="don't truncate target tables before loading")
    args = ap.parse_args()

    global c_log
    c_log = c.get_logger("load")
    base = c.DATA_DIR / "sample" if args.sample else c.DATA_DIR
    limit = args.lines if args.sample else None
    names = args.only or list(DUMPS)

    missing = [DUMPS[n][0] for n in names if not (base / DUMPS[n][0]).exists()]
    if missing:
        sys.exit(f"Missing files in {base}: {', '.join(missing)} (run download.py first)")

    bad = c.BadLines()
    with c.connect() as conn:
        with conn.cursor() as cur:
            if args.reset:
                cur.execute("DROP TABLE IF EXISTS " + ", ".join(ALL_TABLES) + " CASCADE")
                c_log.info("dropped all tables")
            cur.execute((c.SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
        conn.commit()
        for name in names:
            load_dump(conn, name, base / DUMPS[name][0], limit, bad, args.append)
    bad.close()
    c_log.info("done; %s bad lines (see logs/bad_lines.log)", f"{bad.count:,}")


if __name__ == "__main__":
    main()

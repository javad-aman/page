"""Build indexes (sql/indexes.sql), then the catalog view (sql/views.sql), then ANALYZE.

  python scripts/build_indexes.py
  python scripts/build_indexes.py --skip-views

Each statement runs on its own and is timed, so a long index build is visible.
Safe to re-run: indexes use IF NOT EXISTS and the view is dropped and recreated.
"""
import argparse
import re
import time

import common as c

log = c.get_logger("indexes")


def statements(path):
    sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
    return [s.strip() for s in sql.split(";") if s.strip()]


def run(cur, stmts):
    for s in stmts:
        label = " ".join(s.split())[:90]
        t = time.time()
        cur.execute(s)
        log.info("%6.1fs  %s", time.time() - t, label)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-views", action="store_true")
    args = ap.parse_args()

    with c.connect(autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET maintenance_work_mem = '2GB'")
        cur.execute("SET max_parallel_maintenance_workers = 4")
        run(cur, statements(c.SQL_DIR / "indexes.sql"))
        if not args.skip_views:
            run(cur, statements(c.SQL_DIR / "views.sql"))
        t = time.time()
        cur.execute("ANALYZE")
        log.info("%6.1fs  ANALYZE", time.time() - t)


if __name__ == "__main__":
    main()

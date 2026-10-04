"""Post-load derived data: rebuild work_popularity from ratings + reading_log.

Per-record cleaning (ISBNs, descriptions, years, subjects) already happened in load.py.
Run order: load.py -> clean.py -> build_indexes.py -> validate.py
"""
import time

import common as c

log = c.get_logger("clean")

POPULARITY_SQL = """
INSERT INTO work_popularity
    (work_key, rating_count, avg_rating, want_to_read, currently_reading, already_read)
SELECT COALESCE(r.work_key, l.work_key),
       COALESCE(r.n, 0),
       round(r.avg::numeric, 2),
       COALESCE(l.want, 0),
       COALESCE(l.reading, 0),
       COALESCE(l.done, 0)
FROM (SELECT work_key, count(*) AS n, avg(rating) AS avg
        FROM ratings GROUP BY work_key) r
FULL OUTER JOIN
     (SELECT work_key,
             count(*) FILTER (WHERE shelf = 'want-to-read')      AS want,
             count(*) FILTER (WHERE shelf = 'currently-reading') AS reading,
             count(*) FILTER (WHERE shelf = 'already-read')      AS done
        FROM reading_log GROUP BY work_key) l
  ON l.work_key = r.work_key
"""


def main():
    with c.connect() as conn, conn.cursor() as cur:
        t = time.time()
        cur.execute("TRUNCATE work_popularity")
        cur.execute(POPULARITY_SQL)
        log.info("work_popularity: %s rows (%.1fs)", f"{cur.rowcount:,}", time.time() - t)
        conn.commit()


if __name__ == "__main__":
    main()

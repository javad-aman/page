"""Validate the load: counts, searches, ISBN lookup, popularity ranking.

  python scripts/validate.py
"""
import common as c

COVER = "https://covers.openlibrary.org/b/id/{}-M.jpg"
TABLES = ["works", "editions", "authors", "work_authors", "edition_authors",
          "work_subjects", "ratings", "reading_log", "work_popularity"]
SEARCHES = ["project hail mary", "dune", "the midnight library"]
ISBN = "9780593135204"

# title, authors, year and cover for a work, falling back to its editions
WORK_COLS = """
    w.key, w.title,
    (SELECT string_agg(a.name, ', ') FROM (
        SELECT a.name FROM work_authors wa JOIN authors a ON a.key = wa.author_key
         WHERE wa.work_key = w.key LIMIT 3) a) AS authors,
    COALESCE(w.first_publish_year,
             (SELECT min(e.publish_year) FROM editions e WHERE e.work_key = w.key)) AS year,
    COALESCE(w.cover_id,
             (SELECT e.cover_id FROM editions e
               WHERE e.work_key = w.key AND e.cover_id IS NOT NULL LIMIT 1)) AS cover_id
"""

SEARCH_SQL = f"""
SELECT {WORK_COLS}, COALESCE(p.popularity_score, 0) AS score
FROM works w LEFT JOIN work_popularity p ON p.work_key = w.key
WHERE to_tsvector('simple', coalesce(w.title, '')) @@ websearch_to_tsquery('simple', %(q)s)
ORDER BY (lower(w.title) = lower(%(q)s)) DESC, score DESC
LIMIT 5
"""

ISBN_SQL = f"""
SELECT e.key AS edition, e.title, e.isbn_10, e.isbn_13, e.pages, e.publish_year,
       e.language, e.publisher, e.cover_id AS edition_cover, {WORK_COLS}
FROM editions e LEFT JOIN works w ON w.key = e.work_key
WHERE e.isbn_13 @> ARRAY[%(i)s] OR e.isbn_10 @> ARRAY[%(i)s]
"""

TOP_SQL = f"""
SELECT {WORK_COLS}, p.rating_count, p.avg_rating, p.want_to_read,
       p.currently_reading, p.already_read, p.popularity_score
FROM work_popularity p JOIN works w ON w.key = p.work_key
ORDER BY p.popularity_score DESC
LIMIT 20
"""


def show(rows, cols, widths=None):
    if not rows:
        print("  (no rows)")
        return
    out = [[("" if v is None else str(v)) for v in r] for r in rows]
    w = [min(widths[i] if widths else 40, max(len(cols[i]), *(len(r[i]) for r in out)))
         for i in range(len(cols))]
    print("  " + "  ".join(h.ljust(w[i]) for i, h in enumerate(cols)))
    for r in out:
        print("  " + "  ".join(v[:w[i]].ljust(w[i]) for i, v in enumerate(r)))


def main():
    with c.connect() as conn, conn.cursor() as cur:
        print("== Row counts")
        rows = []
        for t in TABLES:
            cur.execute(f"SELECT count(*) FROM {t}")
            rows.append((t, f"{cur.fetchone()[0]:,}"))
        cur.execute("SELECT count(*) FROM editions WHERE work_key IS NULL")
        rows.append(("editions without work", f"{cur.fetchone()[0]:,}"))
        cur.execute("SELECT count(*) FROM (SELECT 1 FROM work_subjects "
                    "GROUP BY work_key, kind, subject HAVING count(*) > 1) d")
        rows.append(("duplicate subjects (want 0)", f"{cur.fetchone()[0]:,}"))
        show(rows, ["table", "rows"])

        print("\n== Catalog")
        try:
            cur.execute("SELECT count(*) FROM catalog")
            n = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM works")
            total = cur.fetchone()[0]
            print(f"  {n:,} of {total:,} works pass ({100 * n / max(total, 1):.1f}%)")
        except Exception as e:
            conn.rollback()
            print("  catalog view missing (run build_indexes.py):", str(e).splitlines()[0])

        for q in SEARCHES:
            print(f"\n== Search: {q!r}")
            cur.execute(SEARCH_SQL, {"q": q})
            show([(r[1], r[2], r[3], COVER.format(r[4]) if r[4] else None, r[5])
                  for r in cur.fetchall()],
                 ["title", "author", "year", "cover", "score"], [45, 30, 6, 52, 6])

        print(f"\n== ISBN {ISBN}")
        cur.execute(ISBN_SQL, {"i": ISBN})
        cols = [d.name for d in cur.description]
        for r in cur.fetchall():
            for k, v in zip(cols, r):
                print(f"  {k:14s} {v}")
            cover = r[cols.index("cover_id")] or r[cols.index("edition_cover")]
            print(f"  {'cover_url':14s} {COVER.format(cover) if cover else None}")
        if not cur.rowcount:
            print("  (not found)")

        print("\n== Top 20 works by popularity")
        cur.execute(TOP_SQL)
        show([(r[1], r[2], r[5], r[6], r[7], r[8], r[9], r[10]) for r in cur.fetchall()],
             ["title", "author", "ratings", "avg", "want", "reading", "read", "score"],
             [40, 24, 7, 5, 6, 7, 6, 6])


if __name__ == "__main__":
    main()

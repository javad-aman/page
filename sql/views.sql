-- The books worth showing in the app. Materialized so app queries are fast;
-- refresh with:  REFRESH MATERIALIZED VIEW CONCURRENTLY catalog;
--
-- A work qualifies when it has
--   * a non-blank title,
--   * at least one author, and
--   * at least one edition, where the edition has an ISBN or a cover
--     (or the work itself has a cover).

DROP MATERIALIZED VIEW IF EXISTS catalog;

CREATE MATERIALIZED VIEW catalog AS
SELECT
    w.key,
    w.title,
    w.subtitle,
    w.description,
    COALESCE(w.first_publish_year,
             (SELECT min(e.publish_year) FROM editions e WHERE e.work_key = w.key)) AS year,
    COALESCE(w.cover_id,
             (SELECT e.cover_id FROM editions e
               WHERE e.work_key = w.key AND e.cover_id IS NOT NULL LIMIT 1)) AS cover_id
FROM works w
WHERE btrim(coalesce(w.title, '')) <> ''
  AND EXISTS (SELECT 1 FROM work_authors wa WHERE wa.work_key = w.key)
  AND EXISTS (SELECT 1 FROM editions e
               WHERE e.work_key = w.key
                 AND (cardinality(e.isbn_10) > 0 OR cardinality(e.isbn_13) > 0
                      OR e.cover_id IS NOT NULL OR w.cover_id IS NOT NULL));

CREATE UNIQUE INDEX catalog_key_idx ON catalog (key);

CREATE INDEX catalog_title_fts ON catalog USING gin (to_tsvector('simple', coalesce(title, '')));

CREATE INDEX catalog_title_trgm ON catalog USING gin (title gin_trgm_ops);

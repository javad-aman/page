-- Built AFTER loading. Safe to re-run (IF NOT EXISTS). One statement per blank-line-terminated
-- block; build_indexes.py runs them one at a time and times each.

-- uniqueness for link tables (loader already de-duplicates within each record)
CREATE UNIQUE INDEX IF NOT EXISTS work_authors_pk ON work_authors (work_key, author_key);

CREATE UNIQUE INDEX IF NOT EXISTS edition_authors_pk ON edition_authors (edition_key, author_key);

CREATE UNIQUE INDEX IF NOT EXISTS work_subjects_pk ON work_subjects (work_key, kind, subject);

-- joins and lookups
CREATE INDEX IF NOT EXISTS editions_work_key_idx ON editions (work_key);

CREATE INDEX IF NOT EXISTS work_authors_author_idx ON work_authors (author_key);

CREATE INDEX IF NOT EXISTS edition_authors_author_idx ON edition_authors (author_key);

CREATE INDEX IF NOT EXISTS work_subjects_subject_idx ON work_subjects (subject);

CREATE INDEX IF NOT EXISTS ratings_work_idx ON ratings (work_key);

CREATE INDEX IF NOT EXISTS reading_log_work_idx ON reading_log (work_key);

-- ISBN lookup: WHERE isbn_13 @> ARRAY['978...']
CREATE INDEX IF NOT EXISTS editions_isbn13_gin ON editions USING gin (isbn_13);

CREATE INDEX IF NOT EXISTS editions_isbn10_gin ON editions USING gin (isbn_10);

-- full-text search ('simple' config: books are multilingual, so no stemming/stop-words)
CREATE INDEX IF NOT EXISTS works_title_fts ON works USING gin (to_tsvector('simple', coalesce(title, '')));

CREATE INDEX IF NOT EXISTS authors_name_fts ON authors USING gin (to_tsvector('simple', coalesce(name, '')));

-- trigram search (typo-tolerant, ILIKE '%dune%', similarity)
CREATE INDEX IF NOT EXISTS works_title_trgm ON works USING gin (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS authors_name_trgm ON authors USING gin (name gin_trgm_ops);

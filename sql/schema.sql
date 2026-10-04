-- Tables only. Secondary indexes live in indexes.sql and are built AFTER loading
-- (much faster). Primary keys on the three big tables are kept here because
-- Open Library keys are unique; link tables get their PKs in indexes.sql after dedupe.
--
-- Nothing from the dumps is discarded: every works/editions/authors row keeps the
-- full original record in `raw` plus its dump `revision`. The typed columns are
-- cleaned conveniences extracted from it.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS authors (
    key           text PRIMARY KEY,          -- /authors/OL1A
    name          text,
    birth_date    text,
    death_date    text,
    revision      integer,
    last_modified timestamptz,
    raw           jsonb
);

CREATE TABLE IF NOT EXISTS works (
    key                 text PRIMARY KEY,    -- /works/OL1W
    title               text,
    subtitle            text,
    description         text,                -- plain text (string or {type,value} unwrapped)
    first_publish_year  integer,
    cover_id            bigint,              -- first valid cover
    covers              bigint[],            -- all valid covers
    revision            integer,
    last_modified       timestamptz,
    raw                 jsonb
);

CREATE TABLE IF NOT EXISTS editions (
    key               text PRIMARY KEY,      -- /books/OL1M
    work_key          text,                  -- NULL when the edition has no work
    title             text,
    isbn_10           text[],                -- normalized, de-duplicated
    isbn_13           text[],
    pages             integer,
    publish_date_raw  text,                  -- original messy string
    publish_year      integer,
    language          text,                  -- first language code, e.g. eng
    publisher         text,                  -- first publisher
    cover_id          bigint,
    covers            bigint[],
    revision          integer,
    last_modified     timestamptz,
    raw               jsonb
);

CREATE TABLE IF NOT EXISTS work_authors (
    work_key    text NOT NULL,
    author_key  text NOT NULL
);

-- authors credited on an edition itself (editions often carry authors the work lacks)
CREATE TABLE IF NOT EXISTS edition_authors (
    edition_key text NOT NULL,
    author_key  text NOT NULL
);

CREATE TABLE IF NOT EXISTS work_subjects (
    work_key  text NOT NULL,
    kind      text NOT NULL DEFAULT 'subject',  -- subject / place / person / time
    subject   text NOT NULL                     -- lowercased, trimmed
);

CREATE TABLE IF NOT EXISTS ratings (
    work_key     text NOT NULL,
    edition_key  text,
    rating       smallint NOT NULL,
    rated_on     date
);

CREATE TABLE IF NOT EXISTS reading_log (
    work_key     text NOT NULL,
    edition_key  text,
    shelf        text NOT NULL,              -- want-to-read / currently-reading / already-read
    logged_on    date
);

CREATE TABLE IF NOT EXISTS work_popularity (
    work_key           text PRIMARY KEY,
    rating_count       integer NOT NULL DEFAULT 0,
    avg_rating         numeric(3,2),
    want_to_read       integer NOT NULL DEFAULT 0,
    currently_reading  integer NOT NULL DEFAULT 0,
    already_read       integer NOT NULL DEFAULT 0,
    -- single ranking number: every rating and every shelf add counts as one signal
    popularity_score   integer GENERATED ALWAYS AS
        (rating_count + want_to_read + currently_reading + already_read) STORED
);

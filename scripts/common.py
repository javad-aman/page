"""Shared helpers: paths, DB connection, logging and the cleaning functions."""
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / os.getenv("DATA_DIR", "data")
LOG_DIR = ROOT / os.getenv("LOG_DIR", "logs")
SQL_DIR = ROOT / "sql"
DATABASE_URL = os.getenv("DATABASE_URL")


def connect(**kw) -> psycopg.Connection:
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL is not set (copy .env.example to .env)")
    return psycopg.connect(DATABASE_URL, **kw)


def get_logger(name: str = "page") -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(name)
    if not log.handlers:
        log.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        fh = logging.FileHandler(LOG_DIR / "pipeline.log", encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(fh)
        log.addHandler(sh)
    return log


class BadLines:
    """Appends rejected lines to logs/bad_lines.log instead of crashing."""

    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._f = open(LOG_DIR / "bad_lines.log", "a", encoding="utf-8")
        self.count = 0

    def add(self, source: str, lineno: int, reason: str, line: bytes | str):
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        self._f.write(f"{source}\t{lineno}\t{reason}\t{line[:500].rstrip()}\n")
        self.count += 1

    def close(self):
        self._f.close()


# ---------------------------------------------------------------- cleaning

_NUL = re.compile("\x00")
_WS = re.compile(r"\s+")


def text(v) -> str | None:
    """Trimmed string without NUL bytes (Postgres rejects them); None if empty."""
    if v is None:
        return None
    if not isinstance(v, str):
        v = str(v)
    v = _NUL.sub("", v).strip()
    return v or None


def description(v) -> str | None:
    """Descriptions are either a plain string or {"type": ..., "value": ...}."""
    if isinstance(v, dict):
        v = v.get("value")
    return text(v) if isinstance(v, str) else None


_ISBN_STRIP = re.compile(r"[^0-9Xx]")
_ISBN10 = re.compile(r"^\d{9}[\dX]$")
_ISBN13 = re.compile(r"^\d{13}$")


def isbns(values, pattern) -> list[str]:
    """Normalize (strip hyphens/spaces, uppercase X), keep well-formed, de-dupe in order."""
    out, seen = [], set()
    for v in values or []:
        if not isinstance(v, str):
            continue
        n = _ISBN_STRIP.sub("", v).upper()
        if pattern.match(n) and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def isbn10s(values):
    return isbns(values, _ISBN10)


def isbn13s(values):
    return isbns(values, _ISBN13)


_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_MAX_YEAR = date.today().year + 1


def year(v) -> int | None:
    """Pull a plausible 4-digit year out of messy dates ('c1995', '[1995]', 'May 3, 1995')."""
    if not isinstance(v, str):
        return None
    for m in _YEAR.finditer(v):
        y = int(m.group(1))
        if 1000 <= y <= _MAX_YEAR:
            return y
    return None


def covers(v) -> list[int]:
    """Valid cover ids only (Open Library uses -1 for removed covers)."""
    out = []
    for c in v or []:
        if isinstance(c, int) and not isinstance(c, bool) and c > 0 and c not in out:
            out.append(c)
    return out


def pages(v) -> int | None:
    if isinstance(v, int) and not isinstance(v, bool) and 0 < v < 100_000:
        return v
    return None


def subject(v) -> str | None:
    if isinstance(v, dict):
        v = v.get("name") or v.get("value")
    if not isinstance(v, str):
        return None
    v = _WS.sub(" ", _NUL.sub("", v)).strip().lower()
    return v or None


def key_of(v) -> str | None:
    """Reference to another record: {'key': '/x/OL1'} or already a string."""
    if isinstance(v, dict):
        v = v.get("key")
    return v if isinstance(v, str) and v.startswith("/") else None


def parse_date(v: str) -> date | None:
    try:
        return datetime.strptime(v[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None

"""Download Open Library dumps (resumable, with progress).

  python scripts/download.py --sample          # first 100k lines of each dump (small)
  python scripts/download.py                   # full dumps (asks before >1 GB)
  python scripts/download.py --only works authors
"""
import argparse
import gzip
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

BASE = "https://openlibrary.org/data/"
DUMPS = {
    "works": "ol_dump_works_latest.txt.gz",
    "editions": "ol_dump_editions_latest.txt.gz",
    "authors": "ol_dump_authors_latest.txt.gz",
    "ratings": "ol_dump_ratings_latest.txt.gz",
    "reading-log": "ol_dump_reading-log_latest.txt.gz",
}
SAMPLE_LINES = 100_000
CONFIRM_BYTES = 1 * 1024**3
CHUNK = 1024 * 1024
HEADERS = {"User-Agent": "page-pipeline/0.1 (personal book app)"}

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))


def remote_size(url: str) -> int | None:
    r = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=60)
    r.raise_for_status()
    n = r.headers.get("Content-Length")
    return int(n) if n else None


def download_sample(name: str, filename: str, lines: int) -> Path:
    """Stream the dump, keep only the first `lines` lines, write a small .gz."""
    out_dir = DATA_DIR / "sample"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / filename
    if out.exists():
        print(f"[skip] {out} already exists")
        return out
    tmp = out.with_suffix(out.suffix + ".part")
    url = BASE + filename
    with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
        r.raise_for_status()
        src = gzip.GzipFile(fileobj=r.raw)  # r.raw yields the still-compressed bytes
        n = 0
        with gzip.open(tmp, "wb") as dst, tqdm(total=lines, unit="line", desc=f"sample {name}") as bar:
            for line in src:
                dst.write(line)
                n += 1
                bar.update(1)
                if n >= lines:
                    break
    tmp.replace(out)
    print(f"[ok] {out} ({n:,} lines, {out.stat().st_size / 1e6:.1f} MB)")
    return out


def download_full(name: str, filename: str, retries: int = 8) -> Path:
    """Resumable download using HTTP Range requests."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / filename
    part = out.with_suffix(out.suffix + ".part")
    url = BASE + filename
    total = remote_size(url)

    if out.exists() and (total is None or out.stat().st_size == total):
        print(f"[skip] {out} already complete")
        return out

    for attempt in range(1, retries + 1):
        have = part.stat().st_size if part.exists() else 0
        if total is not None and have == total:
            break
        headers = dict(HEADERS)
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with requests.get(url, headers=headers, stream=True, timeout=60) as r:
                if r.status_code == 416:  # already have everything
                    break
                r.raise_for_status()
                if have and r.status_code != 206:  # server ignored Range: start over
                    have = 0
                mode = "ab" if have else "wb"
                with open(part, mode) as f, tqdm(
                    total=total, initial=have, unit="B", unit_scale=True,
                    unit_divisor=1024, desc=name,
                ) as bar:
                    for chunk in r.iter_content(CHUNK):
                        f.write(chunk)
                        bar.update(len(chunk))
            if total is None or part.stat().st_size == total:
                break
        except (requests.RequestException, OSError) as e:
            wait = min(60, 2 ** attempt)
            print(f"[retry {attempt}/{retries}] {name}: {e} (waiting {wait}s)", file=sys.stderr)
            time.sleep(wait)
    else:
        raise RuntimeError(f"{name}: gave up after {retries} attempts; rerun to resume")

    if total is not None and part.stat().st_size != total:
        raise RuntimeError(f"{name}: size mismatch ({part.stat().st_size} != {total}); rerun to resume")
    part.replace(out)
    print(f"[ok] {out} ({out.stat().st_size / 1e9:.2f} GB)")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", action="store_true", help=f"only the first {SAMPLE_LINES:,} lines of each dump")
    ap.add_argument("--lines", type=int, default=SAMPLE_LINES, help="line count for --sample")
    ap.add_argument("--only", nargs="+", choices=DUMPS, help="subset of dumps")
    ap.add_argument("--yes", action="store_true", help="skip the >1 GB confirmation")
    args = ap.parse_args()

    names = args.only or list(DUMPS)

    if args.sample:
        for name in names:
            download_sample(name, DUMPS[name], args.lines)
        return

    sizes = {n: remote_size(BASE + DUMPS[n]) for n in names}
    total = sum(s or 0 for s in sizes.values())
    for n in names:
        print(f"  {n:12s} {(sizes[n] or 0) / 1e9:6.2f} GB")
    print(f"  {'TOTAL':12s} {total / 1e9:6.2f} GB")
    if total > CONFIRM_BYTES and not args.yes:
        if input("Download over 1 GB. Continue? [y/N] ").strip().lower() != "y":
            print("Cancelled.")
            return
    for name in names:
        download_full(name, DUMPS[name])


if __name__ == "__main__":
    main()

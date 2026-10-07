"""Shared paths, constants and helpers for the moefIFSCivil import scripts."""

import datetime
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
LFS_DIR = ROOT / "LFS" / "moefIFSCivil"
PDFS_DIR = LFS_DIR / "pdfs"
DOCS_DIR = ROOT / "input" / "documents"

BASE_URL = "https://moef.gov.in"
CIVIL_LIST_PAGE_URL = f"{BASE_URL}/ifs-civil-list-2"
SET_LOCALE_URL = f"{BASE_URL}/set-locale"
USER_AGENT = "Mozilla/5.0"

MINISTRY = "Ministry of Environment, Forest and Climate Change, Government of India"
DEFAULT_HF_REPO_ID = "Orgpedia/moefIFSCivil"


def load_env():
    load_dotenv(ROOT / ".env")


def require_env(*names):
    values = [os.environ.get(n, "").strip() for n in names]
    missing = [n for n, v in zip(names, values) if not v]
    if missing:
        raise SystemExit(f"Missing environment variables: {', '.join(missing)} (set them in .env)")
    return values


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z%z")


def pdf_path(year):
    return PDFS_DIR / f"{year}.pdf"


def read_records(name):
    """Read input/documents/<name>.json as a dict keyed by year."""
    path = DOCS_DIR / f"{name}.json"
    if not path.exists():
        return {}
    return {r["year"]: r for r in json.loads(path.read_text())}


def write_records(name, records):
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCS_DIR / f"{name}.json"
    ordered = [records[y] for y in sorted(records)]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def sha1_file(path):
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def link_pdf(year):
    """Create/repair input/documents/<year>.pdf -> ../../LFS/moefIFSCivil/pdfs/<year>.pdf"""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    link = DOCS_DIR / f"{year}.pdf"
    target = os.path.relpath(pdf_path(year), DOCS_DIR)
    if link.is_symlink() and os.readlink(link) == target:
        return
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)

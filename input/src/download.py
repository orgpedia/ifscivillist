"""Download IFS Civil List PDFs that are missing from LFS/moefIFSCivil/pdfs.

Years come from the "Indian Forest Service - Civil List <year>" links on
moef.gov.in/ifs-civil-list-2. The site serves Hindi by default and the Hindi
page has no links, so the session first switches the locale to English.
Existing files are never re-downloaded; a warning is printed if the site now
links a different file for a year, or if the remote file changed.
"""

import re
import sys
import time
from html import unescape

import requests

from common import (
    BASE_URL,
    CIVIL_LIST_PAGE_URL,
    PDFS_DIR,
    SET_LOCALE_URL,
    USER_AGENT,
    link_pdf,
    pdf_path,
    read_records,
    sha1_file,
    utc_now,
    write_records,
)

RETRIES = 5
HEADERS = {"User-Agent": USER_AGENT}
LINK_RE = re.compile(r'<a\s[^>]*href="([^"]+\.pdf)"[^>]*>(.*?)</a>', re.I | re.S)
YEAR_RE = re.compile(r"Civil\s+List\s*[-,]?\s*(\d{4})", re.I)


def english_page(session):
    r = session.get(CIVIL_LIST_PAGE_URL, timeout=60)
    r.raise_for_status()
    m = re.search(r'name="_token" value="([^"]+)"', r.text)
    if not m:
        raise SystemExit(f"Could not find the locale form token on {CIVIL_LIST_PAGE_URL}")
    session.post(SET_LOCALE_URL, data={"_token": m.group(1), "locale": "en"}, timeout=60).raise_for_status()
    r = session.get(CIVIL_LIST_PAGE_URL, timeout=60)
    r.raise_for_status()
    return r.text


def get_year_urls(session):
    """Return {year: (url, title)} from the civil list links on the page."""
    year_urls = {}
    for href, text in LINK_RE.findall(english_page(session)):
        title = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text))).strip()
        m = YEAR_RE.search(title)
        if not m:
            continue
        url = href if href.startswith("http") else BASE_URL + href
        year = m.group(1)
        if year in year_urls and year_urls[year][0] != url:
            print(f"{year}: WARNING listed twice, keeping {year_urls[year][0]}, ignoring {url}")
            continue
        year_urls[year] = (url, title)
    if not year_urls:
        raise SystemExit(f"Could not find any civil list links on {CIVIL_LIST_PAGE_URL}")
    return year_urls


def total_size(r):
    if r.status_code == 206:
        m = re.search(r"/(\d+)$", r.headers.get("Content-Range", ""))
        return int(m.group(1)) if m else None
    length = r.headers.get("Content-Length")
    return int(length) if length else None


def fetch(session, url, dest):
    """Download url to dest via dest.part, resuming on retries. Returns (info, error)."""
    part = dest.with_name(dest.name + ".part")
    error = ""
    for attempt in range(1, RETRIES + 1):
        offset = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            with session.get(url, headers=headers, stream=True, timeout=120) as r:
                if r.status_code == 404:
                    return None, "not_found"
                if r.status_code == 416:  # stale .part, start over
                    part.unlink()
                    continue
                r.raise_for_status()
                if r.status_code == 200:
                    offset = 0  # server ignored Range
                total = total_size(r)
                last_modified = r.headers.get("Last-Modified")
                with part.open("ab" if offset else "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)

            size = part.stat().st_size
            if total and size != total:
                raise OSError(f"size mismatch {size} vs {total}")
            with part.open("rb") as f:
                if f.read(5) != b"%PDF-":
                    part.unlink()
                    raise OSError("not a PDF")
            part.replace(dest)
            return {"size": size, "last_modified": last_modified}, ""
        except (requests.RequestException, OSError) as e:
            error = str(e)
            print(f"\tattempt {attempt}/{RETRIES} failed: {error}")
            time.sleep(5 * attempt)
    return None, error


def check_remote(session, year, url, record):
    """Warn if the site now links a different file, or the remote file changed."""
    if record.get("url") != url:
        print(f"{year}: WARNING site now links {url} (have {record.get('url')}). Not re-downloading.")
        return False
    try:
        r = session.head(url, timeout=60, allow_redirects=True)
    except requests.RequestException as e:
        print(f"{year}: could not check remote ({e})")
        return False
    if r.status_code != 200:
        print(f"{year}: could not check remote (HTTP {r.status_code})")
        return False

    remote_size = int(r.headers.get("Content-Length") or 0) or None
    remote_lm = r.headers.get("Last-Modified")
    changed = False
    if remote_size and record.get("size") and remote_size != record["size"]:
        changed = True
    if remote_lm and record.get("last_modified") and remote_lm != record["last_modified"]:
        changed = True

    if changed:
        print(
            f"{year}: WARNING remote PDF has changed "
            f"(remote size={remote_size} last-modified={remote_lm}; "
            f"local size={record.get('size')} last-modified={record.get('last_modified')}). Not re-downloading."
        )
    elif remote_lm and not record.get("last_modified") and remote_size == record.get("size"):
        record["last_modified"] = remote_lm
        return True
    return False


def main():
    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    downloads = read_records("downloads")
    session = requests.Session()
    session.headers.update(HEADERS)
    year_urls = get_year_urls(session)
    print(f"*** {len(year_urls)} years on site: {sorted(year_urls)}")

    downloaded, skipped, failed = [], [], []
    for year, (url, title) in sorted(year_urls.items()):
        dest = pdf_path(year)
        if dest.exists():
            skipped.append(year)
            link_pdf(year)
            if year in downloads and check_remote(session, year, url, downloads[year]):
                write_records("downloads", downloads)
            continue

        print(f"{year}: downloading {url}")
        info, error = fetch(session, url, dest)
        if not info:
            print(f"{year}: FAILED {error}")
            failed.append(year)
            downloads.setdefault(year, {"year": year, "url": url, "title": title})
            downloads[year]["status"] = f"failed:{error}"
            write_records("downloads", downloads)
            continue

        downloads[year] = {
            "year": year,
            "url": url,
            "title": title,
            "size": info["size"],
            "last_modified": info["last_modified"],
            "sha1": sha1_file(dest),
            "download_time_utc": utc_now(),
            "status": "downloaded",
        }
        write_records("downloads", downloads)
        link_pdf(year)
        downloaded.append(year)
        print(f"{year}: ok ({info['size']} bytes)")
        time.sleep(2)

    print(f"*** Downloaded: {len(downloaded)} {downloaded}")
    print(f"*** Skipped (already present): {len(skipped)}")
    print(f"*** Failed: {len(failed)} {failed}")
    if downloaded:
        print("*** Next: make link_wayback upload_archive sync_hf_push, then commit input/documents/")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

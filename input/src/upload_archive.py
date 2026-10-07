"""Upload IFS Civil List PDFs to archive.org, or refresh metadata of uploaded items.

Usage:
    upload_archive.py --collection opensource                     # upload years not yet uploaded
    upload_archive.py --collection ifscivil --update-metadata     # re-apply metadata, no re-upload
"""

import argparse
import html

import internetarchive as ia

from common import CIVIL_LIST_PAGE_URL, MINISTRY, load_env, pdf_path, read_records, require_env, utc_now, write_records


def identifier_for(year):
    return f"in.gov.moef.ifscivillist.{year}"


def build_metadata(download, wayback, collection):
    year, url = download["year"], download["url"]
    title = f"Indian Forest Service Civil List {year}"
    wayback_url = wayback.get("archive_url", "") if wayback.get("link_success") else ""

    def row(label, value):
        return f'<tr><td style="vertical-align: top"><b>{label}</b>:&nbsp;</td><td style="vertical-align: top">{value}</td></tr>'

    def link(href, text):
        return f'<a href="{html.escape(href)}">{html.escape(text)}</a>'

    rows = [
        row("Title", html.escape(title)),
        row("Year", year),
        row("Ministry", html.escape(MINISTRY)),
        row("Source URL", link(url, url)),
        row("Source page", link(CIVIL_LIST_PAGE_URL, CIVIL_LIST_PAGE_URL)),
    ]
    if wayback_url:
        rows.append(row("Wayback URL", link(wayback_url, "web.archive.org")))
    if download.get("download_time_utc"):
        rows.append(row("Downloaded", html.escape(download["download_time_utc"])))
    description = (
        f"<p>Indian Forest Service (IFS) Civil List {year}, published by the {html.escape(MINISTRY)}.</p>\n"
        "<table>\n" + "\n".join(rows) + "\n</table>"
    )

    metadata = {
        "collection": collection,
        "mediatype": "texts",
        "title": title,
        "creator": MINISTRY,
        "publisher": MINISTRY,
        "date": year,
        "year": year,
        "language": "eng",
        "subject": [
            "IFS Civil List",
            "Indian Forest Service",
            "IFS",
            "Ministry of Environment, Forest and Climate Change",
            "MoEFCC",
            "Government of India",
            year,
        ],
        "source": url,
        "source_page": CIVIL_LIST_PAGE_URL,
        "source_title": download.get("title", ""),
        "source_last_modified": download.get("last_modified") or "",
        "sha1": download.get("sha1", ""),
        "description": description,
    }
    if wayback_url:
        metadata["wayback_url"] = wayback_url
    return {k: v for k, v in metadata.items() if v}


def upload(year, metadata, keys):
    identifier = identifier_for(year)
    responses = ia.upload(
        identifier,
        files={f"{year}.pdf": str(pdf_path(year))},
        metadata=metadata,
        access_key=keys[0],
        secret_key=keys[1],
        checksum=True,  # skip if the same file is already in the item
        retries=5,
        retries_sleep=30,
        validate_identifier=True,
        verbose=True,
    )
    bad = [r for r in responses if r.status_code != 200]
    if bad:
        raise RuntimeError(f"HTTP {bad[0].status_code}: {bad[0].text[:200]}")
    if not responses:
        print("\tfile already present in item (checksum match)")


def run_upload(args, keys, downloads, wayback, archive):
    todo = [
        d for y, d in sorted(downloads.items())
        if not d.get("status", "").startswith("failed") and not archive.get(y, {}).get("upload_success")
    ]
    print(f"*** To upload: {len(todo)} (collection={args.collection})")

    for idx, d in enumerate(todo):
        year = d["year"]
        identifier = identifier_for(year)
        print(f"**** {year} [{idx + 1}/{len(todo)}] {identifier}")
        record = {"year": year, "identifier": identifier, "collection": args.collection, "time_utc": utc_now()}

        if not pdf_path(year).exists():
            record.update(upload_success=False, message="pdf missing locally, run make import")
        else:
            wb = wayback.get(year, {})
            if not wb.get("link_success"):
                print("\tWARNING no wayback link yet, uploading without wayback_url")
            try:
                upload(year, build_metadata(d, wb, args.collection), keys)
                record.update(upload_success=True, archive_url=f"https://archive.org/details/{identifier}", message="")
            except Exception as e:
                record.update(upload_success=False, message=str(e))

        print(f"\t{'UPLOADED: ' + record['archive_url'] if record['upload_success'] else 'FAILED: ' + record['message']}")
        archive[year] = record
        write_records("archive", archive)


def run_update_metadata(args, keys, downloads, wayback, archive):
    done = [a for y, a in sorted(archive.items()) if a.get("upload_success") and y in downloads]
    print(f"*** Updating metadata of {len(done)} items (collection={args.collection})")

    for a in done:
        year = a["year"]
        metadata = build_metadata(downloads[year], wayback.get(year, {}), args.collection)
        try:
            r = ia.modify_metadata(a["identifier"], metadata, access_key=keys[0], secret_key=keys[1])
            if r.status_code == 200:
                print(f"{year}: updated")
                a.update(collection=args.collection, metadata_time_utc=utc_now())
            elif "no changes" in r.text.lower():
                print(f"{year}: unchanged")
            else:
                print(f"{year}: FAILED HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"{year}: FAILED {e}")
        write_records("archive", archive)


def main(args):
    load_env()
    keys = require_env("IA_ACCESS_KEY", "IA_SECRET_KEY")
    downloads, wayback, archive = read_records("downloads"), read_records("wayback"), read_records("archive")

    if args.update_metadata:
        run_update_metadata(args, keys, downloads, wayback, archive)
    else:
        run_upload(args, keys, downloads, wayback, archive)

    ok = [a for _, a in sorted(archive.items()) if a.get("upload_success")]
    failed = [y for y, a in sorted(archive.items()) if not a.get("upload_success")]
    print(f"\n*** Uploaded items ({len(ok)}):")
    for a in ok:
        print(a["archive_url"])
    print(f"*** Failed: {len(failed)} {failed}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--collection", default="opensource")
    p.add_argument("--update-metadata", action="store_true", help="re-apply metadata to uploaded items")
    main(p.parse_args())

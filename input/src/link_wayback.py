"""Ask the Wayback Machine (Save Page Now 2 API) to capture every PDF URL not yet linked.

SPN2 docs: https://docs.google.com/document/d/1Nsv52MvSjbLb2PCpHlat0gkzw0EvtSgpKHu4mk0MnrA
"""

import argparse
import time

import requests

from common import load_env, read_records, require_env, utc_now, write_records

SAVE_URL = "https://web.archive.org/save"
STATUS_URL = "https://web.archive.org/save/status/{job_id}"
MAX_SERVICE_FAILURES = 3
STOP_ERRORS = {"error:too-many-daily-captures", "error:user-session-limit"}


class ServiceError(Exception):
    pass


def spn2_request(session, method, url, **kwargs):
    try:
        r = session.request(method, url, timeout=120, **kwargs)
    except requests.RequestException as e:
        raise ServiceError(f"request failed: {e}") from e
    if r.status_code == 429 or r.status_code >= 500:
        raise ServiceError(f"HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError as e:
        raise ServiceError(f"HTTP {r.status_code} non-JSON response: {r.text[:200]}") from e


def capture(session, url, args):
    """Submit url to SPN2 and poll until done. Returns the final status dict."""
    data = {
        "url": url,
        "capture_all": "1",
        "skip_first_archive": "1",
        "if_not_archived_within": args.reuse,
    }
    body = spn2_request(session, "POST", SAVE_URL, data=data)
    if body.get("message"):
        print(f"\tSPN2: {body['message']}")
    if body.get("status") == "error" or "job_id" not in body:
        return body

    job_id = body["job_id"]
    print(f"\tjob_id={job_id}")
    deadline = time.time() + args.poll_timeout
    while True:
        time.sleep(args.poll_interval)
        status = spn2_request(session, "GET", STATUS_URL.format(job_id=job_id))
        status.setdefault("job_id", job_id)
        if status.get("status") in ("success", "error"):
            return status
        if time.time() > deadline:
            return {"status": "error", "status_ext": "poll_timeout", "job_id": job_id,
                    "message": f"no result after {args.poll_timeout}s"}


def main(args):
    load_env()
    access_key, secret_key = require_env("IA_ACCESS_KEY", "IA_SECRET_KEY")

    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Authorization": f"LOW {access_key}:{secret_key}"})

    downloads = read_records("downloads")
    wayback = read_records("wayback")
    todo = [
        d for y, d in sorted(downloads.items())
        if not d.get("status", "").startswith("failed") and not wayback.get(y, {}).get("link_success")
    ]
    print(f"*** To link: {len(todo)}")

    linked, failed, service_failures = [], [], 0
    for idx, d in enumerate(todo):
        year, url = d["year"], d["url"]
        print(f"**** {year} [{idx + 1}/{len(todo)}] {url}")
        try:
            result = capture(session, url, args)
            service_failures = 0
        except ServiceError as e:
            service_failures += 1
            print(f"\tservice failure ({service_failures}/{MAX_SERVICE_FAILURES}): {e}")
            result = {"status": "error", "status_ext": "service_failure", "message": str(e)}

        record = {"year": year, "url": url, "job_id": result.get("job_id", ""), "time_utc": utc_now()}
        timestamp = result.get("timestamp", "")
        if result.get("status") == "success" and timestamp:
            record.update(
                link_success=True,
                timestamp=timestamp,
                archive_url=f"https://web.archive.org/web/{timestamp}/{url}",
                content_url=f"https://web.archive.org/web/{timestamp}id_/{url}",
                message=result.get("message", ""),
            )
            linked.append(year)
            print(f"\tLINKED: {record['archive_url']}")
        else:
            reason = result.get("status_ext") or "error"
            record.update(link_success=False, message=f"{reason}: {result.get('message', '')}".strip(": "))
            failed.append(year)
            print(f"\tFAILED: {record['message']}")

        wayback[year] = record
        write_records("wayback", wayback)

        if result.get("status_ext") in STOP_ERRORS:
            print(">>> Stopping: SPN2 capture limit reached, re-run later")
            break
        if service_failures >= MAX_SERVICE_FAILURES:
            print(">>> Stopping: too many consecutive service failures, re-run later")
            break
        if idx + 1 < len(todo):
            time.sleep(60 if service_failures else args.gap)

    print(f"*** Linked: {len(linked)} {linked}")
    print(f"*** Failed: {len(failed)} {failed}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reuse", default="30d", help="SPN2 if_not_archived_within (reuse a capture newer than this)")
    p.add_argument("--poll-interval", type=float, default=5)
    p.add_argument("--poll-timeout", type=int, default=600)
    p.add_argument("--gap", type=float, default=10, help="seconds between submissions")
    main(p.parse_args())

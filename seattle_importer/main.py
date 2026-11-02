from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from dateutil.parser import isoparse

from .feed import parse_feed
from .models import IngestionEvent
from .supabase import Supabase
from .util import TZ


def supabase_from_env() -> Supabase:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY are required")
    return Supabase(url, key)


def report(sb: Supabase, source: str, code: str, message: str, now: datetime, metadata=None):
    incident = IngestionEvent(source, "error", code, message, now, metadata or {})
    sb.report_ingestion_error(incident)
    print(f"ERROR {source} [{code}]: {message}", file=sys.stderr)


def run(config_path: str, dry_run: bool = False) -> int:
    base = os.environ.get("FEED_BASE_URL", "").rstrip("/") + "/"
    if not base.strip("/"):
        raise SystemExit("FEED_BASE_URL is required")
    config = json.loads(Path(config_path).read_text())
    now = datetime.now(TZ)
    upcoming_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stale_after = now - timedelta(days=int(os.environ.get("FEED_STALE_DAYS", "10")))
    sb = None if dry_run else supabase_from_env()
    session = requests.Session()
    session.headers.update({"User-Agent": "SeattleEventsImporter/4.0"})
    failures = 0

    for item in config:
        expected_source = item["source"]
        try:
            status_url = urljoin(base, item["status"])
            sr = session.get(status_url, timeout=30)
            sr.raise_for_status()
            status = sr.json()
            if status.get("source") != expected_source:
                raise ValueError("status source mismatch")
            status_time = isoparse(status["generated_at"])
            if not status.get("success"):
                failures += 1
                if sb:
                    report(sb, expected_source, status.get("code", "producer_error"), status.get("message", "producer failed"), now, {"status_url": status_url})
                continue
            if status_time < stale_after:
                failures += 1
                if sb:
                    report(sb, expected_source, "feed_stale", f"feed producer has not succeeded since {status_time.isoformat()}", now, {"status_url": status_url})
                continue

            feed_url = urljoin(base, item["feed"])
            fr = session.get(feed_url, timeout=30)
            fr.raise_for_status()
            source, generated_at, events = parse_feed(fr.content)
            if source != expected_source:
                raise ValueError(f"feed source mismatch: expected {expected_source}, got {source}")
            if generated_at < stale_after:
                raise ValueError(f"feed is stale: {generated_at.isoformat()}")
            if not events:
                raise ValueError("feed returned zero upcoming events")

            rows = [e.row(now) for e in events]
            if dry_run:
                print(f"{source}: {len(rows)} events")
            else:
                sb.sync_source(source, rows, now.isoformat())
                sb.mark_missing(source, now.isoformat(), upcoming_from.isoformat())
                sb.resolve_ingestion_errors(source, now.isoformat())
                print(f"{source}: imported {len(rows)} events")
        except Exception as exc:
            failures += 1
            if sb:
                report(sb, expected_source, "feed_import_error", str(exc), now, {"exception_type": type(exc).__name__})
            else:
                print(f"ERROR {expected_source}: {exc}", file=sys.stderr)

    return failures


def purge_old() -> None:
    sb = supabase_from_env()
    print(f"purged {sb.purge_old_events()} old event rows")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="feeds.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--purge-old", action="store_true")
    args = parser.parse_args()
    if args.purge_old:
        purge_old()
        return
    failures = run(args.config, args.dry_run)
    if failures:
        raise SystemExit(f"{failures} feed(s) failed")


if __name__ == "__main__":
    main()

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

import requests

from .models import IngestionEvent

HUMAN_FIELDS = (
    "review_status",
    "reviewed_at",
    "visible",
    "favorite",
    "category",
    "notes",
)


class Supabase:
    def __init__(self, url: str, key: str):
        root = url.rstrip("/") + "/rest/v1"
        self.root = root
        self.events_url = root + "/events"
        self.ingestion_url = root + "/ingestion_events"
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _existing_for_source(self, source: str) -> dict[str, dict]:
        response = requests.get(
            self.events_url,
            headers=self.headers,
            params={
                "source": f"eq.{source}",
                "select": (
                    "id,first_seen_at,review_status,reviewed_at,visible,favorite,"
                    "category,notes,material_hash,last_material_change_at"
                ),
            },
            timeout=30,
        )
        response.raise_for_status()
        return {row["id"]: row for row in response.json()}

    def sync_source(self, source: str, rows: list[dict], run_started_iso: str):
        existing = self._existing_for_source(source)
        prepared: list[dict] = []

        for row in rows:
            old = existing.get(row["id"])
            if old:
                row["first_seen_at"] = old.get("first_seen_at") or run_started_iso
                for field in HUMAN_FIELDS:
                    if field in old:
                        row[field] = old.get(field)
                if old.get("material_hash") != row.get("material_hash"):
                    row["last_material_change_at"] = run_started_iso
                else:
                    row["last_material_change_at"] = old.get("last_material_change_at")
            else:
                row["first_seen_at"] = run_started_iso
                row["review_status"] = "unreviewed"
                row["reviewed_at"] = None
                row["last_material_change_at"] = run_started_iso

            prepared.append(row)

        self.upsert_events(prepared)

    def upsert_events(self, rows: list[dict]):
        if not rows:
            return
        headers = {**self.headers, "Prefer": "resolution=merge-duplicates,return=minimal"}
        for i in range(0, len(rows), 200):
            response = requests.post(
                self.events_url + "?on_conflict=id",
                headers=headers,
                json=rows[i : i + 200],
                timeout=30,
            )
            response.raise_for_status()

    def mark_missing(self, source: str, run_started_iso: str, upcoming_from_iso: str):
        # Only call this after the source fetch and its upsert have succeeded.
        # missing_since is write-once until the event reappears, at which point
        # normal upsert rows clear it back to null.
        params = (
            f"?source=eq.{quote(source, safe='')}"
            f"&last_seen_at=lt.{quote(run_started_iso, safe=':+-.TZ')}"
            f"&start_at=gte.{quote(upcoming_from_iso, safe=':+-.TZ')}"
            "&missing_since=is.null"
        )
        headers = {**self.headers, "Prefer": "return=minimal"}
        response = requests.patch(
            self.events_url + params,
            headers=headers,
            json={"missing_since": run_started_iso},
            timeout=30,
        )
        response.raise_for_status()

    def report_ingestion_error(self, event: IngestionEvent):
        row = event.row()
        row["id"] = f"{event.source}:{event.code}"
        row["resolved_at"] = None
        row.pop("first_seen_at", None)
        headers = {**self.headers, "Prefer": "resolution=merge-duplicates,return=minimal"}
        response = requests.post(
            self.ingestion_url + "?on_conflict=id",
            headers=headers,
            json=row,
            timeout=30,
        )
        response.raise_for_status()

    def resolve_ingestion_errors(self, source: str, resolved_at_iso: str):
        headers = {**self.headers, "Prefer": "return=minimal"}
        response = requests.patch(
            self.ingestion_url + f"?source=eq.{quote(source, safe='')}&resolved_at=is.null",
            headers=headers,
            json={"resolved_at": resolved_at_iso, "last_seen_at": resolved_at_iso},
            timeout=30,
        )
        response.raise_for_status()

    def purge_old_events(self) -> int | None:
        response = requests.post(
            self.root + "/rpc/purge_old_events",
            headers={**self.headers, "Prefer": "return=representation"},
            json={},
            timeout=30,
        )
        response.raise_for_status()
        try:
            value = response.json()
        except ValueError:
            return None
        return value if isinstance(value, int) else None

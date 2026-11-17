import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import requests

from seattle_importer.diagnostics import format_failure, sanitize_text
from seattle_importer.main import run
from seattle_importer.util import TZ


FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:seattle="urn:seattle-events:v1">
  <channel>
    <title>Neumos</title>
    <seattle:source>neumos</seattle:source>
    <seattle:generated_at>2026-11-17T12:00:00-08:00</seattle:generated_at>
    <item>
      <title>Band</title>
      <guid>neumos:1</guid>
      <seattle:source_event_id>1</seattle:source_event_id>
      <seattle:venue>Neumos</seattle:venue>
      <seattle:start_at>2026-12-01T20:00:00-08:00</seattle:start_at>
      <seattle:event_url>https://example.com/e</seattle:event_url>
    </item>
  </channel>
</rss>"""


def http_error(url: str, status: int = 404) -> requests.HTTPError:
    response = Mock()
    response.status_code = status
    response.reason = "Not Found" if status == 404 else "Bad Request"
    response.url = url
    response.text = ""
    response.request = Mock(method="GET" if status == 404 else "POST", url=url)
    response.json.side_effect = ValueError("no json")
    return requests.HTTPError(f"{status} Client Error for url: {url}", response=response)


class SanitizationTests(unittest.TestCase):
    def test_failure_text_omits_credentials_and_query(self):
        response = Mock()
        response.status_code = 401
        response.request = Mock(
            method="POST",
            url="https://example.supabase.co/rest/v1/events?apikey=sb_secret_abcdefghijklmnopqrstuvwxyz",
        )
        response.json.return_value = {
            "code": "PGRST301",
            "message": "Invalid JWT Authorization: Bearer sb_secret_abcdefghijklmnopqrstuvwxyz",
        }
        exc = requests.HTTPError("request failed", response=response)
        text = format_failure(exc, "importer-database", "neumos")
        self.assertIn("status=401", text)
        self.assertIn("error_code=PGRST301", text)
        self.assertIn("Bearer [REDACTED]", text)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", text)
        self.assertNotIn("apikey=", text)
        self.assertNotIn("sb_secret_", text)
        self.assertEqual(sanitize_text("eyJhbGciOiJIUzI1NiJ9.payload.sig"), "[JWT]")
        self.assertEqual(sanitize_text("sb_publishable_abcdefghijklmnopqrstuvwxyz"), "[KEY]")


class IncidentReportTests(unittest.TestCase):
    def test_reporting_failure_keeps_original_and_continues(self):
        config = [
            {"source": "neumos", "feed": "feeds/neumos.xml", "status": "status/neumos.json"},
            {"source": "showbox", "feed": "feeds/showbox.xml", "status": "status/showbox.json"},
        ]
        fetched = []

        def get(url, timeout=30):
            fetched.append(urlsplit(url).path)
            raise http_error(url, 404)

        sb = Mock()
        sb.report_ingestion_error.side_effect = requests.ConnectionError(
            "Failed to resolve host='example.supabase.co'"
        )
        session = Mock()
        session.get.side_effect = get

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "feeds.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(config, handle)
            stderr = io.StringIO()
            with patch.dict(os.environ, {"FEED_BASE_URL": "https://feeds.example"}):
                with patch("seattle_importer.main.supabase_from_env", return_value=sb):
                    with patch("seattle_importer.main.requests.Session", return_value=session):
                        with contextlib.redirect_stderr(stderr):
                            failures = run(path, dry_run=False)

        text = stderr.getvalue()
        self.assertEqual(failures, 2)
        self.assertEqual(fetched, ["/status/neumos.json", "/status/showbox.json"])
        self.assertEqual(sb.report_ingestion_error.call_count, 2)
        sb.mark_missing.assert_not_called()
        sb.sync_source.assert_not_called()
        self.assertIn("layer=published-feed", text)
        self.assertIn("source=neumos", text)
        self.assertIn("source=showbox", text)
        self.assertIn("status=404", text)
        self.assertIn("incident_report_failed", text)
        self.assertIn("example.supabase.co", text)
        self.assertNotIn("sb_secret_", text)
        self.assertNotIn("Bearer ", text)

    def test_failed_database_write_does_not_mark_missing(self):
        now = datetime.now(TZ).isoformat()
        status = {
            "source": "neumos",
            "success": True,
            "generated_at": now,
        }

        def get(url, timeout=30):
            path = urlsplit(url).path
            response = Mock(status_code=200)
            response.raise_for_status = lambda: None
            if path.endswith("status/neumos.json"):
                response.json.return_value = status
                response.content = json.dumps(status).encode()
                return response
            if path.endswith("feeds/neumos.xml"):
                response.content = FEED
                return response
            raise AssertionError(path)

        sb = Mock()
        sb.sync_source.side_effect = http_error(
            "https://example.supabase.co/rest/v1/events?on_conflict=id",
            400,
        )
        session = Mock()
        session.get.side_effect = get

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "feeds.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    [{"source": "neumos", "feed": "feeds/neumos.xml", "status": "status/neumos.json"}],
                    handle,
                )
            stderr = io.StringIO()
            with patch.dict(os.environ, {"FEED_BASE_URL": "https://feeds.example"}):
                with patch("seattle_importer.main.supabase_from_env", return_value=sb):
                    with patch("seattle_importer.main.requests.Session", return_value=session):
                        with contextlib.redirect_stderr(stderr):
                            failures = run(path, dry_run=False)

        text = stderr.getvalue()
        self.assertEqual(failures, 1)
        sb.sync_source.assert_called_once()
        sb.mark_missing.assert_not_called()
        sb.resolve_ingestion_errors.assert_not_called()
        self.assertIn("layer=importer-database", text)
        self.assertIn("status=400", text)
        self.assertIn("/rest/v1/events", text)
        self.assertNotIn("on_conflict", text)

    def test_producer_failure_does_not_mark_missing(self):
        now = datetime.now(TZ).isoformat()

        def get(url, timeout=30):
            response = Mock(status_code=200)
            response.raise_for_status = lambda: None
            response.json.return_value = {
                "source": "paramount",
                "success": False,
                "code": "source_http_error",
                "message": "403 Client Error: Forbidden for url: https://www.axs.com/venues/101582/paramount-theatre-seattle-seattle-tickets",
                "generated_at": now,
            }
            return response

        sb = Mock()
        session = Mock()
        session.get.side_effect = get

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "feeds.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    [{"source": "paramount", "feed": "feeds/paramount.xml", "status": "status/paramount.json"}],
                    handle,
                )
            stderr = io.StringIO()
            with patch.dict(os.environ, {"FEED_BASE_URL": "https://feeds.example"}):
                with patch("seattle_importer.main.supabase_from_env", return_value=sb):
                    with patch("seattle_importer.main.requests.Session", return_value=session):
                        with contextlib.redirect_stderr(stderr):
                            failures = run(path, dry_run=False)

        text = stderr.getvalue()
        self.assertEqual(failures, 1)
        sb.sync_source.assert_not_called()
        sb.mark_missing.assert_not_called()
        self.assertIn("layer=producer", text)
        self.assertIn("source=paramount", text)
        self.assertIn("403", text)
        sb.report_ingestion_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()

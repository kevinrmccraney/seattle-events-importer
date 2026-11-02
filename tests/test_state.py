import unittest
from datetime import datetime
from unittest.mock import patch, Mock

from seattle_importer.models import Event
from seattle_importer.supabase import Supabase
from seattle_importer.util import TZ


class MaterialHashTests(unittest.TestCase):
    def event(self, **changes):
        values = dict(
            id="x:1",
            source="x",
            source_event_id="1",
            title="Band",
            venue="Venue",
            start_at=datetime(2026, 11, 10, 20, 0, tzinfo=TZ),
            event_url="https://example.com/1",
            support="Support",
            status="scheduled",
            sold_out=False,
            metadata={"artists": ["Band", "Support"]},
        )
        values.update(changes)
        return Event(**values)

    def test_sold_out_does_not_change_material_hash(self):
        a = self.event(sold_out=False, status="scheduled")
        b = self.event(sold_out=True, status="sold_out")
        self.assertEqual(a.row(datetime.now(TZ))["material_hash"], b.row(datetime.now(TZ))["material_hash"])
        self.assertNotEqual(a.row(datetime.now(TZ))["content_hash"], b.row(datetime.now(TZ))["content_hash"])

    def test_reschedule_does_change_material_hash(self):
        a = self.event(status="scheduled")
        b = self.event(status="rescheduled")
        self.assertNotEqual(a.row(datetime.now(TZ))["material_hash"], b.row(datetime.now(TZ))["material_hash"])

    def test_lineup_change_does_change_material_hash(self):
        a = self.event(support="Support")
        b = self.event(support="Different Support")
        self.assertNotEqual(a.row(datetime.now(TZ))["material_hash"], b.row(datetime.now(TZ))["material_hash"])


class SupabasePreservationTests(unittest.TestCase):
    @patch("seattle_importer.supabase.requests.post")
    @patch("seattle_importer.supabase.requests.get")
    def test_sync_preserves_review_fields(self, mock_get, mock_post):
        mock_get.return_value = Mock(
            status_code=200,
            json=lambda: [{
                "id": "x:1",
                "first_seen_at": "2026-10-01T00:00:00+00:00",
                "review_status": "interested",
                "reviewed_at": "2026-10-15T00:00:00+00:00",
                "visible": True,
                "favorite": True,
                "category": "maybe",
                "notes": "keep",
                "material_hash": "oldhash",
                "last_material_change_at": "2026-10-01T00:00:00+00:00",
            }],
        )
        mock_get.return_value.raise_for_status = lambda: None
        mock_post.return_value = Mock(status_code=201)
        mock_post.return_value.raise_for_status = lambda: None

        sb = Supabase("https://example.supabase.co", "secret")
        row = self.event_row()
        sb.sync_source("x", [row], "2026-10-31T12:00:00+00:00")

        sent = mock_post.call_args.kwargs["json"][0]
        self.assertEqual(sent["review_status"], "interested")
        self.assertEqual(sent["reviewed_at"], "2026-10-15T00:00:00+00:00")
        self.assertEqual(sent["notes"], "keep")
        self.assertEqual(sent["last_material_change_at"], "2026-10-31T12:00:00+00:00")

    @staticmethod
    def event_row():
        e = Event(
            id="x:1",
            source="x",
            source_event_id="1",
            title="Band Updated",
            venue="Venue",
            start_at=datetime(2026, 11, 10, 20, 0, tzinfo=TZ),
            event_url="https://example.com/1",
        )
        return e.row(datetime(2026, 10, 31, 12, 0, tzinfo=TZ))


if __name__ == "__main__":
    unittest.main()

import unittest

from seattle_importer.feed import parse_feed


SAMPLE = b'''<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:seattle="urn:seattle-events:v1">
  <channel>
    <title>Neumos</title>
    <link>https://neumos.com</link>
    <description>Normalized upcoming events</description>
    <seattle:source>neumos</seattle:source>
    <seattle:generated_at>2026-11-01T12:00:00-08:00</seattle:generated_at>
    <item>
      <title>Band</title>
      <link>https://example.com/e</link>
      <guid isPermaLink="false">neumos:1</guid>
      <description>Band at Neumos</description>
      <seattle:source>neumos</seattle:source>
      <seattle:source_event_id>1</seattle:source_event_id>
      <seattle:venue>Neumos</seattle:venue>
      <seattle:start_at>2026-11-10T20:00:00-08:00</seattle:start_at>
      <seattle:event_url>https://example.com/e</seattle:event_url>
      <seattle:ticket_url>https://example.com/t</seattle:ticket_url>
      <seattle:support>Support</seattle:support>
      <seattle:status>scheduled</seattle:status>
      <seattle:sold_out>false</seattle:sold_out>
      <seattle:metadata>{"artists":["Band","Support"]}</seattle:metadata>
    </item>
  </channel>
</rss>'''


class FeedParserTests(unittest.TestCase):
    def test_parse_normalized_feed(self):
        source, generated, events = parse_feed(SAMPLE)
        self.assertEqual(source, "neumos")
        self.assertEqual(events[0].source_event_id, "1")
        self.assertEqual(events[0].support, "Support")
        self.assertEqual(events[0].metadata["artists"], ["Band", "Support"])


if __name__ == "__main__":
    unittest.main()

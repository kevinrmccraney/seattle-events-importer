# v4 importer changes

- Removes all venue/API scraping from the Supabase layer.
- Consumes normalized RSS feeds plus per-source producer status files.
- Stores exact producer errors in `ingestion_events` when available.
- Refuses missing-event reconciliation after producer/feed failure.
- Preserves the v3 review-state, hashing, material-change, missing-state, and annual-purge behavior.

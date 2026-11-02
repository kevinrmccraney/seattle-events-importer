# Seattle Events Supabase Importer v4.1

This repository does not scrape venue websites. It consumes normalized RSS feeds produced by the separate feed-producer repository and maintains the Supabase review database.

## Architecture

```text
normalized RSS feeds -> weekly importer -> Supabase -> review/frontend
```

The importer is intentionally unaware of Carbonhouse, DICE, Showbox HTML, API keys, or venue-specific parsing.

## Supabase setup

1. Create a Supabase project.
2. Open **SQL Editor** and run `schema.sql` in full.
3. Copy the project URL and server-side secret key.
4. In this GitHub repository, add Actions secrets:

```text
SUPABASE_URL
SUPABASE_SECRET_KEY
```

5. Add an Actions **repository variable**:

```text
FEED_BASE_URL=https://USERNAME.github.io/seattle-event-feeds/
```

The importer appends paths from `feeds.json` to that base URL.

## Weekly import

`.github/workflows/import.yml` runs Mondays at `14:47 UTC`, after the producer refresh.

For each source it:

1. reads `status/SOURCE.json`
2. refuses to import if the producer reported an error
3. rejects feeds older than 10 days (`FEED_STALE_DAYS` can override this)
4. parses normalized RSS
5. upserts by stable `(source, source_event_id)` identity
6. inserts genuinely new IDs as `unreviewed`
7. preserves `review_status`, `reviewed_at`, `visible`, `favorite`, `category`, and `notes`
8. updates `content_hash` / `material_hash`
9. marks unseen upcoming events `missing_since` only after a successful feed import
10. resolves prior ingestion errors after a successful import

Producer errors such as a rejected DICE key are stored in `ingestion_events`; they are not inserted into the music-events table.

## Review workflow

`review_status` is one of:

- `unreviewed`
- `interested`
- `not_interested`

A sellout updates metadata but does not make an event new or materially changed.
Material changes are limited to title, artist/support lineup, start/end, venue, and cancellation/postponement/reschedule status.

Recommended review queries:

```text
Review queue: review_status = unreviewed
Interested:   review_status = interested
Working set:  review_status in (unreviewed, interested)
```

## Annual cleanup

`schema.sql` installs `public.purge_old_events()`, which deletes rows whose event start is more than one year old. `.github/workflows/purge.yml` runs it once each January.

## Run locally

```bash
python -m pip install -r requirements.txt
export FEED_BASE_URL='https://USERNAME.github.io/seattle-event-feeds/'
export SUPABASE_URL='https://PROJECT.supabase.co'
export SUPABASE_SECRET_KEY='...'
python -m seattle_importer.main
```

Dry-run feed validation without Supabase writes:

```bash
FEED_BASE_URL='https://USERNAME.github.io/seattle-event-feeds/' \
python -m seattle_importer.main --dry-run
```

## Tests

```bash
python -m unittest discover -s tests -v
```

## Feed registry update (v4.1)

`feeds.json` now also consumes:

- `feeds/tractor.xml` with `status/tractor.json`
- `feeds/clockout.xml` with `status/clockout.json`

No schema or importer-state behavior changed.

### v4.2 feeds

The default feed registry also consumes `feeds/nectar.xml` and `feeds/hidden-hall.xml` with their matching status sidecars.


### v4.3 feeds

The default registry additionally consumes El Corazón, The Funhouse, Dimitriou's Jazz Alley, and The Royal Room normalized feeds. No Supabase schema change is required.


### v4.4 feeds

The default `feeds.json` registry includes:

- `feeds/el-corazon.xml`
- `feeds/funhouse.xml`
- `feeds/jazz-alley.xml`
- `feeds/royal-room.xml`

with matching status sidecars. No SQL/schema change is required.

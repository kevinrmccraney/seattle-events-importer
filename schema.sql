create table if not exists public.events (
  id text primary key,
  source text not null,
  source_event_id text not null,
  title text not null,
  venue text not null,
  start_at timestamptz not null,
  end_at timestamptz,
  event_url text not null,
  ticket_url text,
  image_url text,
  description text,
  support text,
  promoter text,
  doors_time text,
  age_restriction text,
  status text not null default 'scheduled',
  sold_out boolean not null default false,
  metadata jsonb not null default '{}'::jsonb,
  content_hash text,
  material_hash text,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  last_material_change_at timestamptz,
  missing_since timestamptz,
  removed boolean not null default false,
  review_status text not null default 'unreviewed',
  reviewed_at timestamptz,
  visible boolean not null default true,
  favorite boolean not null default false,
  category text,
  notes text,
  constraint events_review_status_check
    check (review_status in ('unreviewed', 'interested', 'not_interested'))
);

-- Safe upgrades for projects created from earlier versions.
alter table public.events add column if not exists source_event_id text;
alter table public.events add column if not exists end_at timestamptz;
alter table public.events add column if not exists image_url text;
alter table public.events add column if not exists support text;
alter table public.events add column if not exists promoter text;
alter table public.events add column if not exists doors_time text;
alter table public.events add column if not exists status text not null default 'scheduled';
alter table public.events add column if not exists sold_out boolean not null default false;
alter table public.events add column if not exists metadata jsonb not null default '{}'::jsonb;
alter table public.events add column if not exists content_hash text;
alter table public.events add column if not exists material_hash text;
alter table public.events add column if not exists last_material_change_at timestamptz;
alter table public.events add column if not exists missing_since timestamptz;
alter table public.events add column if not exists review_status text not null default 'unreviewed';
alter table public.events add column if not exists reviewed_at timestamptz;

-- Add the review constraint only if an older database does not already have it.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'events_review_status_check'
      and conrelid = 'public.events'::regclass
  ) then
    alter table public.events
      add constraint events_review_status_check
      check (review_status in ('unreviewed', 'interested', 'not_interested'));
  end if;
end $$;

create unique index if not exists events_source_event_id_uidx
  on public.events(source, source_event_id);
create index if not exists events_start_at_idx on public.events(start_at);
create index if not exists events_source_idx on public.events(source);
create index if not exists events_review_status_idx on public.events(review_status);
create index if not exists events_missing_since_idx on public.events(missing_since);

create table if not exists public.ingestion_events (
  id text primary key,
  source text not null,
  level text not null,
  code text not null,
  message text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  resolved_at timestamptz,
  metadata jsonb not null default '{}'::jsonb
);

create index if not exists ingestion_events_source_idx on public.ingestion_events(source);
create index if not exists ingestion_events_active_idx on public.ingestion_events(resolved_at);

-- Annual cleanup: remove event rows whose event start is more than one year old.
create or replace function public.purge_old_events()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  deleted_count integer;
begin
  delete from public.events
  where start_at < now() - interval '1 year';

  get diagnostics deleted_count = row_count;
  return deleted_count;
end;
$$;

alter table public.events enable row level security;
alter table public.ingestion_events enable row level security;

drop policy if exists "public can read visible events" on public.events;
create policy "public can read visible events"
on public.events for select
to anon
using (
  visible = true
  and removed = false
  and review_status <> 'not_interested'
);

-- Operational errors are admin-only: never expose them through the public frontend.
grant select on public.events to anon;
grant select, insert, update, delete on public.events to service_role;
grant select, insert, update, delete on public.ingestion_events to service_role;
grant execute on function public.purge_old_events() to service_role;

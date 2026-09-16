create table if not exists public.uploaded_reports (
  id text primary key,
  report_type text not null check (report_type in ('sales', 'waste')),
  original_name text not null,
  stored_name text not null,
  period_start date not null,
  period_end date not null,
  uploaded_at timestamptz not null,
  size integer not null check (size > 0),
  storage_path text not null,
  constraint uploaded_reports_unique_period unique (report_type, period_start, period_end)
);

create index if not exists uploaded_reports_type_period_idx
  on public.uploaded_reports (report_type, period_start desc, period_end desc);

alter table public.uploaded_reports enable row level security;

drop policy if exists "Backend service role can manage uploaded reports" on public.uploaded_reports;
create policy "Backend service role can manage uploaded reports"
  on public.uploaded_reports
  for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

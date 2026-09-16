create table if not exists public.uploaded_report_chunks (
  report_id text not null references public.uploaded_reports(id) on delete cascade,
  chunk_index integer not null check (chunk_index >= 0),
  content_base64 text not null,
  created_at timestamptz not null default now(),
  primary key (report_id, chunk_index)
);

create index if not exists uploaded_report_chunks_report_idx
  on public.uploaded_report_chunks (report_id, chunk_index);

alter table public.uploaded_report_chunks enable row level security;

drop policy if exists "Backend service role can manage uploaded report chunks" on public.uploaded_report_chunks;
create policy "Backend service role can manage uploaded report chunks"
  on public.uploaded_report_chunks
  for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

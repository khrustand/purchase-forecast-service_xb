-- Чеки — отдельный источник спроса; несколько актов за день допустимы.
alter table public.uploaded_reports drop constraint if exists uploaded_reports_report_type_check;
alter table public.uploaded_reports add constraint uploaded_reports_report_type_check
  check (report_type in ('sales', 'waste', 'receipts'));
alter table public.uploaded_reports drop constraint if exists uploaded_reports_unique_period;
create unique index if not exists uploaded_reports_period_non_waste
  on public.uploaded_reports(report_type, period_start, period_end) where report_type <> 'waste';
create unique index if not exists uploaded_reports_waste_summary_period
  on public.uploaded_reports(period_start, period_end)
  where report_type = 'waste' and stored_name not like 'waste-doc-%';
create unique index if not exists uploaded_reports_waste_document
  on public.uploaded_reports(period_start, (substring(stored_name from '^waste-doc-([0-9]+)-')))
  where report_type = 'waste' and stored_name like 'waste-doc-%';

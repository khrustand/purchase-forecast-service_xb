# Supabase Report Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Supabase-backed report storage mode for XLSX uploads while keeping the current local mode intact.

**Architecture:** The web server will depend on a small storage interface already represented by `MonthlyReportStorage` methods. A new `SupabaseReportStorage` adapter will store files in Supabase Storage and report metadata in the `uploaded_reports` table through Supabase REST APIs.

**Tech Stack:** Python 3.11 standard library, Supabase Storage REST API, Supabase PostgREST, unittest.

**Spec:** `docs/superpowers/specs/2026-09-15-supabase-report-storage-design.md`

## Global Constraints

- All visible UI text, docs, and operational messages must be in Russian.
- Do not print or commit real Supabase keys, database URLs, passwords, or uploaded production data.
- Keep local mode as the default: `STORAGE_BACKEND=local`.
- Use only standard-library HTTP clients for this step; do not add a Supabase SDK dependency.

---

### Task 1: Storage Factory and Supabase Adapter

**Files:**
- Modify: `src/infrastructure/report_storage.py`
- Test: `tests/test_report_storage.py`

**Interfaces:**
- Produces: `create_report_storage() -> object`
- Produces: `SupabaseReportStorage`
- Produces: `storage_label() -> str` on both storage classes

- [ ] Write failing tests for backend selection, missing Supabase config, Supabase upload metadata, and Supabase download.
- [ ] Run `py -m unittest tests.test_report_storage` and verify the new tests fail because the adapter does not exist.
- [ ] Implement `SupabaseReportStorage` with validation reuse, Storage upload/download, metadata select/insert, and a local cache.
- [ ] Run `py -m unittest tests.test_report_storage` and verify it passes.

### Task 2: Web Interface Integration

**Files:**
- Modify: `src/app/web_server.py`
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: `create_report_storage()`
- Consumes: `storage_label()`

- [ ] Write a failing test that `/reports` HTML shows the active storage mode.
- [ ] Run `py -m unittest tests.test_web_server` and verify the test fails before the UI change.
- [ ] Replace direct `MonthlyReportStorage()` construction with `create_report_storage()`.
- [ ] Add storage mode text to the `/reports` page.
- [ ] Run `py -m unittest tests.test_web_server` and verify it passes.

### Task 3: Supabase Migration and Docs

**Files:**
- Create: `supabase/migrations/001_uploaded_reports.sql`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/external-deployment.md`

**Interfaces:**
- Produces: SQL table `public.uploaded_reports`

- [ ] Add SQL migration for report metadata with indexes and duplicate protection.
- [ ] Document that the SQL must be run in Supabase SQL Editor before enabling `STORAGE_BACKEND=supabase`.
- [ ] Run `py -m unittest`.

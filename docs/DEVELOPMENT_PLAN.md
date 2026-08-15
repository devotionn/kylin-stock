# KylinStock 开发计划

## Phase 0 - Requirements Baseline

Status: completed/ongoing confirmation.

- REQUIREMENTS.md maintained as scope baseline.
- New customer feedback increments document version.

## Phase 1 - Foundation

- Initialize Vue 3 + TypeScript + Vite.
- Initialize Tauri 2 desktop shell.
- Establish project directory conventions.
- Add Element Plus.
- Add SQLite persistence and migrations.
- Add global error handling and logging.
- Build application shell/sidebar/topbar.
- Validate development build.

Exit criteria: application opens as desktop window and can initialize/read/write local SQLite database.

## Phase 2 - Master Data

- Materials CRUD.
- Units.
- Locations.
- Disable/archive semantics.
- Centered table UI convention.

Exit criteria: user can maintain all data required before stock operations.

## Phase 3 - Inventory Core

- Stock-in form and transaction.
- Stock-out form and destination.
- Insufficient-stock guard.
- Current inventory.
- Inventory distribution.
- Transaction ledger.

Exit criteria: end-to-end `material -> stock in -> stock -> stock out -> destination -> ledger` is correct and transaction-safe.

## Phase 4 - Query & Export

- Name filter.
- Date range filter.
- Unit filter.
- Transaction type filter.
- Destination filter.
- Combined filters.
- Export current query result.
- Export transaction details.
- Export inventory distribution.

Exit criteria: exported rows match visible query semantics.

## Phase 5 - Backup & Restore

- Manual backup.
- Annual-labelled backup.
- Backup list/metadata.
- Restore confirmation.
- Restore flow.
- Failure handling.

Exit criteria: a test database can be backed up, modified and restored correctly.

## Phase 6 - UX Hardening

- Dashboard.
- Empty/loading/error states.
- Form validation.
- Long-text handling.
- Chinese UI consistency.
- Confirmation dialogs for destructive actions.
- Table alignment requirement verification.

## Phase 7 - Kylin ARM64 Compatibility

Target machine: Kylin Linux Desktop V10 JICAI, Phytium D2000, ARM64, UKUI.

Validate:

- runtime/WebKitGTK;
- native dependencies;
- SQLite;
- Chinese IME/fonts;
- export/file picker;
- backup paths;
- desktop launcher;
- package installation;
- reboot persistence.

## Phase 8 - Acceptance

Execute all acceptance cases in REQUIREMENTS.md. Record failures and fixes. Produce installation/use notes and final release artifact.

## Scope Guard

Do not introduce procurement, sales, finance, SaaS, complex RBAC, barcode hardware, cloud dependency or multi-machine architecture unless REQUIREMENTS.md is explicitly revised.

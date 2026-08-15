# KylinStock 开发计划

## Phase 0 - Requirements Baseline

Status: completed/ongoing confirmation.

- REQUIREMENTS.md maintained as scope baseline.
- New customer feedback increments document version.

## Phase 1 - Foundation

Status: **in progress**.

Completed:

- Vue 3 + TypeScript + Vite project skeleton.
- Tauri 2 desktop shell.
- Project directory conventions.
- Element Plus application shell/sidebar/topbar.
- SQLite initialization layer and initial schema.
- Tauri SQL and dialog capability configuration.
- Customer-required centered table styling baseline.
- Main navigation entries for all V1 modules.

Remaining before Phase 1 exit:

- Install dependencies and generate lockfiles in a build environment.
- Validate `npm run build`.
- Validate `tauri dev` desktop startup.
- Validate SQLite initialization/read/write on Linux.
- Add structured logging/error boundary.

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

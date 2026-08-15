# KylinStock 开发计划

## Phase 0 - Requirements Baseline

Status: **completed / continuously maintained**.

- REQUIREMENTS.md is the V1 scope baseline.
- New customer feedback increments the document version before implementation.

## Phase 1 - Foundation

Status: **implemented, build validation pending**.

Completed:

- Vue 3 + TypeScript + Vite project skeleton.
- Tauri 2 desktop shell.
- Project directory conventions.
- Element Plus application shell/sidebar/topbar.
- SQLite initialization layer and initial schema.
- Tauri SQL/dialog/filesystem capability configuration.
- Customer-required centered table styling baseline.
- Main navigation entries for all V1 modules.

Remaining validation:

- Install dependencies and generate lockfiles in a build environment.
- Validate `npm run build`.
- Validate `tauri dev` desktop startup.
- Validate SQLite initialization/read/write on Linux.
- Add structured logging/error boundary.

## Phase 2 - Master Data

Status: **implemented and merged to main**.

Completed:

- Materials create/edit/search.
- Units quick creation.
- Locations quick creation.
- Disable/re-enable semantics instead of deleting historical master data.
- Customer-required centered table convention.
- Material query result XLSX export added during Phase 4.

## Phase 3 - Inventory Core

Status: **implemented and merged to main**.

Completed:

- Stock-in form and transaction.
- Stock-out form and mandatory destination.
- Insufficient-stock guard / no normal negative inventory.
- Per-material/per-location inventory balances.
- Current inventory view.
- Inventory distribution view.
- Transaction ledger.
- Atomic SQLite transaction semantics for ledger + balance changes.

Core flow now exists:

`material -> stock in -> inventory -> stock out -> destination -> ledger`

## Phase 4 - Query & Export

Status: **implemented and merged to main; target-machine validation pending**.

Completed:

- Material-name filter.
- Date-range filter.
- Related-unit filter.
- Transaction-type filter.
- Destination filter.
- Combined ledger filters.
- Inventory filters for material name, measurement unit and location.
- Native system save dialog.
- XLSX workbook generation.
- Export current material query results.
- Export current transaction query results.
- Export current inventory/distribution query results.
- “What is queried is what is exported” semantics: export uses the exact rows currently shown in the table.

Validation remaining:

- TypeScript/Vite build.
- Tauri filesystem permission check.
- `.xlsx` opening and Chinese-content validation in target office software.
- Real Kylin V10 / ARM64 save-dialog and file-write test.

## Phase 5 - Backup & Restore

Status: **implemented on `feat/backup-restore`, validation pending**.

Implemented:

- Manual backup with native save dialog.
- Annual-labelled full database snapshot.
- Backup history / metadata.
- Native Rust database file backup command.
- SQLite connection pool is closed before file-level backup or restore.
- Native backup uses temporary-file + sync + rename semantics.
- Restore-file SQLite header validation.
- Restore confirmation in UI.
- Automatic pre-restore safety backup.
- Database replacement through temporary and old-file swap.
- Rollback to previous database if restored target cannot be safely synced.
- Post-restore `PRAGMA integrity_check`.
- Automatic attempt to recover the pre-restore safety copy if integrity check fails.
- Database connection reopened after backup/restore lifecycle.

Implementation note:

`sqlite:kylin-stock.db` is resolved by the current Tauri SQL plugin under the Tauri `app_config_dir`; the native backup module deliberately resolves the same directory before accessing `kylin-stock.db`.

Validation remaining:

- TypeScript build.
- Rust `cargo check` / Tauri build.
- Manual backup-create test.
- Annual-backup test.
- Modify-data -> restore -> data-recovered test.
- Corrupt/non-SQLite file rejection test.
- USB/removable-media backup target test on Kylin.

Exit criteria: a test database can be backed up, modified and restored correctly without losing the pre-restore safety copy.

## Phase 6 - UX Hardening

Status: **next after build validation**.

- Dashboard with real database statistics.
- Empty/loading/error states.
- Stronger form validation.
- Long-text handling.
- Chinese UI consistency.
- Confirmation dialogs for destructive actions.
- Table alignment requirement verification.
- Human-readable local date/time formatting.

## Phase 7 - Kylin ARM64 Compatibility

Target machine: Kylin Linux Desktop V10 JICAI, Phytium D2000, ARM64, UKUI.

Validate:

- runtime/WebKitGTK;
- native dependencies;
- SQLite;
- Chinese IME/fonts;
- XLSX export/file picker;
- backup/restore paths;
- removable-media write;
- desktop launcher;
- package installation;
- reboot persistence.

## Phase 8 - Acceptance

Execute all acceptance cases in REQUIREMENTS.md. Record failures and fixes. Produce installation/use notes and final release artifact.

## Scope Guard

Do not introduce procurement, sales, finance, SaaS, complex RBAC, barcode hardware, cloud dependency or multi-machine architecture unless REQUIREMENTS.md is explicitly revised.

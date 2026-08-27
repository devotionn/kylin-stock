# Kylin Tauri 1 Compatibility Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce an ARM64 Debian package that runs on the customer’s Kylin Linux Desktop V10 environment with WebKitGTK 4.0, while preserving the existing inventory, backup, export, OCR, and scanned-document workflows.

**Architecture:** Downgrade only the desktop shell boundary from Tauri 2 to Tauri 1. Keep Rust business commands and the Vue application behavior intact, replace Tauri 2 core/plugin imports with Tauri 1 APIs, and use the Tauri 1 SQL plugin for the existing frontend SQLite access. Build the Linux release on a Kylin/Ubuntu-20.04-compatible ARM64 baseline so the ELF links to `libwebkit2gtk-4.0.so.37`.

**Tech Stack:** Vue 3, TypeScript, Vite, Tauri 1.8.x, `@tauri-apps/api` 1.6.0, Tauri SQL plugin v1, Rust, SQLx, SQLite, WebKitGTK 4.0, Debian ARM64.

---

## Design Decisions

1. Do not edit only the `.deb` `Depends` field. The current binary requires the 4.1 SONAME, so a metadata-only workaround would install a package that cannot start on the customer machine.
2. Use Tauri 1.8.3 and `tauri-build` 1.5.6. Tauri’s documented Linux support maps WebKitGTK 4.0 to Tauri 1 and 4.1 to Tauri 2.
3. Remove Tauri 2 dialog and filesystem plugins from the Rust side. Tauri 1 provides dialog and filesystem APIs through `@tauri-apps/api`, protected by the v1 allowlist.
4. Use the official Tauri SQL v1 mirror package `tauri-plugin-sql-api` and the `v1` plugin-workspace branch. Preserve the current `Database.load`, `select`, `execute`, and `close` calls so database semantics and paths remain unchanged.
5. Keep the existing `src-tauri/capabilities` files untouched for now. They are Tauri 2 metadata and are not referenced by the Tauri 1 configuration, but deleting them is unnecessary and would increase unrelated change scope.

## Task 1: Add a failing Debian compatibility contract

**Files:**
- Create: `scripts/verify-kylin-deb.sh`
- Modify: `.github/workflows/ci.yml`

**Steps:**

1. Write a Bash script that accepts one `.deb`, reads `Package`, `Architecture`, `Depends`, and uses `readelf -d` on the extracted executable when available.
2. Require package `kylin-stock`, architecture `arm64`, a dependency on `libwebkit2gtk-4.0-37`, and no dependency on `libwebkit2gtk-4.1-0`.
3. Run it against the existing `release/kylin-stock_0.1.0_arm64.deb`; it must fail because the current package depends on 4.1. This is the baseline failing check.
4. Add the script after ARM64 package creation and before installation in CI.

## Task 2: Migrate frontend package dependencies and imports

**Files:**
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `src/services/backup.ts`
- Modify: `src/services/database.ts`
- Modify: `src/services/documentRecognition.ts`
- Modify: `src/services/export.ts`
- Modify: `src/services/inventory.ts`
- Modify: `src/views/DocumentImportView.vue`

**Steps:**

1. Pin `@tauri-apps/api` to the v1 line, pin `@tauri-apps/cli` to the v1 line, remove `@tauri-apps/plugin-dialog` and `@tauri-apps/plugin-fs`, and replace the v2 SQL package with `tauri-plugin-sql-api` from the official `v1` GitHub tag.
2. Replace `@tauri-apps/api/core` imports with `@tauri-apps/api/tauri`.
3. Replace `@tauri-apps/plugin-dialog` imports with `@tauri-apps/api/dialog`.
4. Replace `@tauri-apps/plugin-fs` `writeFile` with Tauri 1 `writeBinaryFile`.
5. Replace the SQL import with `tauri-plugin-sql-api`. Keep the existing SQL statements, bind arrays, and database close/error behavior unchanged.
6. Run `npm install --package-lock-only` or an equivalent locked install update, then run `npm run build`.

## Task 3: Migrate Rust dependencies and path APIs

**Files:**
- Modify: `src-tauri/Cargo.toml`
- Modify: `src-tauri/Cargo.lock`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src-tauri/src/backup.rs`
- Modify: `src-tauri/src/document_import.rs`
- Modify: `src-tauri/src/inventory.rs`
- Modify: `src-tauri/src/migration.rs`
- Modify: `src-tauri/src/ocr.rs`

**Steps:**

1. Set `tauri = "1.8.3"` and `tauri-build = "1.5.6"`.
2. Remove Tauri 2 dialog and filesystem Rust plugins.
3. Replace the SQL dependency with the official Tauri SQL v1 Git dependency using the `sqlite` feature.
4. Register only the SQL v1 plugin in `lib.rs` and remove the Tauri 2 mobile entry-point attribute.
5. Replace Tauri 2 `app.path().app_config_dir()` and `app.path().resource_dir()` calls with Tauri 1 `app.path_resolver().app_config_dir()` and `app.path_resolver().resource_dir()` calls, preserving all existing error handling and data locations.
6. Run `cargo check --locked --manifest-path src-tauri/Cargo.toml` on Windows to catch Rust/API errors before Linux packaging.

## Task 4: Convert configuration and Linux build baseline

**Files:**
- Modify: `src-tauri/tauri.conf.json`
- Modify: `src-tauri/tauri.linux.conf.json`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/KYLIN_DEPLOYMENT.md`

**Steps:**

1. Convert the Tauri 2 config shape to the Tauri 1 shape: `package`, `tauri.windows`, `tauri.allowlist`, and `tauri.bundle`.
2. Enable only the required v1 dialog `open`/`save` and filesystem `writeFile` allowlist entries. Keep save-dialog-selected paths working for XLSX export.
3. Set Linux Debian target metadata to the v1-generated WebKitGTK 4.0 dependency and retain the ASCII package name `kylin-stock` plus Chinese desktop entry name.
4. Update CI dependencies from `libwebkit2gtk-4.1-dev` to `libwebkit2gtk-4.0-dev` only in the compatibility build job. Keep the separate OCR jobs unchanged.
5. Document that this is a Kylin V10 WebKitGTK 4.0 release and that the package must be built on the oldest supported 4.0-compatible ARM64 baseline.

## Task 5: Verify the package and application behavior

**Files:**
- Test: `scripts/verify-kylin-deb.sh`
- Test: existing `tests/test_ocr_worker.py`, `tests/test_hough_shape.py`
- Test: existing Rust unit tests under `src-tauri/src`

**Steps:**

1. Run `npm ci --no-audit --no-fund` and `npm run build`; expect both to pass.
2. Run `cargo test --locked --manifest-path src-tauri/Cargo.toml --lib -- --nocapture`; expect existing migration, inventory, OCR, and document-import tests to pass.
3. Run the package verification script against the newly built ARM64 `.deb`; expect it to pass and report WebKitGTK 4.0.
4. Install the package in a Kylin V10 ARM64 test environment with `sudo dpkg -i`; expect no unsatisfied `libwebkit2gtk-4.1-0` dependency.
5. Launch the desktop entry and manually smoke-test startup, database initialization, material CRUD, stock in/out, XLSX export, backup/restore, OCR import, and restart persistence.
6. Run `scripts/kylin-acceptance-evidence.sh` on the customer machine and archive the output with the release package.

## Task 6: Commit the migration in reviewable units

**Steps:**

1. Commit the compatibility contract and plan documentation.
2. Commit the dependency/API migration.
3. Commit configuration, CI, and documentation changes.
4. Commit only after the local checks pass; do not stage existing customer artifacts such as `release/`, OCR diagnostics, or generated icon files unless explicitly requested.

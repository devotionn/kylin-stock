#!/usr/bin/env bash
set -u

# KylinStock target-machine acceptance evidence collector.
# Read-only: this script does not install packages, modify the database, or launch the app.

PRODUCT_NAME='物资管理系统'
APP_IDENTIFIER='com.devotionn.kylinstock'
DB_NAME='kylin-stock.db'

section() {
  printf '\n===== %s =====\n' "$1"
}

pass() { printf '[PASS] %s\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1"; }
info() { printf '[INFO] %s\n' "$1"; }

first_line() {
  "$@" 2>/dev/null | head -n 1 || true
}

section 'Evidence Metadata'
printf 'Collected at: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')"
printf 'Hostname: %s\n' "$(hostname 2>/dev/null || printf 'unknown')"
printf 'Product: %s\n' "$PRODUCT_NAME"
printf 'Identifier: %s\n' "$APP_IDENTIFIER"

section 'Target Platform'
arch="$(uname -m 2>/dev/null || true)"
kernel="$(uname -r 2>/dev/null || true)"
printf 'Architecture: %s\n' "${arch:-unknown}"
printf 'Kernel: %s\n' "${kernel:-unknown}"
if [ "$arch" = 'aarch64' ]; then
  pass 'CPU architecture is aarch64 / ARM64'
else
  warn "Expected aarch64 on the customer Phytium D2000 machine; got ${arch:-unknown}"
fi

if [ -r /etc/os-release ]; then
  grep -E '^(NAME|PRETTY_NAME|VERSION|VERSION_ID|ID|KYLIN_RELEASE_ID)=' /etc/os-release || true
else
  warn '/etc/os-release is not readable'
fi

if command -v lscpu >/dev/null 2>&1; then
  lscpu | grep -E '^(Architecture|CPU\(s\)|Model name|Vendor ID|Thread|Core|Socket):' || true
fi

section 'Desktop / Locale'
printf 'XDG_CURRENT_DESKTOP: %s\n' "${XDG_CURRENT_DESKTOP:-unknown}"
printf 'XDG_SESSION_TYPE: %s\n' "${XDG_SESSION_TYPE:-unknown}"
printf 'LANG: %s\n' "${LANG:-unknown}"
printf 'LC_ALL: %s\n' "${LC_ALL:-unset}"

section 'Runtime ABI / GUI Dependencies'
printf 'glibc: %s\n' "$(first_line ldd --version)"
if command -v pkg-config >/dev/null 2>&1; then
  for spec in 'webkit2gtk-4.1:WebKitGTK 4.1' 'webkit2gtk-4.0:WebKitGTK 4.0' 'gtk+-3.0:GTK 3' 'openssl:OpenSSL'; do
    key="${spec%%:*}"
    label="${spec#*:}"
    version="$(pkg-config --modversion "$key" 2>/dev/null || true)"
    if [ -n "$version" ]; then
      pass "$label available: $version"
    else
      warn "$label not reported by pkg-config"
    fi
  done
else
  warn 'pkg-config is not installed; GUI dependency versions cannot be queried this way'
fi

section 'Installed KylinStock Package'
package_found=0
if command -v dpkg-query >/dev/null 2>&1; then
  if dpkg-query -W -f='Package: ${Package}\nVersion: ${Version}\nArchitecture: ${Architecture}\nStatus: ${Status}\n' kylin-stock 2>/dev/null; then
    package_found=1
    pass 'dpkg package kylin-stock is installed'
  else
    matches="$(dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\t${Status}\n' 2>/dev/null | grep -Ei 'kylin[-_]?stock|devotionn|物资' || true)"
    if [ -n "$matches" ]; then
      printf '%s\n' "$matches"
      package_found=1
      pass 'A package matching KylinStock identifiers is installed'
    else
      warn 'No installed dpkg package matched kylin-stock / devotionn / 物资'
    fi
  fi
else
  warn 'dpkg-query is unavailable; package installation cannot be proven with dpkg'
fi

section 'Desktop Entry'
desktop_entry=''
for root in /usr/share/applications /usr/local/share/applications "${HOME:-}/.local/share/applications"; do
  [ -d "$root" ] || continue
  while IFS= read -r candidate; do
    if grep -Eqi "${APP_IDENTIFIER}|kylin[-_]?stock|${PRODUCT_NAME}" "$candidate" 2>/dev/null; then
      desktop_entry="$candidate"
      break 2
    fi
  done < <(find "$root" -maxdepth 1 -type f -name '*.desktop' 2>/dev/null)
done

if [ -n "$desktop_entry" ]; then
  pass "Desktop entry found: $desktop_entry"
  grep -E '^(Name|Exec|Icon|Terminal|Categories)=' "$desktop_entry" || true
else
  warn 'KylinStock desktop entry not found in standard application directories'
fi

section 'Executable / Dynamic Link Evidence'
executable=''
for candidate in \
  "$(command -v kylin-stock 2>/dev/null || true)" \
  /usr/bin/kylin-stock \
  /usr/local/bin/kylin-stock; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then
    executable="$candidate"
    break
  fi
done

if [ -z "$executable" ] && [ -n "$desktop_entry" ]; then
  exec_line="$(sed -n 's/^Exec=//p' "$desktop_entry" | head -n 1)"
  exec_token="${exec_line%% *}"
  if [ -n "$exec_token" ]; then
    if command -v "$exec_token" >/dev/null 2>&1; then
      executable="$(command -v "$exec_token")"
    elif [ -x "$exec_token" ]; then
      executable="$exec_token"
    fi
  fi
fi

if [ -n "$executable" ]; then
  pass "Executable found: $executable"
  if command -v file >/dev/null 2>&1; then
    file "$executable" || true
  fi
  if command -v ldd >/dev/null 2>&1; then
    missing="$(ldd "$executable" 2>/dev/null | grep 'not found' || true)"
    if [ -z "$missing" ]; then
      pass 'No missing shared libraries reported by ldd'
    else
      warn 'Missing shared libraries detected:'
      printf '%s\n' "$missing"
    fi
  fi
else
  if [ "$package_found" -eq 1 ]; then
    warn 'Package was found but executable path could not be resolved automatically'
  else
    warn 'Application executable not found'
  fi
fi

section 'Persistent SQLite Database'
config_root="${XDG_CONFIG_HOME:-${HOME:-}/.config}"
db_candidates=''
if [ -d "$config_root" ]; then
  db_candidates="$(find "$config_root" -maxdepth 5 -type f -name "$DB_NAME" -print 2>/dev/null || true)"
fi

if [ -z "$db_candidates" ]; then
  warn "No $DB_NAME found under ${config_root:-unknown}. This is expected before the app has initialized its database."
else
  while IFS= read -r db_path; do
    [ -n "$db_path" ] || continue
    pass "Database found: $db_path"
    if command -v stat >/dev/null 2>&1; then
      stat -c 'Size: %s bytes | Modified: %y' "$db_path" 2>/dev/null || true
    fi
    if command -v sha256sum >/dev/null 2>&1; then
      printf 'SHA256: '
      sha256sum "$db_path" 2>/dev/null | awk '{print $1}' || true
    fi
    if command -v sqlite3 >/dev/null 2>&1; then
      printf 'PRAGMA user_version: '
      sqlite3 -readonly "$db_path" 'PRAGMA user_version;' 2>/dev/null || printf 'UNAVAILABLE\n'
      printf 'PRAGMA quick_check: '
      sqlite3 -readonly "$db_path" 'PRAGMA quick_check;' 2>/dev/null | head -n 1 || printf 'UNAVAILABLE\n'
      printf 'materials rows: '
      sqlite3 -readonly "$db_path" 'SELECT COUNT(*) FROM materials;' 2>/dev/null || printf 'UNAVAILABLE\n'
      printf 'stock_transactions rows: '
      sqlite3 -readonly "$db_path" 'SELECT COUNT(*) FROM stock_transactions;' 2>/dev/null || printf 'UNAVAILABLE\n'
    else
      info 'sqlite3 CLI not installed; database version/integrity query skipped (the app itself does not require sqlite3 CLI)'
    fi
  done <<< "$db_candidates"
fi

section 'Acceptance Evidence Summary'
if [ "$arch" = 'aarch64' ]; then
  pass 'Architecture gate'
else
  warn 'Architecture gate'
fi
if [ "$package_found" -eq 1 ]; then
  pass 'Installation evidence gate'
else
  warn 'Installation evidence gate'
fi
if [ -n "$desktop_entry" ]; then
  pass 'Desktop entry evidence gate'
else
  warn 'Desktop entry evidence gate'
fi
if [ -n "$executable" ]; then
  pass 'Executable evidence gate'
else
  warn 'Executable evidence gate'
fi

cat <<'EOF'

This collector is intentionally read-only and does NOT mark business acceptance as passed.
Continue with docs/ACCEPTANCE_CHECKLIST.md for stock-in/out, query/export,
backup/restore, persistence, Chinese input, office-suite XLSX compatibility, and reboot tests.
EOF

#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  printf 'Usage: %s path/to/kylin-stock_*.deb\n' "$0" >&2
  exit 2
fi

deb="$1"
if [ ! -f "$deb" ]; then
  printf 'Debian package not found: %s\n' "$deb" >&2
  exit 2
fi

for command_name in dpkg-deb mktemp readelf; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command_name" >&2
    exit 2
  fi
done

package_name="$(dpkg-deb --field "$deb" Package)"
architecture="$(dpkg-deb --field "$deb" Architecture)"
depends="$(dpkg-deb --field "$deb" Depends)"

printf 'Package=%s\n' "$package_name"
printf 'Architecture=%s\n' "$architecture"
printf 'Depends=%s\n' "$depends"

if [ "$package_name" != 'kylin-stock' ]; then
  printf 'Unexpected Debian package name: %s\n' "$package_name" >&2
  exit 1
fi

if [ "$architecture" != 'arm64' ]; then
  printf 'Unexpected Debian architecture: %s\n' "$architecture" >&2
  exit 1
fi

if ! grep -Eq '(^|, )[[:space:]]*libwebkit2gtk-4\.0-37([[:space:]]|,|$)' <<<"$depends"; then
  printf 'Package does not declare libwebkit2gtk-4.0-37: %s\n' "$depends" >&2
  exit 1
fi

if grep -Eq '(^|, )[[:space:]]*libwebkit2gtk-4\.1-0([[:space:]]|,|$)' <<<"$depends"; then
  printf 'Package still declares the incompatible WebKitGTK 4.1 runtime.\n' >&2
  exit 1
fi

inspect_dir="$(mktemp -d)"
trap 'rm -rf "$inspect_dir"' EXIT
dpkg-deb --extract "$deb" "$inspect_dir"

binary="$inspect_dir/usr/bin/kylin-stock"
if [ ! -x "$binary" ]; then
  printf 'Installed executable not found in package: %s\n' "$binary" >&2
  exit 1
fi

needed="$(readelf -d "$binary" 2>/dev/null | sed -n 's/.*Shared library: \[\([^]]*\)\].*/\1/p')"
if ! grep -Fxq 'libwebkit2gtk-4.0.so.37' <<<"$needed"; then
  printf 'Executable is not linked to libwebkit2gtk-4.0.so.37.\n' >&2
  printf 'NEEDED entries:\n%s\n' "$needed" >&2
  exit 1
fi
if grep -Fxq 'libwebkit2gtk-4.1.so.0' <<<"$needed"; then
  printf 'Executable still links to libwebkit2gtk-4.1.so.0.\n' >&2
  exit 1
fi
printf 'WebKitGTK SONAME=libwebkit2gtk-4.0.so.37\n'

printf 'Kylin WebKitGTK 4.0 package contract: PASS\n'

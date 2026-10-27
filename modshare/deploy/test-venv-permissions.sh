#!/usr/bin/env bash
# Small Linux permission regression fixture; does not touch the actual site.
# Requires root and the already-created modshare service user.
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Run as root on Linux.' >&2; exit 1; }
id modshare >/dev/null
umask 077
fixture=$(mktemp -d /tmp/modshare-venv-permissions.XXXXXXXX)
cleanup() {
    case "$fixture" in /tmp/modshare-venv-permissions.*) rm -rf -- "$fixture";; *) exit 1;; esac
}
trap cleanup EXIT
chmod 0755 "$fixture"
mkdir -p "$fixture/venv/bin" "$fixture/venv/lib" "$fixture/secrets" "$fixture/data"
printf '#!/bin/sh\nexit 0\n' > "$fixture/venv/bin/python"
chmod 0700 "$fixture/venv/bin/python"
printf 'fixture package\n' > "$fixture/venv/lib/package.py"
printf 'fixture secret\n' > "$fixture/secrets/config.json"
printf 'fixture database\n' > "$fixture/data/modshare.db"
if runuser -u modshare -- test -x "$fixture/venv/bin/python"; then
    echo 'Fixture failed to reproduce umask 077 inaccessible venv.' >&2
    exit 1
fi
chown -hR root:root "$fixture/venv"
chmod -R a+rX,go-w "$fixture/venv"
runuser -u modshare -- "$fixture/venv/bin/python"
runuser -u modshare -- test -r "$fixture/venv/lib/package.py"
runuser -u modshare -- test ! -w "$fixture/venv/bin/python"
runuser -u modshare -- test ! -w "$fixture/venv"
runuser -u modshare -- test ! -r "$fixture/secrets/config.json"
runuser -u modshare -- test ! -r "$fixture/data/modshare.db"
echo 'PASS: root-owned venv is readable/executable but not writable; secret/data fixture stays private.'

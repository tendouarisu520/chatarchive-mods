#!/usr/bin/env bash
# Root-only consistent snapshot. Pauses only this site's service, then resumes.
set -Eeuo pipefail
umask 077
[[ ${EUID} -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
base=/opt/modshare
destination=${1:-$base/backups}
[[ "$destination" = /* && ! -L "$destination" ]] || { echo 'Use an absolute, non-symlink backup directory.' >&2; exit 1; }
install -d -m 0700 -o root -g root "$destination"
destination=$(realpath -e -- "$destination")
case "$destination/" in "$base/data/"*|"$base/app/"*|"$base/venv/"*) echo 'Backups must be outside runtime/source directories.' >&2; exit 1;; esac
snapshot="$destination/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -m 0700 "$snapshot"
was_active=0
systemctl is-active --quiet modshare.service && was_active=1
resume() {
    local exit_code=$?
    trap - EXIT
    if [[ $was_active -eq 1 ]]; then
        systemctl start modshare.service || exit_code=1
    fi
    [[ $exit_code -eq 0 ]] || echo "Backup incomplete; inspect $snapshot" >&2
    exit "$exit_code"
}
trap resume EXIT
if [[ $(systemctl show -p LoadState --value modshare.service) != not-found ]]; then
    systemctl stop modshare.service
fi
python3 "$(dirname "$0")/backup_snapshot.py" "$base" "$snapshot"
echo "Verified snapshot: $snapshot"

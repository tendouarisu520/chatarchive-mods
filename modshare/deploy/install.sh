#!/usr/bin/env bash
# Run as root with a staged source directory containing manage.py and deploy/.
# Package/dependency installation can be long: launch using the README's nohup.
set -Eeuo pipefail
umask 077
[[ ${EUID} -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
source_dir=${1:?Usage: install.sh STAGED_SOURCE [PROTECTED_CONFIG_JSON]}
config_source=${2:-}
base=/opt/modshare
service=modshare.service
source_dir=$(realpath -e -- "$source_dir")
[[ -f "$source_dir/manage.py" && -f "$source_dir/requirements.txt" && -f "$source_dir/deploy/$service" ]] || { echo 'Incomplete staged source.' >&2; exit 1; }
[[ "$source_dir" != "$base/app" && "$source_dir" != "$base" ]] || { echo 'Use a separate staged source directory.' >&2; exit 1; }
case "$base/app/" in "$source_dir/"*) echo 'Staged source must not contain the installation destination.' >&2; exit 1;; esac
[[ -z $(find "$source_dir" -type l -print -quit) ]] || { echo 'Staged source must not contain symlinks.' >&2; exit 1; }
for executable in python3 runuser systemctl rsync setfacl; do command -v "$executable" >/dev/null; done
for directory in "$base" "$base/app" "$base/venv" "$base/data" "$base/secrets" "$base/backups"; do
    [[ ! -L "$directory" ]] || { echo "Refusing symlink target: $directory" >&2; exit 1; }
done
getent group modshare >/dev/null || groupadd --system modshare
if ! id modshare >/dev/null 2>&1; then
    useradd --system --gid modshare --home-dir "$base" --no-create-home --shell /usr/sbin/nologin modshare
fi
install -d -m 0755 -o root -g root "$base" "$base/app"
install -d -m 0750 -o root -g modshare "$base/secrets"
install -d -m 0700 -o root -g root "$base/backups"
install -d -m 0750 -o modshare -g modshare "$base/data" "$base/data/files" "$base/data/tmp" "$base/data/static"
if [[ -f "$base/data/modshare.db" ]]; then
    bash "$source_dir/deploy/backup.sh" "$base/backups"
fi
if [[ -n "$config_source" ]]; then
    [[ -f "$config_source" && ! -L "$config_source" ]] || { echo 'Expected a regular protected configuration file.' >&2; exit 1; }
    if [[ $(realpath -e -- "$config_source") != "$base/secrets/config.json" ]]; then
        install -m 0640 -o root -g modshare "$config_source" "$base/secrets/config.json"
    fi
fi
[[ -f "$base/secrets/config.json" && ! -L "$base/secrets/config.json" ]] || { echo 'Supply protected configuration JSON before installing.' >&2; exit 1; }
chown root:modshare "$base/secrets/config.json"
chmod 0640 "$base/secrets/config.json"
python3 - "$base/secrets/config.json" <<'PY'
import json, sys
config = json.load(open(sys.argv[1], encoding='utf-8-sig'))
assert len(config.get('secret_key', '')) >= 32 and 'REPLACE' not in config['secret_key'], 'Set a real random secret key.'
assert config.get('allowed_hosts') and isinstance(config.get('secure'), bool), 'Configure explicit allowed_hosts and secure.'
if not config['secure']:
    assert set(config['allowed_hosts']) <= {'127.0.0.1', 'localhost', '[::1]'}, 'Insecure preview must allow loopback hosts only.'
assert config.get('script_name', '') == '', 'This independent site uses the domain root, with no URL prefix.'
smtp = config.get('smtp', {})
assert all(smtp.get(key) for key in ('host', 'port', 'username', 'password', 'from')), 'Configure SMTP.'
assert smtp.get('ssl') is True, 'Production SMTP must use SSL.'
PY
if [[ ! -f "$base/secrets/runtime.env" ]]; then
    printf 'MOD_SCRIPT_NAME=\nMOD_X_ACCEL=1\n' > "$base/secrets/runtime.env"
fi
chown root:modshare "$base/secrets/runtime.env"
chmod 0640 "$base/secrets/runtime.env"
was_active=0
systemctl is-active --quiet "$service" && was_active=1
restart_previous() {
    local exit_code=$?
    if [[ $exit_code -ne 0 && $was_active -eq 1 ]]; then
        echo 'Install failed; service remains stopped for diagnosis. Use backup to restore before restarting.' >&2
    fi
    exit "$exit_code"
}
trap restart_previous EXIT
if [[ $(systemctl show -p LoadState --value "$service") != not-found ]]; then
    systemctl stop "$service"
fi
# Fixed isolated destination; excluded runtime/secrets can never enter app.
rsync -a --delete --exclude='.git/' --exclude='__pycache__/' --exclude='*.pyc' --exclude='.venv/' --exclude='venv/' --exclude='data/' --exclude='secrets/' --exclude='backups/' "$source_dir/" "$base/app/"
chown -R root:root "$base/app"
chmod -R a+rX,go-w "$base/app"
if [[ ! -x "$base/venv/bin/python" ]]; then python3 -m venv "$base/venv"; fi
"$base/venv/bin/python" -m pip install --disable-pip-version-check -r "$base/app/requirements.txt"
# umask 077 protects secrets, but would leave a root-created venv inaccessible
# to the service user. Only this root-owned, non-secret tree is made readable.
chown -hR root:root "$base/venv"
chmod -R a+rX,go-w "$base/venv"
runuser -u modshare -- "$base/venv/bin/python" -I -B -c 'import django, gunicorn, os, sys; assert os.access(sys.executable, os.X_OK); assert not os.access(sys.prefix, os.W_OK); print("Service-user venv access/import check passed.")'
export MOD_CONFIG_FILE="$base/secrets/config.json" MOD_DATA_DIR="$base/data" MOD_DEBUG=0 MOD_X_ACCEL=1 PYTHONDONTWRITEBYTECODE=1
# runtime.env only contains trusted operator-managed simple assignments.
set -a
source "$base/secrets/runtime.env"
set +a
cd "$base/app"
runuser -u modshare -- "$base/venv/bin/python" manage.py check --deploy
runuser -u modshare -- "$base/venv/bin/python" manage.py migrate --noinput
runuser -u modshare -- "$base/venv/bin/python" manage.py collectstatic --noinput
if [[ ${MOD_X_ACCEL:-0} == 1 ]]; then
    bash "$base/app/deploy/install-file-access.sh"
fi
install -m 0644 "$base/app/deploy/$service" "/etc/systemd/system/$service"
systemctl daemon-reload
systemctl enable "$service"
systemctl restart "$service"
systemctl is-active --quiet "$service"
echo 'ChatArchive service active on 127.0.0.1:3310. Root must validate/enable app/deploy/nginx-preview.conf for loopback3311 SSH preview. Future independent-domain TLS template is app/deploy/nginx-vhost.conf; Nginx was not changed.'

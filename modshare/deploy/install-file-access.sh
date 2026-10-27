#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
base=/opt/modshare
nginx_user=${NGINX_USER:-www-data}
id "$nginx_user" >/dev/null
command -v setfacl >/dev/null || { echo 'Install the acl package first.' >&2; exit 1; }
for directory in "$base/data" "$base/data/files" "$base/data/tmp" "$base/data/static"; do
    [[ -d "$directory" && ! -L "$directory" ]] || { echo "Unsafe/missing directory: $directory" >&2; exit 1; }
done
# The worker can traverse data, but cannot list it or read DB/config files.
setfacl -m "u:${nginx_user}:--x" "$base/data"
setfacl -R -m "u:${nginx_user}:rX" "$base/data/files" "$base/data/static"
find "$base/data/files" "$base/data/static" -type d -exec setfacl -m "d:u:${nginx_user}:r-x,d:m::r-x" {} +
# App creates final .blob directly in files and chmods it to 0640, enabling
# its inherited Nginx read ACL. Temporary uploads never get an Nginx ACL.
echo 'Nginx private-file/static access configured; data DB and secrets stay private.'

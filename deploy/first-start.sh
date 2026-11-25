#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $# == 4 ]] || { echo 'Usage: first-start.sh ABSOLUTE_DEPLOY_DIR IMAGE_ARCHIVE IMAGE_REFERENCE COMMIT_SHA' >&2; exit 2; }
root=$1
project=${VALUEFLOW_PROJECT:-valueflow-server}
[[ "$project" =~ ^valueflow[-a-z0-9]*$ ]] || exit 2
[[ "$root" == /* && "$root" != / ]] || exit 2
docker info >/dev/null
docker compose version
for program in flock openssl awk install ss grep; do command -v "$program" >/dev/null; done
mkdir -p -- "$root"
if [[ ! -e "$root/.env" ]]; then
  [[ -z $(docker ps --all --quiet --filter "label=com.docker.compose.project=$project") ]] || {
    echo 'Existing valueflow-server found; recover its configuration before initializing.' >&2; exit 1;
  }
  if docker volume inspect "${project}_postgres_data" >/dev/null 2>&1; then
    echo 'Existing database volume found; recover its configuration before initializing.' >&2; exit 1
  fi
  [[ ${KAKAO_APP_ID:-} =~ ^[1-9][0-9]*$ ]] || { echo 'Set KAKAO_APP_ID to the existing numeric app ID.' >&2; exit 2; }
  port=${API_PORT:-18081}
  [[ "$port" =~ ^[0-9]{1,5}$ ]] && (( port >= 1024 && port <= 65535 )) || exit 2
  if ss -H -ltn | awk '{print $4}' | grep -Eq ":${port}$"; then
    echo 'Selected API port is occupied. Choose a free API_PORT.' >&2; exit 1
  fi
  password=$(openssl rand -hex 24)
  # Noclobber protects concurrent first starts and existing configuration.
  (set -o noclobber; cat > "$root/.env" <<EOF
API_IMAGE=$3
API_PORT=$port
POSTGRES_DB=valueflow
POSTGRES_USER=valueflow
POSTGRES_PASSWORD=$password
DATABASE_URL=postgresql+psycopg://valueflow:$password@db:5432/valueflow
KAKAO_APP_ID=$KAKAO_APP_ID
CORS_ORIGINS=[]
SESSION_TTL_SECONDS=604800
ADMIN_SESSION_TTL_SECONDS=3600
EOF
  )
  unset password
fi
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/release.sh" "$@"

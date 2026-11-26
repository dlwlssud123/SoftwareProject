#!/usr/bin/env bash
set -euo pipefail
umask 077

# ValueFlow Scheduled Data Refresh Runner
# Runs public-data refresh inside a one-off API container with shared DB and persisted data.

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if [[ $# -gt 0 && "$1" == /* ]]; then
  root=$1
  shift
else
  root=$script_dir
fi
root=$(cd -- "$root" && pwd -P)

[[ -f "$root/.env" && -f "$root/compose.yaml" ]] || {
  echo "ValueFlow deployment configuration not found in $root." >&2
  exit 2
}

project=${VALUEFLOW_PROJECT:-valueflow-server}
mkdir -p -- "$root/.state" "$root/data/raw" "$root/data/processed"

# Shared deployment / refresh lock to avoid conflicts
exec 9>"$root/.state/deploy.lock"
flock -n 9 || {
  echo "Another deployment or refresh is holding deploy.lock; skipping this run." >&2
  exit 3
}

compose=(docker compose --project-name "$project" --project-directory "$root" --env-file "$root/.env" --file "$root/compose.yaml")

# Verify database container is running and healthy
db_container=$("${compose[@]}" ps --quiet db)
[[ -n "$db_container" ]] || {
  echo "ValueFlow database service is not running." >&2
  exit 1
}

# Run daily_refresh in a one-off API container
# -T ensures non-interactive execution for cron / CI
"${compose[@]}" run --rm --no-deps -T \
  --user "$(id -u):$(id -g)" \
  --volume "$root/data:/opt/valueflow/data:rw" \
  api python -m app.jobs.daily_refresh "$@"

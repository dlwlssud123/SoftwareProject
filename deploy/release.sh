#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# != 4 ]]; then
  echo 'Usage: release.sh ABSOLUTE_DEPLOY_DIR IMAGE_ARCHIVE IMAGE_REFERENCE COMMIT_SHA' >&2
  exit 2
fi
root=$1
archive=$2
image=$3
revision=$4
project=${VALUEFLOW_PROJECT:-valueflow-server}
wait_seconds=${DEPLOY_WAIT_SECONDS:-120}
[[ "$project" =~ ^valueflow[-a-z0-9]*$ && "$wait_seconds" =~ ^[0-9]+$ ]] || exit 2
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ "$root" == /* && "$root" != / && "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ -f "$root/.env" && ! -L "$root/.env" && -f "$archive" ]] || {
  echo 'Initialize this deployment with first-start.sh before deploying.' >&2
  exit 2
}
root=$(cd -- "$root" && pwd -P)
mkdir -p -- "$root/.state" "$root/backups"
exec 9>"$root/.state/deploy.lock"
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 3; }

# A shared server may already use this Compose project name from another path.
for container in $(docker ps --all --quiet --filter "label=com.docker.compose.project=$project"); do
  owner=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$container")
  [[ "$owner" == "$root" ]] || { echo 'valueflow-server belongs to a different deployment directory.' >&2; exit 1; }
done

docker load --input "$archive"
actual_revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
[[ "$actual_revision" == "$revision" ]] || { echo 'Image revision does not match the release.' >&2; exit 1; }
target=$(docker image inspect --format '{{.Id}}' "$image")
compose=(docker compose --project-name "$project" --project-directory "$root" --env-file "$root/.env" --file "$root/compose.yaml")
incoming=(docker compose --project-name "$project" --project-directory "$root" --env-file "$root/.env" --file "$source_dir/compose.yaml")
API_IMAGE="$target" "${incoming[@]}" config --quiet

previous_container=$(docker ps --quiet --filter "label=com.docker.compose.project=$project" --filter label=com.docker.compose.service=api)
previous_image=''
if [[ -n "$previous_container" ]]; then
  previous_image=$(docker inspect --format '{{.Image}}' "$previous_container")
fi
cp -- "$root/.env" "$root/.state/env.before"
had_compose=false
if [[ -f "$root/compose.yaml" ]]; then
  cp -- "$root/compose.yaml" "$root/.state/compose.before.yaml"
  had_compose=true
fi

set_image() {
  awk -v image="$1" 'BEGIN { found=0 } /^API_IMAGE=/ { print "API_IMAGE=" image; found=1; next } { print } END { if (!found) print "API_IMAGE=" image }' "$root/.env" > "$root/.state/env.next"
  chmod 600 "$root/.state/env.next"
  mv -- "$root/.state/env.next" "$root/.env"
}

recover() {
  result=$?
  trap - EXIT
  if (( result != 0 )); then
    cp -- "$root/.state/env.before" "$root/.env"
    if "$had_compose"; then cp -- "$root/.state/compose.before.yaml" "$root/compose.yaml"; fi
    if [[ -n "$previous_image" ]]; then
      set_image "$previous_image"
      echo 'Release failed; restoring the previous API image. Database backup is retained.' >&2
      if ! "${compose[@]}" up --detach --no-deps --wait --wait-timeout "$wait_seconds" api; then
        echo 'Previous API recovery also failed; inspect the deployment and database backup.' >&2
      fi
    else
      # Remove only this new API; keep the database and its volume for diagnosis.
      "${compose[@]}" stop api || true
      echo 'First deployment failed. Database and backup were preserved.' >&2
    fi
  fi
  exit "$result"
}
trap recover EXIT

install -m 644 -- "$source_dir/compose.yaml" "$root/compose.yaml"
mkdir -p -- "$root/initdb"
install -m 644 -- "$source_dir/initdb/001-vector.sql" "$root/initdb/001-vector.sql"
set_image "$target"
"${compose[@]}" up --detach --wait --wait-timeout "$wait_seconds" db
backup="$root/backups/$(date -u +%Y%m%dT%H%M%SZ)-${revision:0:12}-$$.dump"
"${compose[@]}" exec -T db sh -eu -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner' > "$backup.pending"
[[ -s "$backup.pending" ]] || { echo 'Database backup is empty; deployment stopped.' >&2; exit 1; }
mv -- "$backup.pending" "$backup"
"${compose[@]}" run --rm --no-deps api alembic upgrade head
"${compose[@]}" up --detach --no-deps --wait --wait-timeout "$wait_seconds" api
container=$("${compose[@]}" ps --quiet api)
[[ -n "$container" && $(docker inspect --format '{{.Image}}' "$container") == "$target" ]]
[[ $(docker inspect --format '{{.State.Health.Status}}' "$container") == healthy ]]
printf 'revision=%s\nimage=%s\nprevious_image=%s\nbackup=%s\n' "$revision" "$target" "$previous_image" "$backup" > "$root/.state/release.next"
mv -- "$root/.state/release.next" "$root/.state/current-release"
echo "Deployment healthy: $revision"

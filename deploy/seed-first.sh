#!/usr/bin/env bash
set -euo pipefail
umask 077

[[ $# == 1 ]] || { echo 'Usage: seed-first.sh ABSOLUTE_DEPLOY_DIR' >&2; exit 2; }
[[ "$1" == /* && "$1" != / ]] || exit 2
root=$(cd -- "$1" && pwd -P)
seed=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ -f "$root/.env" && -f "$root/compose.yaml" ]] || {
  echo 'Complete first-start.sh before importing data.' >&2; exit 2;
}
for program in docker flock sha256sum; do command -v "$program" >/dev/null; done
[[ -f "$seed/data/raw/recipes/cookrcp01_all.json" &&
   -f "$seed/data/raw/nutrition/foodntr_v03_representative.json" ]] || {
  echo 'Both public snapshots are required.' >&2; exit 2;
}
(cd -- "$seed" && sha256sum --check snapshots.sha256)
compose=(docker compose --project-name valueflow-server --project-directory "$root"
         --env-file "$root/.env" --file "$root/compose.yaml")
database=$("${compose[@]}" ps --quiet db)
[[ -n "$database" ]] || { echo 'Start the ValueFlow database first.' >&2; exit 1; }
owner=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$database")
[[ "$owner" == "$root" ]] || { echo 'Database belongs to another deployment directory.' >&2; exit 1; }
mkdir -p -- "$root/.state" "$root/backups"
exec 9>"$root/.state/deploy.lock"
flock -n 9 || { echo 'Another deployment or initial import is running.' >&2; exit 3; }

backup="$root/backups/before-seed-$(date -u +%Y%m%dT%H%M%SZ)-$$.dump"
"${compose[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$backup.pending"
[[ -s "$backup.pending" ]]
mv -- "$backup.pending" "$backup"
echo "Database backup: $backup"

# A separate one-off container reuses the deployed code and DB network. Bind
# only public snapshots read-only; no ports or additional DB service are created.
run=("${compose[@]}" --file "$seed/seed.compose.yaml" run --rm --no-deps -T --user "$(id -u):$(id -g)"
     --volume "$seed/data:/opt/valueflow/data:ro" api)
"${run[@]}" alembic upgrade head
"${run[@]}" python -m app.jobs.import_public_data --dry-run
"${run[@]}" python -m app.jobs.import_public_data --apply
"${run[@]}" python -m app.jobs.import_public_data --verify
"${run[@]}" python -m app.jobs.map_recipe_foods --apply
"${run[@]}" python -m app.jobs.map_recipe_foods --verify
echo 'Recipe/food import and computed nutrition verified. Welfare, facilities, seasonal and RAG were not imported.'

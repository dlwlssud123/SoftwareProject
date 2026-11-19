#!/usr/bin/env bash
# Disposable Docker integration test. Never point this at a real deployment.
set -euo pipefail
image=${1:?Pass the tested backend image}
revision=${2:?Pass its commit SHA}
scripts=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Compose prioritizes exported variables over --env-file. The API test lane's
# host DB URL must not replace this disposable deployment's generated DB URL.
unset DATABASE_URL POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD API_IMAGE
root=${RELEASE_TEST_DIR:-$(mktemp -d)}/server
export VALUEFLOW_PROJECT="valueflow-release-test-$$"
export DEPLOY_WAIT_SECONDS=35
export KAKAO_APP_ID=1
export API_PORT=${RELEASE_TEST_PORT:-18091}
mkdir -p -- "$root"
[[ ! -e "$root/.env" ]] || { echo 'Test requires a fresh directory.' >&2; exit 2; }
archive="$root/../image.tar"
docker image save --output "$archive" "$image"
cleanup() {
  result=$?
  if [[ -f "$root/.env" ]]; then
    # Only this test-created, uniquely named Compose project is disposable.
    docker compose --project-name "$VALUEFLOW_PROJECT" --project-directory "$root" --env-file "$root/.env" --file "$root/compose.yaml" down --volumes --remove-orphans || true
  fi
  exit "$result"
}
trap cleanup EXIT
bash "$scripts/first-start.sh" "$root" "$archive" "$image" "$revision"
compose=(docker compose --project-name "$VALUEFLOW_PROJECT" --project-directory "$root" --env-file "$root/.env" --file "$root/compose.yaml")
original=$(docker image inspect --format '{{.Id}}' "$image")
"${compose[@]}" exec -T db sh -eu -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "INSERT INTO users (id, role) VALUES ('\''11111111-1111-1111-1111-111111111111'\'', '\''user'\'');"'

before=$(sha256sum "$root/.env")
if bash "$scripts/release.sh" "$root" "$archive" "$image" 0000000000000000000000000000000000000000; then
  echo 'Mismatched image revision was accepted.' >&2; exit 1
fi
[[ $(sha256sum "$root/.env") == "$before" ]]

broken="valueflow-release-broken:$$"
printf 'FROM %s\nCMD ["python", "-c", "raise SystemExit(1)"]\n' "$image" |
  docker build --tag "$broken" --label "org.opencontainers.image.revision=$revision" --file - "$scripts"
docker image save --output "$archive" "$broken"
if bash "$scripts/release.sh" "$root" "$archive" "$broken" "$revision"; then
  echo 'Broken release unexpectedly succeeded.' >&2; exit 1
fi
container=$("${compose[@]}" ps --quiet api)
[[ $(docker inspect --format '{{.Image}}' "$container") == "$original" ]]
[[ $(docker inspect --format '{{.State.Health.Status}}' "$container") == healthy ]]
count=$("${compose[@]}" exec -T db sh -eu -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM users WHERE id = '\''11111111-1111-1111-1111-111111111111'\'';"')
[[ "$count" == 1 ]]
[[ -n $(find "$root/backups" -name '*.dump' -size +0c -print -quit) ]]
echo 'Release integration passed: first deployment, backup, revision rejection, failed-release rollback, persistent data.'

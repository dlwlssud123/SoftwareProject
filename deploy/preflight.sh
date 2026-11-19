#!/usr/bin/env bash
set -euo pipefail
echo '== OS and resources =='
cat /etc/os-release | head -n 3
uname -m
free -h
df -h "$HOME"
echo '== Docker =='
docker --version
docker compose version
docker info >/dev/null
docker compose ls
echo '== Listening TCP ports =='
ss -ltn
echo '== Existing ValueFlow resources =='
docker ps --all --filter label=com.docker.compose.project=valueflow-server --format '{{.Names}} {{.Status}} {{.Ports}}'
echo 'Review these results before running first-start.sh.'

#!/usr/bin/env bash
set -euo pipefail
umask 077
check_only=false
if [[ ${1:-} == --check ]]; then check_only=true; shift; fi
[[ $# == 1 && -f "$1" ]] || { echo 'Usage: authorize-key.sh [--check] PUBLIC_KEY_FILE' >&2; exit 2; }
key=$(cat -- "$1")
# OpenSSH on Windows writes CRLF; command substitution removes only LF.
key=${key%$'\r'}
[[ "$key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+\ [a-zA-Z0-9_-]+$ ]] || {
  echo 'Expected one ed25519 public key line.' >&2; exit 2;
}
if "$check_only"; then echo 'Deployment public key format valid.'; exit 0; fi
mkdir -p -- "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch -- "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
entry="restrict $key"
if ! grep --fixed-strings --line-regexp --quiet -- "$entry" "$HOME/.ssh/authorized_keys"; then
  printf '%s\n' "$entry" >> "$HOME/.ssh/authorized_keys"
fi
echo 'Deployment public key registered for the current user.'

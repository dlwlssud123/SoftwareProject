"""Prepare an isolated deployment key; optionally configure GitHub development CD."""

import argparse
import os
import re
import subprocess
from pathlib import Path

LOCAL = Path(__file__).resolve().parent / ".local"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Write GitHub secrets and variables; CD stays disabled",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Enable CD only after an authenticated server health check",
    )
    parser.add_argument("--repo", default="dlwlssud123/SoftwareProject")
    parser.add_argument("--host", default="210.90.113.81")
    parser.add_argument("--port", type=int, default=1190)
    parser.add_argument("--user", default="kapje90")
    parser.add_argument("--directory", default="/home/kapje90/Documents/ValueFlow")
    args = parser.parse_args()
    if not (
        re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo)
        and re.fullmatch(r"[a-zA-Z0-9.-]+", args.host)
        and re.fullmatch(r"[a-zA-Z0-9_-]+", args.user)
        and re.fullmatch(r"/[a-zA-Z0-9_./-]+", args.directory)
        and args.directory != "/"
        and ".." not in args.directory
        and 1 <= args.port <= 65535
    ):
        parser.error("Invalid deployment target")
    LOCAL.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = LOCAL / "github-actions-key"
    hosts = LOCAL / "known_hosts"
    if not key.exists():
        run(
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-f",
            str(key),
            "-N",
            "",
            "-C",
            "valueflow-actions",
        )
    if not key.with_suffix(".pub").exists():
        raise SystemExit(
            "Deployment public key is missing; do not replace the existing private key"
        )
    lookup = f"[{args.host}]:{args.port}" if args.port != 22 else args.host
    trusted = run(
        "ssh-keygen",
        "-F",
        lookup,
        "-f",
        str(Path.home() / ".ssh" / "known_hosts"),
        capture_output=True,
        text=True,
    )
    lines = [
        line
        for line in trusted.stdout.splitlines()
        if line and not line.startswith("#")
    ]
    if not lines:
        raise SystemExit(
            "No previously trusted SSH host key found; verify the server fingerprint before configuring CD"
        )
    hosts.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(key, 0o600)
    os.chmod(hosts, 0o600)
    if args.configure:
        run(
            "gh",
            "api",
            "--method",
            "PUT",
            f"repos/{args.repo}/environments/development",
            stdout=subprocess.DEVNULL,
        )
        for name, file in (
            ("VALUEFLOW_SSH_KEY", key),
            ("VALUEFLOW_KNOWN_HOSTS", hosts),
        ):
            run(
                "gh",
                "secret",
                "set",
                name,
                "--repo",
                args.repo,
                "--env",
                "development",
                input=file.read_bytes(),
            )
        variables = {
            "VALUEFLOW_DEPLOY_HOST": args.host,
            "VALUEFLOW_DEPLOY_PORT": str(args.port),
            "VALUEFLOW_DEPLOY_USER": args.user,
            "VALUEFLOW_DEPLOY_DIR": args.directory,
            "VALUEFLOW_CD_ENABLED": "false",
        }
        for name, value in variables.items():
            run("gh", "variable", "set", name, "--repo", args.repo, "--body", value)
        print(
            "GitHub development secrets configured. Automatic deployment is disabled."
        )
    if args.enable:
        directory = args.directory
        command = (
            f"cd '{directory}' && test -s .state/current-release && "
            "container=$(docker compose --project-name valueflow-server --env-file .env --file compose.yaml ps --quiet api) && "
            'test -n "$container" && test "$(docker inspect --format \'{{.State.Health.Status}}\' "$container")" = healthy'
        )
        run(
            "ssh",
            "-i",
            str(key),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={hosts}",
            "-o",
            "ConnectTimeout=10",
            "-p",
            str(args.port),
            f"{args.user}@{args.host}",
            command,
        )
        run(
            "gh",
            "variable",
            "set",
            "VALUEFLOW_CD_ENABLED",
            "--repo",
            args.repo,
            "--body",
            "true",
        )
        print("Existing server deployment is healthy; main-branch CD enabled.")
    if not args.configure and not args.enable:
        print(
            "Local deployment key and previously trusted host key prepared. GitHub and server were not modified."
        )


if __name__ == "__main__":
    main()

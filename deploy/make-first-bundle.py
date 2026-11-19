"""Build a first-deployment bundle without local databases or private credentials."""

import io
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run(
        [sys.executable, str(ROOT / "deploy/configure-github.py")], check=True
    )
    app_id = next(
        (
            line.partition("=")[2].strip().strip("\"'")
            for line in (ROOT / "src/backend/.env")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.startswith("KAKAO_APP_ID=")
        ),
        "",
    )
    if not re.fullmatch(r"[1-9][0-9]*", app_id):
        raise SystemExit("Set the existing numeric KAKAO_APP_ID in src/backend/.env")
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    image = "valueflow-backend:first"
    subprocess.run(
        [
            "docker",
            "build",
            "--file",
            "src/backend/Dockerfile",
            "--label",
            f"org.opencontainers.image.revision={revision}",
            "--tag",
            image,
            ".",
        ],
        cwd=ROOT,
        check=True,
    )
    stage = ROOT / "dist/valueflow-first"
    stage.mkdir(parents=True, exist_ok=True)
    image_archive = stage / "image.tar"
    subprocess.run(
        ["docker", "save", "--output", str(image_archive), image], check=True
    )
    output = ROOT / "dist/valueflow-first-deploy.tar.gz"
    with tarfile.open(output, "w:gz", compresslevel=1) as bundle:
        bundle.add(image_archive, arcname="image.tar")
        for name in [
            "compose.yaml",
            "release.sh",
            "first-start.sh",
            "preflight.sh",
            "authorize-key.sh",
            "initdb/001-vector.sql",
        ]:
            bundle.add(ROOT / "deploy" / name, arcname=f"deploy/{name}")
        bundle.add(
            ROOT / "deploy/.local/github-actions-key.pub", arcname="github-actions.pub"
        )
        command = (
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            'cd -- "$(dirname -- "${BASH_SOURCE[0]}")"\n'
            f'KAKAO_APP_ID={app_id} bash deploy/first-start.sh "$HOME/Documents/ValueFlow" '
            f'"$PWD/image.tar" {image} {revision}\n'
        )
        content = command.encode("utf-8")
        info = tarfile.TarInfo("run-first.sh")
        info.size = len(content)
        info.mode = 0o700
        bundle.addfile(info, io.BytesIO(content))
    print(
        f"First-deployment bundle ready: {output} ({output.stat().st_size // 1024 // 1024} MiB)"
    )
    print(
        "Includes the public deployment key and numeric app ID; excludes private keys, API keys, .env and local DB data."
    )


if __name__ == "__main__":
    main()

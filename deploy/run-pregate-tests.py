"""Run every selected Python/Vitest file with its own runtime, without a shell."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def commands(files, root=ROOT):
    python_files, web_files = [], []
    root = root.resolve()
    admin = root / "src/admin"
    if not files:
        raise ValueError("No test files selected")
    for name in files:
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Selected test must be an existing repository file")
        if path.suffix == ".py":
            python_files.append(str(path.relative_to(root)))
        elif path.is_relative_to(admin) and path.name.endswith(
            (".test.ts", ".test.tsx")
        ):
            web_files.append(str(path.relative_to(admin)))
        else:
            raise ValueError("Unsupported test runtime; no selected file was skipped")
    result = []
    if python_files:
        result.append((root, [sys.executable, "-m", "pytest", "-q", *python_files]))
    if web_files:
        node = shutil.which("node")
        entry = admin / "node_modules/vitest/vitest.mjs"
        if not node or not entry.is_file():
            raise ValueError("Install Node and run npm ci in src/admin first")
        result.append((admin, [node, str(entry), "run", *web_files]))
    return result


def main(argv=None):
    try:
        selected = commands(sys.argv[1:] if argv is None else argv)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(ROOT / "src/backend"),
            str(ROOT / "src/data"),
            environment.get("PYTHONPATH", ""),
        ]
    )
    for directory, command in selected:
        result = subprocess.run(command, cwd=directory, env=environment, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

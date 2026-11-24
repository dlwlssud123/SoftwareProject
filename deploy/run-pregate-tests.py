"""Run every selected Python/Vitest/Flutter file without omitting runtimes."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def commands(files, root=ROOT):
    python_files, web_files, flutter_files = [], [], []
    root = root.resolve()
    admin = root / "src/admin"
    frontend = root / "src/frontend"
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
        elif path.is_relative_to(frontend / "test") and path.name.endswith(
            "_test.dart"
        ):
            flutter_files.append(str(path.relative_to(frontend)))
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
    if flutter_files:
        launcher = shutil.which("flutter")
        if not launcher:
            raise ValueError("Add the installed Flutter SDK bin directory to PATH")
        sdk = Path(launcher).resolve().parent.parent
        dart = (
            sdk / "bin/cache/dart-sdk/bin" / ("dart.exe" if os.name == "nt" else "dart")
        )
        snapshot = sdk / "bin/cache/flutter_tools.snapshot"
        if not dart.is_file() or not snapshot.is_file():
            raise ValueError(
                "Run flutter --version once to initialize the installed SDK"
            )
        # Invoke Dart directly so Windows batch launchers do not add a shell.
        result.append(
            (
                frontend,
                [
                    str(dart),
                    str(snapshot),
                    "--no-version-check",
                    "--suppress-analytics",
                    "test",
                    "--no-pub",
                    *flutter_files,
                ],
            )
        )
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

import importlib.util
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "pregate_runner", Path(__file__).with_name("run-pregate-tests.py")
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_mixed_selection_uses_both_runtimes_without_omitting_files(
    tmp_path, monkeypatch
):
    admin = tmp_path / "src/admin"
    test = admin / "tests/admin.test.tsx"
    entry = admin / "node_modules/vitest/vitest.mjs"
    python = tmp_path / "backend_test.py"
    test.parent.mkdir(parents=True)
    entry.parent.mkdir(parents=True)
    for path in (test, entry, python):
        path.write_text("", encoding="utf-8")
    monkeypatch.setattr(runner.shutil, "which", lambda _: "node-fixture")
    result = runner.commands([str(test.relative_to(tmp_path)), python.name], tmp_path)
    assert result[0] == (tmp_path, [sys.executable, "-m", "pytest", "-q", python.name])
    assert result[1] == (
        admin,
        ["node-fixture", str(entry), "run", str(test.relative_to(admin))],
    )


def test_empty_outside_missing_and_unsupported_tests_fail_closed(tmp_path):
    unsupported = tmp_path / "unknown.txt"
    unsupported.touch()
    for files in ([], ["../outside.py"], ["missing.py"], [unsupported.name]):
        with pytest.raises(ValueError):
            runner.commands(files, tmp_path)


def test_failure_is_returned_without_reporting_success(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "commands", lambda _: [(tmp_path, ["fixture"])])

    class Result:
        returncode = 7

    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: Result())
    assert runner.main(["test.py"]) == 7


def test_flutter_selection_runs_the_sdk_directly_and_keeps_other_runtimes(
    tmp_path, monkeypatch
):
    frontend = tmp_path / "src/frontend"
    test = frontend / "test/startup_test.dart"
    test.parent.mkdir(parents=True)
    test.touch()
    python = tmp_path / "test_api.py"
    python.touch()
    sdk = tmp_path / "flutter-sdk"
    launcher = sdk / "bin/flutter"
    dart = (
        sdk
        / "bin/cache/dart-sdk/bin"
        / ("dart.exe" if runner.os.name == "nt" else "dart")
    )
    snapshot = sdk / "bin/cache/flutter_tools.snapshot"
    dart.parent.mkdir(parents=True)
    for path in (launcher, dart, snapshot):
        path.touch()
    monkeypatch.setattr(runner.shutil, "which", lambda name: str(launcher))
    commands = runner.commands([str(test.relative_to(tmp_path)), python.name], tmp_path)
    assert len(commands) == 2
    assert commands[0][1][-1] == python.name
    assert commands[1] == (
        frontend,
        [
            str(dart),
            str(snapshot),
            "--no-version-check",
            "--suppress-analytics",
            "test",
            "--no-pub",
            str(test.relative_to(frontend)),
        ],
    )
    dart.unlink()
    with pytest.raises(ValueError, match="initialize"):
        runner.commands([str(test.relative_to(tmp_path))], tmp_path)
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="PATH"):
        runner.commands([str(test.relative_to(tmp_path))], tmp_path)

"""Exercise the public-key parser without modifying SSH authorization."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("authorize-key.sh")
TEST_KEY = b"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestOnly valueflow-actions"


def bash_executable():
    if os.name == "nt":
        candidate = (
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
            / "Git/bin/bash.exe"
        )
        if candidate.is_file():
            return str(candidate)
    return shutil.which("bash")


@pytest.mark.parametrize(
    ("content", "expected_exit"),
    [
        (TEST_KEY + b"\n", 0),
        (TEST_KEY + b"\r\n", 0),
        (b"not a public key\n", 2),
        (TEST_KEY + b"\n" + TEST_KEY + b"\n", 2),
    ],
)
def test_check_public_key_format(tmp_path, content, expected_exit):
    bash = bash_executable()
    if not bash:
        pytest.skip("Bash is required to check the deployment script")
    key_file = tmp_path / "test.pub"
    key_file.write_bytes(content)
    result = subprocess.run(
        [bash, str(SCRIPT), "--check", str(key_file)],
        check=False,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == expected_exit, result.stderr
    assert key_file.read_bytes() == content
    if expected_exit == 0:
        assert "format valid" in result.stdout
    else:
        assert "Expected one ed25519 public key line" in result.stderr

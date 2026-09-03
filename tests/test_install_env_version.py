"""Regression tests for VERSION updates performed by install.sh."""

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SCRIPT = PROJECT_ROOT / "install.sh"
UPDATED_VERSION = "9.8.7"


def _write_version_update_harness(tmp_path: Path) -> Path:
    """Create a shell harness that loads installer functions without running main."""
    installer_source = INSTALL_SCRIPT.read_text(encoding="utf-8")
    functions_source, marker, _ = installer_source.partition(
        "\n# Procesar argumentos\n"
    )
    assert marker, "No se encontró el bloque principal de install.sh"

    (tmp_path / "install.sh").write_text(
        f'CURRENT_VERSION="{UPDATED_VERSION}"\n', encoding="utf-8"
    )
    harness = tmp_path / "run-version-update.sh"
    harness.write_text(
        f"{functions_source}\n"
        'LOG_FILE="$1/install-test.log"\n'
        'loadCurrentVersionFromInstalledScript "$1" || exit $?\n'
        'updateEnvVersion "$1"\n',
        encoding="utf-8",
    )
    return harness


def _run_version_update(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    harness = _write_version_update_harness(tmp_path)
    shell_bin = shutil.which("dash") or "/bin/sh"
    return subprocess.run(  # noqa: S603
        [shell_bin, str(harness), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "contents",
    [
        "VERSION=1.0.0\nSQUID_HOST=127.0.0.1\n",
        "export VERSION = 1.0.0\n VERSION=0.9.0\nSQUID_HOST=127.0.0.1\n",
        "SQUID_HOST=127.0.0.1\n",
        "",
    ],
)
def test_update_env_version_normalizes_to_installed_current_version(tmp_path, contents):
    """The updater writes exactly one VERSION, including for an empty .env."""
    env_file = tmp_path / ".env"
    env_file.write_text(contents, encoding="utf-8")
    env_file.chmod(0o640)

    result = _run_version_update(tmp_path)

    assert result.returncode == 0, result.stderr
    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert lines.count(f"VERSION={UPDATED_VERSION}") == 1
    assert not any(
        line.startswith(("export VERSION", " VERSION", "VERSION =")) for line in lines
    )
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o640
    if "SQUID_HOST" in contents:
        assert "SQUID_HOST=127.0.0.1" in lines


def test_update_env_version_fails_when_env_file_is_missing(tmp_path):
    """A missing .env is an update failure instead of a false success."""
    result = _run_version_update(tmp_path)

    assert result.returncode != 0
    assert not (tmp_path / ".env").exists()

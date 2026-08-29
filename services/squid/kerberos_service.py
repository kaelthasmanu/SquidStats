"""Safe installation and validation of Squid's Kerberos authentication setup."""

from __future__ import annotations

import os
import pwd
import re
import shutil
import stat
import subprocess  # nosec B404
import tempfile
from dataclasses import dataclass
from pathlib import Path

from flask_babel import gettext as _
from loguru import logger

from config import Config
from utils.admin import SquidConfigManager

KEYTAB_MODE = 0o440
KEYTAB_USER = "proxy"
KEYTAB_GROUP = "proxy"
MAX_KEYTAB_SIZE = 16 * 1024 * 1024
DEFAULT_SQUID_PORT = "3128"

KERBEROS_CONFIG_START = "# SQUIDSTATS KERBEROS AUTH START"
KERBEROS_CONFIG_END = "# SQUIDSTATS KERBEROS AUTH END"
KERBEROS_AUTH_FILENAME = "50_auth.conf"


class KerberosConfigurationError(RuntimeError):
    """Expected error while preparing or validating the Kerberos setup."""


class SquidNotInstalledError(KerberosConfigurationError):
    """Raised when the local Squid executable is not installed."""


class KeytabRequiredError(KerberosConfigurationError):
    """Raised when a keytab upload was not supplied."""


@dataclass
class _FileSnapshot:
    path: Path
    exists: bool
    content: bytes = b""
    mode: int | None = None
    uid: int | None = None
    gid: int | None = None


def _squid_binary() -> str | None:
    """Find the local Squid executable, including common sbin locations."""
    binary = shutil.which("squid")
    if binary:
        return binary
    for candidate in ("/usr/sbin/squid", "/usr/local/sbin/squid"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def squid_is_installed() -> bool:
    """Return whether a local Squid executable is available."""
    return _squid_binary() is not None


def _docker_binary() -> str | None:
    """Return Docker's executable when it is installed on the host."""
    return shutil.which("docker")


def _is_squid_docker_container(name: str, ports: str) -> bool:
    """Identify a running Squid container by name or the standard proxy port."""
    if "squid" in name.casefold():
        return True
    return re.search(rf"(?<!\d){DEFAULT_SQUID_PORT}(?!\d)", ports) is not None


def _find_docker_squid_container() -> dict[str, str] | None:
    """Return the first running Docker container that appears to run Squid."""
    docker = _docker_binary()
    if docker is None:
        return None

    success, output = _run(
        [docker, "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Ports}}"]
    )
    if not success:
        logger.debug("Unable to inspect Docker containers: {}", output)
        return None

    for line in output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        container_id, name, ports = (part.strip() for part in parts)
        if _is_squid_docker_container(name, ports):
            return {"id": container_id, "name": name, "ports": ports}
    return None


def get_squid_runtime() -> dict:
    """Detect local Squid first, then a running Docker-based Squid if needed."""
    binary = _squid_binary()
    if binary:
        return {
            "kind": "local",
            "message": _("KERBEROS_STATUS_SQUID_INSTALLED"),
            "local_squid": True,
            "docker_container": None,
        }

    # Docker must only be queried when the local executable is unavailable.
    container = _find_docker_squid_container()
    if container:
        return {
            "kind": "docker",
            "message": _(
                "KERBEROS_STATUS_DOCKER_SQUID_FOUND",
                name=container["name"],
            ),
            "local_squid": False,
            "docker_container": container,
        }

    return {
        "kind": "none",
        "message": _("KERBEROS_ERROR_SQUID_NOT_FOUND"),
        "local_squid": False,
        "docker_container": None,
    }


def _require_squid() -> str:
    binary = _squid_binary()
    if binary is None:
        raise SquidNotInstalledError(_("KERBEROS_ERROR_SQUID_NOT_INSTALLED"))
    return binary


def _keytab_path() -> Path:
    return Path(Config.SQUID_KERBEROS_KEYTAB_PATH).expanduser()


def _get_proxy_ids() -> tuple[int, int]:
    try:
        user = pwd.getpwnam(KEYTAB_USER)
    except KeyError as exc:
        raise KerberosConfigurationError(
            _("KERBEROS_ERROR_PROXY_USER_NOT_FOUND")
        ) from exc

    try:
        import grp

        group_id = grp.getgrnam(KEYTAB_GROUP).gr_gid
    except KeyError as exc:
        raise KerberosConfigurationError(
            _("KERBEROS_ERROR_PROXY_GROUP_NOT_FOUND")
        ) from exc
    return user.pw_uid, group_id


def _snapshot(path: Path) -> _FileSnapshot:
    if not path.exists():
        return _FileSnapshot(path=path, exists=False)
    info = path.stat()
    return _FileSnapshot(
        path=path,
        exists=True,
        content=path.read_bytes(),
        mode=stat.S_IMODE(info.st_mode),
        uid=info.st_uid,
        gid=info.st_gid,
    )


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace a file atomically in its own directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, delete=False, suffix=".squidstats.tmp"
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = temporary.name
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        raise


def _restore(snapshot: _FileSnapshot) -> None:
    if not snapshot.exists:
        try:
            snapshot.path.unlink()
        except FileNotFoundError:
            pass
        return

    _atomic_write_bytes(snapshot.path, snapshot.content)
    if snapshot.mode is not None:
        os.chmod(snapshot.path, snapshot.mode)
    if snapshot.uid is not None and snapshot.gid is not None:
        try:
            os.chown(snapshot.path, snapshot.uid, snapshot.gid)
        except PermissionError:
            logger.warning("Unable to restore owner for %s", snapshot.path)


def _save_uploaded_keytab(upload, destination: Path) -> None:
    filename = (getattr(upload, "filename", "") or "").strip()
    if not filename.lower().endswith(".keytab"):
        raise KerberosConfigurationError(
            _("KERBEROS_ERROR_INVALID_KEYTAB_EXTENSION")
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    total = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, delete=False, suffix=".keytab.tmp"
        ) as temporary:
            temporary_path = temporary.name
            while True:
                chunk = upload.stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_KEYTAB_SIZE:
                    raise KerberosConfigurationError(
                        _("KERBEROS_ERROR_KEYTAB_TOO_LARGE")
                    )
                temporary.write(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())

        if total == 0:
            raise KerberosConfigurationError(_("KERBEROS_ERROR_EMPTY_KEYTAB"))

        uid, gid = _get_proxy_ids()
        os.chmod(temporary_path, KEYTAB_MODE)
        os.chown(temporary_path, uid, gid)
        os.replace(temporary_path, destination)
        temporary_path = None

        # Set these again after replace so the postcondition is explicit.
        os.chmod(destination, KEYTAB_MODE)
        os.chown(destination, uid, gid)
    except PermissionError as exc:
        raise KerberosConfigurationError(
            _("KERBEROS_ERROR_KEYTAB_INSTALL_PERMISSION_DENIED")
        ) from exc
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def _keytab_permissions(path: Path) -> dict:
    if not path.is_file():
        return {
            "exists": False,
            "mode": None,
            "owner": None,
            "group": None,
            "permissions_ok": False,
        }

    info = path.stat()
    try:
        owner = pwd.getpwuid(info.st_uid).pw_name
    except KeyError:
        owner = str(info.st_uid)
    try:
        import grp

        group = grp.getgrgid(info.st_gid).gr_name
    except KeyError:
        group = str(info.st_gid)
    mode = stat.S_IMODE(info.st_mode)
    return {
        "exists": True,
        "mode": f"{mode:04o}",
        "owner": owner,
        "group": group,
        "permissions_ok": (
            mode == KEYTAB_MODE and owner == KEYTAB_USER and group == KEYTAB_GROUP
        ),
    }


def _run(command: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(  # nosec B603  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return False, _("KERBEROS_ERROR_COMMAND_NOT_FOUND", command=command[0])
    except subprocess.TimeoutExpired:
        return False, _(
            "KERBEROS_ERROR_COMMAND_TIMEOUT", command=command[0]
        )
    except OSError as exc:
        return False, str(exc)

    output = "\n".join(
        value.strip()
        for value in (result.stdout or "", result.stderr or "")
        if value and value.strip()
    )
    return result.returncode == 0, output


def verify_keytab_readable(path: Path | str) -> tuple[bool, str]:
    """Run ``klist -k`` as ``proxy`` to verify real read access and validity."""
    keytab = Path(path)
    klist = shutil.which("klist")
    if not klist:
        return False, _("KERBEROS_ERROR_KLIST_NOT_INSTALLED")

    sudo = shutil.which("sudo")
    if sudo:
        command = [sudo, "-u", KEYTAB_USER, klist, "-k", str(keytab)]
    else:
        runuser = shutil.which("runuser")
        if runuser:
            command = [runuser, "-u", KEYTAB_USER, "--", klist, "-k", str(keytab)]
        else:
            return (
                False,
                _("KERBEROS_ERROR_PRIVILEGE_COMMAND_NOT_FOUND"),
            )
    return _run(command)


def _remove_managed_block(content: str) -> str:
    """Remove only complete blocks previously managed by this service."""
    start = content.find(KERBEROS_CONFIG_START)
    if start < 0:
        return content

    end = content.find(KERBEROS_CONFIG_END, start + len(KERBEROS_CONFIG_START))
    if end < 0:
        # Do not discard the remainder of a potentially hand-edited file if a
        # marker was left incomplete.
        return content

    end += len(KERBEROS_CONFIG_END)
    cleaned = content[:start] + content[end:]
    return _remove_managed_block(cleaned)


def _kerberos_block() -> str:
    return (
        f"{KERBEROS_CONFIG_START}\n"
        "# Kerberos authentication managed by SquidStats\n"
        "auth_param negotiate program "
        f"{Config.SQUID_KERBEROS_HELPER_PATH} -k {Config.SQUID_KERBEROS_KEYTAB_PATH} "
        f"-s {Config.SQUID_KERBEROS_SERVICE_PRINCIPAL}\n"
        "auth_param negotiate children 10 startup=5 idle=3\n"
        "auth_param negotiate keep_alive on\n"
        "acl auth proxy_auth REQUIRED\n"
        "http_access allow auth\n"
        f"{KERBEROS_CONFIG_END}\n"
    )


def _add_block(content: str, *, before_http_deny: bool = True) -> str:
    clean = _remove_managed_block(content)
    block = _kerberos_block()
    if not clean:
        return block

    if before_http_deny:
        lines = clean.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if line.strip().lower().startswith("http_access deny all"):
                prefix = "" if index == 0 or lines[index - 1].endswith("\n\n") else "\n"
                lines.insert(index, prefix + block)
                return "".join(lines)

    return clean.rstrip() + "\n\n" + block


def _has_active_include(main_content: str, auth_path: Path) -> bool:
    normalized_auth = str(auth_path.resolve())
    for raw_line in main_content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith("include "):
            continue
        included = line.split(None, 1)[1].strip()
        if "*" in included:
            return True
        try:
            if str(Path(included).expanduser().resolve()) == normalized_auth:
                return True
        except OSError:
            continue
    return False


def _add_modular_include(main_content: str, auth_path: Path) -> str:
    if _has_active_include(main_content, auth_path):
        return main_content
    include_line = f"include {auth_path}\n"
    lines = main_content.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip().startswith("include "):
            lines.insert(index, include_line)
            return "".join(lines)
    return main_content.rstrip() + "\n\n" + include_line


def _validate_squid_configuration(squid_binary: str) -> tuple[bool, str]:
    return _run([squid_binary, "-k", "parse"])


def get_status() -> dict:
    """Return non-sensitive status information for the Kerberos tab."""
    runtime = get_squid_runtime()
    keytab = _keytab_path()
    permissions = _keytab_permissions(keytab)
    config_path = Path(Config.SQUID_CONFIG_PATH).expanduser()
    configured = False
    modular = False
    try:
        main_content = config_path.read_text(encoding="utf-8")
        modular = "include" in main_content.lower() and "squid.d" in main_content
        configured = KERBEROS_CONFIG_START in main_content
        if modular and not configured:
            auth_path = Path(Config.ACL_FILES_DIR).expanduser() / KERBEROS_AUTH_FILENAME
            if auth_path.is_file():
                configured = KERBEROS_CONFIG_START in auth_path.read_text(
                    encoding="utf-8"
                )
    except (OSError, UnicodeError):
        pass

    return {
        # ``squid_installed`` remains local-only because applying the current
        # configuration workflow writes host files and invokes local commands.
        "squid_installed": runtime["local_squid"],
        "squid_available": runtime["kind"] != "none",
        "squid_runtime": runtime["kind"],
        "squid_status_message": runtime["message"],
        "docker_container": runtime["docker_container"],
        "keytab_path": str(keytab),
        "keytab": permissions,
        "configured": configured,
        "config_path": str(config_path),
        "modular": modular,
    }


def configure(upload, config_manager: SquidConfigManager | None = None) -> dict:
    """Install a keytab and apply Kerberos configuration transactionally."""
    squid_binary = _require_squid()
    if upload is None or not (getattr(upload, "filename", "") or "").strip():
        raise KeytabRequiredError(
            _("KERBEROS_ERROR_KEYTAB_REQUIRED")
        )

    keytab = _keytab_path()
    manager = config_manager or SquidConfigManager()
    if not manager.is_valid:
        details = (
            "; ".join(manager.errors)
            if manager.errors
            else _("KERBEROS_ERROR_SQUID_CONFIG_INACCESSIBLE")
        )
        raise KerberosConfigurationError(
            _(
                "KERBEROS_ERROR_SQUID_CONFIG_ACCESS",
                details=details,
            )
        )

    main_path = Path(manager.config_path)
    main_snapshot = _snapshot(main_path)
    keytab_snapshot = _snapshot(keytab)
    auth_path: Path | None = None
    auth_snapshot: _FileSnapshot | None = None

    try:
        _save_uploaded_keytab(upload, keytab)
        permissions = _keytab_permissions(keytab)
        if not permissions["permissions_ok"]:
            raise KerberosConfigurationError(
                _("KERBEROS_ERROR_KEYTAB_PERMISSIONS")
            )

        readable, read_output = verify_keytab_readable(keytab)
        if not readable:
            raise KerberosConfigurationError(
                _(
                    "KERBEROS_ERROR_KEYTAB_NOT_READABLE",
                    details=read_output,
                ).strip()
            )

        if manager.is_modular:
            auth_path = Path(manager.config_dir) / KERBEROS_AUTH_FILENAME
            auth_snapshot = _snapshot(auth_path)
            existing_auth = (
                auth_snapshot.content.decode("utf-8") if auth_snapshot.exists else ""
            )
            new_auth = _add_block(existing_auth, before_http_deny=False)
            if not manager.save_modular_config(KERBEROS_AUTH_FILENAME, new_auth):
                raise KerberosConfigurationError(
                    _("KERBEROS_ERROR_SAVE_MODULE_CONFIG")
                )

            new_main = _add_modular_include(manager.config_content, auth_path)
            if new_main != manager.config_content and not manager.save_config(new_main):
                raise KerberosConfigurationError(
                    _(
                        "KERBEROS_ERROR_ENABLE_MODULE_CONFIG"
                    )
                )
        else:
            existing_main = main_snapshot.content.decode("utf-8")
            new_main = _add_block(existing_main)
            if not manager.save_config(new_main):
                raise KerberosConfigurationError(
                    _("KERBEROS_ERROR_SAVE_SQUID_CONFIG")
                )

        valid, parse_output = _validate_squid_configuration(squid_binary)
        if not valid:
            raise KerberosConfigurationError(
                _(
                    "KERBEROS_ERROR_SQUID_CONFIG_INVALID",
                    details=parse_output,
                ).strip()
            )

        return {
            "status": "success",
            "message": _("KERBEROS_SUCCESS_CONFIGURED"),
            "keytab_path": str(keytab),
            "owner": "proxy:proxy",
            "mode": "0440",
            "proxy_readable": True,
            "config_valid": True,
            "squid_installed": True,
        }
    except Exception:
        logger.exception("Failed to apply Squid Kerberos configuration")
        try:
            _restore(keytab_snapshot)
            if auth_snapshot is not None:
                _restore(auth_snapshot)
            _restore(main_snapshot)
        except Exception:
            logger.exception("Failed to restore the previous Kerberos configuration")
        raise

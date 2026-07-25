"""Terminate tracked network states belonging to a client IP.

This is intentionally a host-level capability. Squid does not expose a
portable API for closing only one client's active sockets, so unsupported
platforms must report that fact instead of claiming the reset succeeded.
"""

import ipaddress
import platform
import shutil
import subprocess  # nosec B404

from loguru import logger


def _validate_ip(client_ip: str) -> str:
    """Return a normalized IP address or raise ValueError."""
    value = str(client_ip or "").strip()
    if not value:
        raise ValueError("Se requiere una dirección IP")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise ValueError("La dirección IP no es válida") from exc


def _run_reset(command: list[str], backend: str) -> tuple[bool, str, str | None]:
    try:
        result = subprocess.run(  # nosec B603  # noqa: S603
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, "El reseteo de conexiones agotó el tiempo de espera", None
    except OSError as exc:
        logger.warning("No se pudo ejecutar %s: %s", backend, exc)
        return False, f"No se pudo ejecutar {backend}", str(exc)

    if result.returncode == 0:
        return True, f"Conexiones activas de {command[-1]} reseteadas mediante {backend}", None

    details = (result.stderr or result.stdout).strip() or None
    logger.warning("%s falló con estado %s: %s", backend, result.returncode, details)
    if details and any(
        marker in details.lower()
        for marker in ("permission denied", "operation not permitted", "must be root")
    ):
        return False, "Se requieren privilegios del sistema para resetear conexiones", details
    return False, f"{backend} no pudo resetear las conexiones", details


def reset_client_connections(client_ip: str) -> tuple[bool, str, str | None]:
    """Reset tracked states for *client_ip* using the host's native firewall.

    Linux uses conntrack and macOS/BSD uses pfctl. Both require the SquidStats
    process to have the corresponding system privileges (normally root or a
    narrowly scoped sudo policy).
    """
    try:
        normalized_ip = _validate_ip(client_ip)
    except ValueError as exc:
        return False, str(exc), None

    system = platform.system().lower()
    if system == "linux":
        binary = shutil.which("conntrack")
        if not binary:
            return (
                False,
                "No se encontró conntrack. Instálalo en el host para resetear conexiones.",
                None,
            )
        return _run_reset([binary, "-D", "-s", normalized_ip], "conntrack")

    if system in {"darwin", "freebsd", "openbsd", "netbsd"}:
        binary = shutil.which("pfctl")
        if not binary:
            return False, "No se encontró pfctl para resetear conexiones", None
        return _run_reset([binary, "-k", normalized_ip], "pfctl")

    return (
        False,
        f"El reseteo de conexiones no está soportado en {platform.system() or 'este sistema'}",
        None,
    )

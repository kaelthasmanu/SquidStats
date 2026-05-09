import shutil
import subprocess  # nosec B404

from loguru import logger


def _get_bin(name: str) -> str | None:
    """Return the absolute path of *name* in PATH, or None if not found."""
    return shutil.which(name)


def _docker_reconfigure() -> tuple[bool, str]:
    docker_bin = _get_bin("docker")
    if docker_bin is None:
        return False, "Docker no encontrado"
    try:
        subprocess.run(  # nosec B603  # noqa: S603
            [docker_bin, "exec", "squid_proxy", "squid", "-k", "reconfigure"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (
            True,
            "Squid reconfigure a través de docker exec squid_proxy squid -k reconfigure",
        )
    except subprocess.CalledProcessError as e:
        logger.warning("docker reconfigure falló con estado %s: %s", e.returncode, e)
        return False, str(e)
    except FileNotFoundError as e:
        logger.warning("Docker no encontrado: %s", e)
        return False, str(e)
    except Exception as e:
        logger.exception("Error ejecutando reconfigure en Docker: %s", e)
        return False, str(e)


def _local_reconfigure() -> tuple[bool, str]:
    squid_bin = _get_bin("squid")
    if squid_bin is None:
        return False, "Squid no encontrado"
    try:
        subprocess.run(  # nosec B603  # noqa: S603
            [squid_bin, "-k", "reconfigure"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return True, "Squid reconfigure a través de squid -k reconfigure (local)"
    except subprocess.CalledProcessError as e:
        logger.warning(
            "Local squid reconfigure falló con estado %s: %s", e.returncode, e
        )
        return False, str(e)
    except FileNotFoundError as e:
        logger.warning("Squid no encontrado: %s", e)
        return False, str(e)
    except Exception as e:
        logger.exception("Error ejecutando reconfigure local: %s", e)
        return False, str(e)


def restart_squid() -> tuple[bool, str, str]:
    systemctl_bin = _get_bin("systemctl")
    if systemctl_bin:
        try:
            subprocess.run([systemctl_bin, "restart", "squid"], check=True)  # nosec B603  # noqa: S603
            return True, "Squid restarted successfully", None
        except subprocess.CalledProcessError as e:
            logger.warning(
                "systemctl restart squid falló con estado %s: %s", e.returncode, e
            )
        except Exception as e:
            logger.warning("Error systemctl restart squid: %s", e)

    # Fallback docker si existe, y luego local
    success, msg = _docker_reconfigure()
    if success:
        return True, msg, None

    success, msg = _local_reconfigure()
    if success:
        return True, msg, None

    return False, "Internal server error", None


def reload_squid() -> tuple[bool, str, str]:
    systemctl_bin = _get_bin("systemctl")
    if systemctl_bin:
        try:
            subprocess.run([systemctl_bin, "reload", "squid"], check=True)  # nosec B603  # noqa: S603
            return True, "Configuration reloaded successfully", None
        except subprocess.CalledProcessError as e:
            logger.warning(
                "systemctl reload squid falló con estado %s: %s", e.returncode, e
            )
        except Exception as e:
            logger.warning("Error systemctl reload squid: %s", e)

    # Fallback docker si existe, y luego local
    success, msg = _docker_reconfigure()
    if success:
        return True, msg, None

    success, msg = _local_reconfigure()
    if success:
        return True, msg, None

    return False, "Internal server error", None

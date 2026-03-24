import subprocess

from loguru import logger


def _docker_reconfigure() -> tuple[bool, str]:
    try:
        subprocess.run(
            ["docker", "exec", "squid_proxy", "squid", "-k", "reconfigure"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return True, "Squid reconfigure a través de docker exec squid_proxy squid -k reconfigure"
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
    try:
        subprocess.run(
            ["squid", "-k", "reconfigure"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return True, "Squid reconfigure a través de squid -k reconfigure (local)"
    except subprocess.CalledProcessError as e:
        logger.warning("Local squid reconfigure falló con estado %s: %s", e.returncode, e)
        return False, str(e)
    except FileNotFoundError as e:
        logger.warning("Squid no encontrado: %s", e)
        return False, str(e)
    except Exception as e:
        logger.exception("Error ejecutando reconfigure local: %s", e)
        return False, str(e)


def restart_squid() -> tuple[bool, str, str]:
    try:
        subprocess.run(["systemctl", "restart", "squid"], check=True)
        return True, "Squid restarted successfully", None
    except subprocess.CalledProcessError as e:
        logger.warning("systemctl restart squid falló con estado %s: %s", e.returncode, e)
    except FileNotFoundError as e:
        logger.warning("systemctl no encontrado: %s", e)
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
    try:
        subprocess.run(["systemctl", "reload", "squid"], check=True)
        return True, "Configuration reloaded successfully", None
    except subprocess.CalledProcessError as e:
        logger.warning("systemctl reload squid falló con estado %s: %s", e.returncode, e)
    except FileNotFoundError as e:
        logger.warning("systemctl no encontrado: %s", e)
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

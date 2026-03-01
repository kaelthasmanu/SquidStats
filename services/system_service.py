import subprocess

from loguru import logger


def restart_squid() -> tuple[bool, str, str]:
    try:
        subprocess.run(["systemctl", "restart", "squid"], check=True)
        return True, "Squid restarted successfully", None
    except Exception as e:
        logger.exception("Error restarting squid")
        # Do not expose raw exception details to callers; log only.
        return False, "Internal server error", None


def reload_squid() -> tuple[bool, str, str]:
    try:
        subprocess.run(["systemctl", "reload", "squid"], check=True)
        return True, "Configuration reloaded successfully", None
    except Exception as e:
        logger.exception("Error reloading squid configuration")
        # Do not expose raw exception details to callers; log only.
        return False, "Internal server error", None

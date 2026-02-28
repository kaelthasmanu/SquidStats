from loguru import logger
import subprocess


def restart_squid() -> tuple[bool, str, str]:
    try:
        subprocess.run(["systemctl", "restart", "squid"], check=True)
        return True, "Squid restarted successfully", None
    except Exception as e:
        logger.exception("Error restarting squid")
        return False, "Internal server error", str(e)


def reload_squid() -> tuple[bool, str, str]:
    try:
        subprocess.run(["systemctl", "reload", "squid"], check=True)
        return True, "Configuration reloaded successfully", None
    except Exception as e:
        logger.exception("Error reloading squid configuration")
        return False, "Internal server error", str(e)

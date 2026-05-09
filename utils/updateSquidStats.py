import os
import shutil
import subprocess

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


def updateSquidStats():
    try:
        proxy_url = os.getenv("HTTP_PROXY", "")
        env = os.environ.copy()
        if proxy_url:
            env["http_proxy"] = proxy_url
            env["https_proxy"] = proxy_url

        proxies = None
        if proxy_url:
            proxies = {"http": proxy_url, "https": proxy_url}
        try:
            response = requests.get(
                "https://github.com/kaelthasmanu/SquidStats/releases/download/2.3.1/install.sh",
                proxies=proxies,
                timeout=30,
            )
            response.raise_for_status()
            sh_bin = "/bin/sh" if os.path.exists("/bin/sh") else shutil.which("sh")
            if not sh_bin:
                logger.error("sh no encontrado en el sistema")
                return False
            args = [sh_bin, "-s", "--update"]
            subprocess.run(args, input=response.content, env=env, check=True)  # noqa: S603
            return True
        except Exception:
            logger.exception("Error descargando el script de actualización")
            return False

    except Exception:
        logger.exception("Error crítico en updateSquidStats")
        return False

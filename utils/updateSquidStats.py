import os
import shutil
import subprocess
import tempfile

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
            with tempfile.NamedTemporaryFile(
                delete=False, mode="w+b", suffix=".sh"
            ) as tmp_script:
                tmp_script_path = tmp_script.name
                response = requests.get(
                    "https://github.com/kaelthasmanu/SquidStats/releases/download/2.3.1/install.sh",
                    proxies=proxies,
                    timeout=30,
                )
                response.raise_for_status()
                tmp_script.write(response.content)
            subprocess.run([shutil.which("chmod") or "chmod", "+x", tmp_script_path])  # noqa: S603
            subprocess.run([shutil.which("bash") or "bash", tmp_script_path, "--update"], env=env)  # noqa: S603
            os.unlink(tmp_script_path)
            return True
        except Exception:
            logger.exception("Error descargando el script de actualización")
            if "tmp_script_path" in locals() and os.path.exists(tmp_script_path):
                os.unlink(tmp_script_path)
            return False

    except Exception:
        logger.exception("Error crítico en updateSquidStats")
        return False

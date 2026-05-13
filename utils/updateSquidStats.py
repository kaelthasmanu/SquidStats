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
        https_proxy_url = os.getenv("HTTPS_PROXY", proxy_url)
        env = os.environ.copy()
        if proxy_url:
            env["http_proxy"] = proxy_url
        if https_proxy_url:
            env["https_proxy"] = https_proxy_url

        proxies = None
        if proxy_url or https_proxy_url:
            proxies = {
                "http": proxy_url or None,
                "https": https_proxy_url or None,
            }
        try:
            # Fetch the latest release tag from GitHub API to always use the current version
            api_response = requests.get(
                "https://api.github.com/repos/kaelthasmanu/SquidStats/releases/latest",
                proxies=proxies,
                timeout=30,
            )
            api_response.raise_for_status()
            latest_tag = api_response.json().get("tag_name", "")
            if not latest_tag:
                logger.error("No se pudo obtener la última versión desde GitHub API")
                return False

            script_url = f"https://github.com/kaelthasmanu/SquidStats/releases/download/{latest_tag}/install.sh"
            response = requests.get(
                script_url,
                proxies=proxies,
                timeout=30,
            )
            response.raise_for_status()
            sh_bin = "/bin/sh" if os.path.exists("/bin/sh") else shutil.which("sh")
            if not sh_bin:
                logger.error("sh no encontrado en el sistema")
                return False

            with tempfile.NamedTemporaryFile(delete=False, suffix=".sh") as tmp_script:
                tmp_script.write(response.content)
                tmp_script_path = tmp_script.name

            os.chmod(tmp_script_path, 0o700)
            args = [sh_bin, tmp_script_path, "--update"]
            try:
                # The external update script is downloaded from the official GitHub
                # release feed, then written to a temporary file and executed.
                # This is intentionally executing remote installer content.
                subprocess.run(args, env=env, check=True, timeout=600)  # noqa: S603
            finally:
                try:
                    os.remove(tmp_script_path)
                except OSError:
                    pass
            return True
        except Exception:
            logger.exception("Error descargando el script de actualización")
            return False

    except Exception:
        logger.exception("Error crítico en updateSquidStats")
        return False

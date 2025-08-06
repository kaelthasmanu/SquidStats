import os
import subprocess
import tempfile

import requests
from dotenv import load_dotenv

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
                    "https://github.com/kaelthasmanu/SquidStats/releases/download/1.0/install.sh",
                    proxies=proxies,
                    timeout=30,
                )
                response.raise_for_status()
                tmp_script.write(response.content)
            subprocess.run(["chmod", "+x", tmp_script_path])
            subprocess.run(["bash", tmp_script_path, "--update"], env=env)
            os.unlink(tmp_script_path)
            return True
        except Exception as e:
            print(f"Error descargando el script de actualizacion: {str(e)}", "error")
            if "tmp_script_path" in locals() and os.path.exists(tmp_script_path):
                os.unlink(tmp_script_path)
            return False

    except Exception as e:
        print(f"Error crítico: {str(e)}", "error")
        return False

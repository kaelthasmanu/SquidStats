import os
import subprocess


def updateSquidStats():
    try:
        proxy_url = os.getenv("HTTP_PROXY", "")
        env = os.environ.copy()
        if proxy_url:
            env["http_proxy"] = proxy_url
            env["https_proxy"] = proxy_url

        script_install = subprocess.run(
            [
                "wget",
                "-O",
                "/tmp/install.sh",
                "https://github.com/kaelthasmanu/SquidStats/releases/download/0.2/install.sh",
            ]
            + (["-e", f"http_proxy={proxy_url}"] if proxy_url else []),
            capture_output=True,
            text=True,
            env=env,
        )

        if script_install.returncode != 0:
            print("Error descargando el script de actualizacion", "error")
            return False

        subprocess.run(["chmod", "+x", "/tmp/install.sh"])
        subprocess.run(["bash", "/tmp/install.sh", "--update"], env=env)
        return True

    except Exception as e:
        print(f"Error crítico: {str(e)}", "error")
        return False

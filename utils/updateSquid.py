import json
import os
import platform
import subprocess
import tempfile

from dotenv import load_dotenv
from loguru import logger

load_dotenv()


def update_squid():
    try:
        pre_check = subprocess.run(["squid", "-v"], capture_output=True, text=True)
        squid_instalado = pre_check.returncode == 0
    except FileNotFoundError:
        squid_instalado = False
        try:
            logger.info(
                "El binario de Squid no se encontró en el sistema (aún no instalado)"
            )
        except Exception:
            pass

    if squid_instalado:
        try:
            logger.info(f"Squid ya está instalado: {pre_check.stdout.strip()}")
        except Exception:
            pass
    else:
        try:
            logger.info("Squid no está instalado o no se detectó instalación previa")
        except Exception:
            pass
    try:
        os_info = platform.freedesktop_os_release()
        os_id = os_info.get("ID", "").lower()
        codename = os_info.get(
            "VERSION_CODENAME", os_info.get("UBUNTU_CODENAME", "")
        ).lower()

        if os_id not in ["ubuntu", "debian"] or not codename:
            print("Sistema operativo no compatible", "error")
            return False

        proxy_url = os.getenv("HTTP_PROXY", "")
        env = os.environ.copy()
        if proxy_url:
            env["http_proxy"] = proxy_url
            env["https_proxy"] = proxy_url

        version_info = subprocess.run(
            ["wget", "-qO-", "https://api.github.com/repos/cuza/squid/releases/latest"],
            capture_output=True,
            text=True,
            env=env,
        )
        if version_info.returncode != 0:
            logger.error("Error obteniendo información de versión")
            return False

        try:
            latest_version = json.loads(version_info.stdout)["tag_name"]
        except (json.JSONDecodeError, KeyError):
            logger.error("Error procesando versión")
            return False

        package_name = f"squid_{latest_version}-{os_id}-{codename}_amd64.deb"
        download_url = f"https://github.com/cuza/squid/releases/download/{latest_version}/{package_name}"

        check_package = subprocess.run(
            ["wget", "--spider", download_url], capture_output=True, text=True, env=env
        )
        if check_package.returncode != 0:
            logger.error(
                f"Paquete no disponible para {os_id.capitalize()} {codename.capitalize()}"
            )
            return False

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=f"_{package_name}"
        ) as tmp_pkg:
            package_path = tmp_pkg.name
            download = subprocess.run(
                ["wget", download_url, "-O", package_path],
                capture_output=True,
                text=True,
                env=env,
            )
        if download.returncode != 0:
            logger.error("Error descargando el paquete")
            return False

        apt_env = env.copy()
        if proxy_url:
            apt_conf = "/etc/apt/apt.conf.d/95proxies"
            with open(apt_conf, "w") as f:
                f.write(f'Acquire::http::Proxy "{proxy_url}";\n')
                f.write(f'Acquire::https::Proxy "{proxy_url}";\n')

        subprocess.run(["apt", "update"], env=apt_env)

        install = subprocess.run(["dpkg", "-i", "--force-overwrite", package_path])
        if install.returncode != 0:
            logger.error("Error instalando el paquete")
            subprocess.run(["apt", "install", "-f", "-y"], env=apt_env)

        subprocess.run(["cp", f"{os.getcwd()}/./utils/squid", "/etc/init.d/"])
        subprocess.run(["chmod", "+x", "/etc/init.d/squid"])
        subprocess.run(["systemctl", "daemon-reload"])

        os.unlink(package_path)
        squid_check = subprocess.run(["squid", "-v"], capture_output=True, text=True)

        if squid_check.returncode != 0:
            logger.error("Error en instalación final")
            return False

        try:
            logger.info(f"Actualización a {latest_version} completada exitosamente")
        except Exception:
            pass
        return True
    except Exception:
        logger.exception("Error crítico durante la actualización de Squid")
        return False

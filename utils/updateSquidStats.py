import os
import re
import shutil
import subprocess
import tempfile
import time

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


_DEB_INSTALL_PATHS = {"/opt/SquidStats/app", "/usr/share/squidstats"}


def is_deb_installation() -> bool:
    """Return True when the app is running from a .deb-managed installation path."""
    install_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return install_dir in _DEB_INSTALL_PATHS


def _get_git_binary():
    git_bin = shutil.which("git")
    if not git_bin:
        logger.error("git executable not found on PATH")
    return git_bin


def _run_git_command(args, cwd, env, capture_output=True, timeout=120):
    git_bin = _get_git_binary()
    if not git_bin:
        return subprocess.CompletedProcess(
            ["git", *args], 1, "", "git executable not found"
        )

    return subprocess.run(  # noqa: S603
        [git_bin, *args],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=True,
        timeout=timeout,
    )


def _repo_has_head(install_dir, env):
    result = _run_git_command(["rev-parse", "--verify", "HEAD"], install_dir, env)
    return result.returncode == 0


def _detect_remote_branch(install_dir, env):
    for branch in ("main", "master"):
        result = _run_git_command(
            ["ls-remote", "--heads", "origin", branch], install_dir, env
        )
        if result.returncode == 0 and result.stdout.strip():
            return branch
    return None


def _prepare_deb_git_repo(install_dir, env):
    git_dir = os.path.join(install_dir, ".git")
    repo_initialized = False
    if not os.path.isdir(git_dir):
        logger.info(
            "Initializing git repository in deb-installed path: %s", install_dir
        )
        result = _run_git_command(["init"], install_dir, env)
        if result.returncode != 0:
            logger.error(
                "Failed to initialize git repository: %s", result.stderr.strip()
            )
            return False
        repo_initialized = True

    result = _run_git_command(["remote", "get-url", "origin"], install_dir, env)
    origin_url = result.stdout.strip() if result.returncode == 0 else None
    if origin_url != "https://github.com/kaelthasmanu/SquidStats.git":
        if origin_url:
            logger.info(
                "Updating git origin remote URL from %s to %s",
                origin_url,
                "https://github.com/kaelthasmanu/SquidStats.git",
            )
            result = _run_git_command(
                [
                    "remote",
                    "set-url",
                    "origin",
                    "https://github.com/kaelthasmanu/SquidStats.git",
                ],
                install_dir,
                env,
            )
        else:
            logger.info(
                "Adding git origin remote: %s",
                "https://github.com/kaelthasmanu/SquidStats.git",
            )
            result = _run_git_command(
                [
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/kaelthasmanu/SquidStats.git",
                ],
                install_dir,
                env,
            )
        if result.returncode != 0:
            logger.error(
                "Failed to configure git origin remote: %s", result.stderr.strip()
            )
            return False

    result = _run_git_command(["fetch", "--tags", "origin"], install_dir, env)
    if result.returncode != 0:
        logger.error("Failed to fetch from origin: %s", result.stderr.strip())
        return False

    branch = _detect_remote_branch(install_dir, env)
    if not branch:
        logger.error("No supported remote branch found on origin")
        return False

    if repo_initialized or not _repo_has_head(install_dir, env):
        logger.info("Checking out branch %s from origin", branch)
        result = _run_git_command(
            ["checkout", "-B", branch, f"origin/{branch}"], install_dir, env
        )
        if result.returncode != 0:
            logger.error(
                "Failed to checkout branch %s from origin: %s",
                branch,
                result.stderr.strip(),
            )
            return False

    return True


def _update_deb_installation(install_dir, env):
    if not _prepare_deb_git_repo(install_dir, env):
        return False

    branch = _detect_remote_branch(install_dir, env)
    if not branch:
        return False

    result = _run_git_command(["pull", "--ff-only", "origin", branch], install_dir, env)
    if result.returncode == 0:
        logger.info("Git pull succeeded on deb installation")
        return True

    status = _run_git_command(["status", "--porcelain"], install_dir, env)
    if status.returncode == 0 and status.stdout.strip():
        logger.error(
            "Git pull failed because the working tree has modified files:\n%s",
            status.stdout.strip(),
        )
    else:
        logger.error(
            "Git pull failed: %s",
            result.stderr.strip() or result.stdout.strip(),
        )
    return False


def updateSquidStats():
    logger.info("Starting SquidStats web update process")

    install_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = os.environ.copy()
    proxy_url = os.getenv("HTTP_PROXY", "")
    https_proxy_url = os.getenv("HTTPS_PROXY", proxy_url)
    if proxy_url:
        logger.debug("HTTP proxy configured")
        env["http_proxy"] = proxy_url
    if https_proxy_url:
        logger.debug("HTTPS proxy configured")
        env["https_proxy"] = https_proxy_url

    if is_deb_installation():
        logger.info("Detected deb-installed SquidStats; updating via git pull")
        return _update_deb_installation(install_dir, env)

    if not os.path.isdir(os.path.join(install_dir, ".git")):
        logger.error(
            "No git repository found in %s. Cannot perform automatic update.",
            install_dir,
        )
        return False

    try:
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

            logger.info(f"Latest release tag resolved: {latest_tag}")
            script_url = f"https://github.com/kaelthasmanu/SquidStats/releases/download/{latest_tag}/install.sh"
            logger.info(f"Downloading update script from {script_url}")
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

            logger.debug(f"Written update script to temporary file: {tmp_script_path}")
            os.chmod(tmp_script_path, 0o700)
            args = [sh_bin, tmp_script_path, "--update"]
            logger.info(f"Executing update script with command: {args}")
            try:
                # The external update script is downloaded from the official GitHub
                # release feed, then written to a temporary file and executed.
                # This is intentionally executing remote installer content.
                subprocess.run(args, env=env, check=True, timeout=600)  # noqa: S603
                logger.info("Update script executed successfully")
            finally:
                try:
                    os.remove(tmp_script_path)
                except OSError:
                    logger.warning(
                        f"Unable to remove temporary update script: {tmp_script_path}"
                    )
            return True
        except Exception:
            logger.exception("Error descargando el script de actualización")
            return False

    except Exception:
        logger.exception("Error crítico en updateSquidStats")
        return False


_WEB_UPDATE_CACHE = {"data": None, "timestamp": 0}
_WEB_CACHE_TTL = 300  # 5 minutos
_GITHUB_WEB_API = "https://api.github.com/repos/kaelthasmanu/SquidStats/releases/latest"


def _parse_web_version(version_str):
    """Extrae la tupla numérica de una versión, ignorando prefijos como 'v'."""
    if not version_str:
        return (0, 0, 0)
    cleaned = re.sub(r"^[vV]", "", version_str.strip())
    parts = re.split(r"[.-]", cleaned)
    nums = []
    for part in parts:
        try:
            nums.append(int(part))
        except ValueError:
            break
    return tuple(nums) if nums else (0, 0, 0)


def _web_version_is_newer(current, latest):
    """Devuelve True si latest es mayor que current."""
    return _parse_web_version(latest) > _parse_web_version(current)


def check_web_update(current_version, force_refresh=False):
    """Verifica si existe una versión más reciente de SquidStats en GitHub.

    Args:
        current_version (str): Versión actual de la aplicación (p. ej. Config.VERSION).
        force_refresh (bool): Ignora el caché y consulta GitHub nuevamente.

    Retorna un dict con:
        - available (bool)
        - current (str): versión actual proporcionada
        - latest (str): última versión en GitHub o None
        - error (str|None): mensaje de error si falló la consulta
    """
    global _WEB_UPDATE_CACHE
    now = time.time()
    if (
        not force_refresh
        and _WEB_UPDATE_CACHE["data"]
        and (now - _WEB_UPDATE_CACHE["timestamp"] < _WEB_CACHE_TTL)
    ):
        return _WEB_UPDATE_CACHE["data"]

    try:
        proxy_url = os.getenv("HTTP_PROXY", "") or os.getenv("HTTPS_PROXY", "")
        proxies = None
        if proxy_url:
            proxies = {"http": proxy_url, "https": proxy_url}

        response = requests.get(
            _GITHUB_WEB_API,
            proxies=proxies,
            timeout=30,
        )
        response.raise_for_status()
        latest_version = response.json().get("tag_name", "")
        if not latest_version:
            result = {
                "available": False,
                "current": current_version,
                "latest": None,
                "error": "No se pudo obtener la última versión desde GitHub",
            }
            _WEB_UPDATE_CACHE = {"data": result, "timestamp": now}
            return result

        available = _web_version_is_newer(current_version or "0", latest_version)
        result = {
            "available": available,
            "current": current_version,
            "latest": latest_version,
            "error": None,
        }
        _WEB_UPDATE_CACHE = {"data": result, "timestamp": now}
        return result
    except Exception as e:
        logger.error(f"Error verificando actualización de SquidStats: {e}")
        result = {
            "available": False,
            "current": current_version,
            "latest": None,
            "error": str(e),
        }
        _WEB_UPDATE_CACHE = {"data": result, "timestamp": now}
        return result

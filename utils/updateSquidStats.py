import os
import shutil
import subprocess
import tempfile

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


_DEB_INSTALL_PATHS = {"/opt/SquidStats/app", "/usr/share/squidstats"}


def is_deb_installation() -> bool:
    """Return True when the app is running from a .deb-managed installation path."""
    install_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return install_dir in _DEB_INSTALL_PATHS


def _run_git_command(args, cwd, env, capture_output=True, timeout=120):
    return subprocess.run(
        ["git", *args],
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
        result = _run_git_command(["ls-remote", "--heads", "origin", branch], install_dir, env)
        if result.returncode == 0 and result.stdout.strip():
            return branch
    return None


def _prepare_deb_git_repo(install_dir, env):
    git_dir = os.path.join(install_dir, ".git")
    repo_initialized = False
    if not os.path.isdir(git_dir):
        logger.info("Initializing git repository in deb-installed path: %s", install_dir)
        result = _run_git_command(["init"], install_dir, env)
        if result.returncode != 0:
            logger.error("Failed to initialize git repository: %s", result.stderr.strip())
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
                ["remote", "set-url", "origin", "https://github.com/kaelthasmanu/SquidStats.git"],
                install_dir,
                env,
            )
        else:
            logger.info(
                "Adding git origin remote: %s",
                "https://github.com/kaelthasmanu/SquidStats.git",
            )
            result = _run_git_command(
                ["remote", "add", "origin", "https://github.com/kaelthasmanu/SquidStats.git"],
                install_dir,
                env,
            )
        if result.returncode != 0:
            logger.error("Failed to configure git origin remote: %s", result.stderr.strip())
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
        result = _run_git_command(["checkout", "-B", branch, f"origin/{branch}"], install_dir, env)
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

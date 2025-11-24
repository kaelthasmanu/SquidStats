import os
import subprocess

notifications_data = {"commits": [], "has_updates": False}


def set_commit_notifications(has_updates, messages):
    notifications_data["has_updates"] = has_updates
    notifications_data["commits"] = messages


def get_commit_notifications():
    return notifications_data


def has_remote_commits_with_messages(
    repo_path: str, branch: str = "main"
) -> tuple[bool, list[str]]:
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        raise ValueError(f"No es un repositorio Git válido: {repo_path}")
    try:
        # Configurar proxy si existe la variable de entorno
        env = os.environ.copy()
        http_proxy = env.get("HTTP_PROXY", "")
        if http_proxy:
            env["http_proxy"] = http_proxy
            env["https_proxy"] = http_proxy

        subprocess.run(
            ["git", "fetch"],
            cwd=repo_path,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        result = subprocess.run(
            [
                "git",
                "rev-list",
                "--left-right",
                "--count",
                f"origin/{branch}...{branch}",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        ahead_behind = result.stdout.strip().split()
        remote_ahead = int(ahead_behind[0])

        if remote_ahead > 0:
            log_result = subprocess.run(
                ["git", "log", f"{branch}..origin/{branch}", "--pretty=format:%s"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            commit_messages = (
                log_result.stdout.strip().split("\n")
                if log_result.stdout.strip()
                else []
            )
            return True, commit_messages

        return False, []

    except subprocess.CalledProcessError as e:
        print(f"Error al ejecutar comandos git: {e.stderr}")
        return False, []

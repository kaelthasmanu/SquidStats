import requests
from loguru import logger

from services.admin_helpers import load_env_vars, save_env_vars


def test_pihole_connection(host: str, token: str | None = None) -> tuple[bool, str]:
    if not host:
        return False, "Host no proporcionado"

    url = host
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"

    params = {}
    headers = {}
    if token:
        headers["Authorization"] = token
        params["auth"] = token

    try:
        resp = requests.get(f"{url}/admin/api.php", params=params, headers=headers, timeout=6)
        if resp.status_code == 200:
            return True, "Conexión a Pi-hole exitosa"
        return False, f"Respuesta inesperada de Pi-hole: {resp.status_code}"
    except Exception as e:
        logger.exception("Error probando conexión Pi-hole")
        return False, f"Error al conectar con Pi-hole: {str(e)}"


def import_domains_from_file(file_storage) -> set:
    domains = set()
    if not file_storage:
        return domains

    content = file_storage.read().decode("utf-8", errors="ignore")
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if " " in line:
            parts = line.split()
            domain = parts[-1]
        else:
            domain = line
        domains.add(domain)
    return domains


def import_domains_from_url(url: str) -> tuple[bool, set, str]:
    domains = set()
    try:
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return False, domains, f"Error al descargar la lista: {resp.status_code}"

        for line in resp.text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if " " in line:
                parts = line.split()
                domain = parts[-1]
            else:
                domain = line
            domains.add(domain)
        return True, domains, ""
    except Exception as e:
        logger.exception("Error descargando lista desde URL")
        return False, domains, str(e)


def merge_and_save_blacklist(existing_env: dict, new_domains: set) -> None:
    existing = [d.strip() for d in existing_env.get("BLACKLIST_DOMAINS", "").split(",") if d.strip()]
    merged = set(existing)
    merged.update(new_domains)
    existing_env["BLACKLIST_DOMAINS"] = ",".join(sorted(merged))
    save_env_vars(existing_env)


def save_custom_list(items: list) -> None:
    env_vars = load_env_vars()
    env_vars["BLACKLIST_DOMAINS"] = ",".join(sorted(set(items)))
    save_env_vars(env_vars)

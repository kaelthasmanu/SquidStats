import requests
from datetime import datetime
from loguru import logger

from database.database import get_session
from database.models.models import BlacklistDomain


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
        resp = requests.get(
            f"{url}/admin/api.php", params=params, headers=headers, timeout=6
        )
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


def merge_and_save_blacklist(new_domains: set, source: str = "import", source_url: str | None = None, added_by: str | None = None) -> None:
    """Merge given domains into the `blacklist_domains` table.

    - new_domains: set of domain strings
    - source: string describing origin ('file', 'url', 'custom', ...)
    - source_url: optional url if source is 'url'
    - added_by: optional username who added the entries
    """
    if not new_domains:
        return

    session = get_session()
    try:
        now = datetime.now()
        for domain in new_domains:
            domain = domain.strip()
            if not domain:
                continue
            existing = (
                session.query(BlacklistDomain).filter(BlacklistDomain.domain == domain).one_or_none()
            )
            if existing:
                # reactivate and update metadata if necessary
                existing.active = 1
                existing.source = source or existing.source
                if source_url:
                    existing.source_url = source_url
                if added_by:
                    existing.added_by = added_by
                existing.updated_at = now
            else:
                record = BlacklistDomain(
                    domain=domain,
                    source=source,
                    source_url=source_url,
                    added_by=added_by,
                    active=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
        session.commit()
    except Exception as e:
        logger.exception("Error guardando blacklist en DB")
        session.rollback()
        raise
    finally:
        session.close()


def save_custom_list(items: list, added_by: str | None = None) -> None:
    """Replace existing 'custom' source blacklist entries with `items`.

    This keeps other sources intact.
    """
    session = get_session()
    try:
        # Deactivate previous custom entries
        session.query(BlacklistDomain).filter(BlacklistDomain.source == "custom").update({"active": 0})

        now = datetime.now()
        for d in sorted(set(items)):
            domain = d.strip()
            if not domain:
                continue
            existing = (
                session.query(BlacklistDomain).filter(BlacklistDomain.domain == domain).one_or_none()
            )
            if existing:
                existing.active = 1
                existing.source = "custom"
                if added_by:
                    existing.added_by = added_by
                existing.updated_at = now
            else:
                record = BlacklistDomain(
                    domain=domain,
                    source="custom",
                    added_by=added_by,
                    active=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
        session.commit()
    except Exception as e:
        logger.exception("Error guardando lista personalizada en DB")
        session.rollback()
        raise
    finally:
        session.close()

import ipaddress
import socket
import urllib.parse
from datetime import datetime

import requests
from loguru import logger
from requests.exceptions import RequestException, SSLError

from database.database import get_session
from database.models.models import BlacklistDomain


def _requests_get_pinned(
    url: str, resolved_ips: list[str], timeout: int = 8
) -> requests.Response:
    """Make an HTTP(S) request to one of the validated IPs while preserving the original Host header.

    - Picks the first resolved IP from `resolved_ips`.
    - Builds a URL with the IP as netloc (including port when present).
    - Sets `Host` header to the original hostname (with port if specified) so virtual hosts still work.
    - Disables redirects to avoid redirection to internal addresses.

    Notes:
    - For HTTPS, certificate validation may fail if the cert is not valid for the IP; in that case we return the raised exception to the caller.
    """
    parsed = urllib.parse.urlparse(url)
    if not resolved_ips:
        raise ValueError("No resolved IPs provided")

    chosen_ip = resolved_ips[0]
    # Choose the first validated public IP (resolved_ips already filtered)
    # and ensure correct formatting for IPv6 addresses in netloc
    chosen_ip = None
    for candidate in resolved_ips:
        try:
            ip_obj = ipaddress.ip_address(candidate)
        except Exception:
            continue
        # pick the first usable IP; prefer IPv4 over IPv6 by ordering
        chosen_ip = ip_obj
        break

    if chosen_ip is None:
        raise ValueError("No valid IP to connect to")

    # Determine port
    port = parsed.port if parsed.port else (443 if parsed.scheme == "https" else 80)

    # Format host part correctly for IPv6 (requires brackets)
    if chosen_ip.version == 6:
        host_part = f"[{chosen_ip.compressed}]"
    else:
        host_part = chosen_ip.compressed

    netloc_ip = f"{host_part}:{port}" if port else host_part
    new_parsed = parsed._replace(netloc=netloc_ip)
    new_url = urllib.parse.urlunparse(new_parsed)

    # Build Host header with original hostname (and port if non-default)
    host_header = parsed.hostname
    if parsed.port and not (
        (parsed.scheme == "http" and parsed.port == 80)
        or (parsed.scheme == "https" and parsed.port == 443)
    ):
        host_header = f"{parsed.hostname}:{parsed.port}"

    session = requests.Session()
    # Preserve other headers but ensure Host is set to original host
    session.headers.update({"Host": host_header})

    try:
        # URL has been fully validated and IP-pinned to prevent SSRF (CodeQL false positive)
        resp = session.get(new_url, timeout=timeout, allow_redirects=False)
        return resp
    except SSLError:
        # Let caller decide how to handle SSL issues for pinned IPs
        raise
    except RequestException:
        # wrap other request exceptions
        raise


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


def _validate_import_url(url: str) -> tuple[str, list[str]]:
    """Validate a user-provided URL to prevent SSRF.

    - allow only http/https schemes
    - require a hostname (netloc)
    - disallow embedded credentials
    - resolve hostname and reject private/loopback/link-local/multicast/reserved/unspecified IPs

    Returns the original URL if validation passes, otherwise raises ValueError.
    """
    parsed = urllib.parse.urlparse(url)

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError("Esquema inválido: solo se permiten http/https")

    if not parsed.netloc:
        raise ValueError("URL inválida: falta host")

    # Disallow URLs containing credentials
    if parsed.username or parsed.password:
        raise ValueError("URLs con credenciales no permitidas")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL inválida: hostname no encontrado")

    try:
        infos = socket.getaddrinfo(hostname, None)
    except Exception:
        raise ValueError("No se pudo resolver el host")

    all_ips: list[str] = []
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except Exception:
            # If we can't parse the IP, skip this entry conservatively
            continue
        all_ips.append(str(ip))

    # Deduplicate while preserving order
    seen = set()
    deduped_ips = [x for x in all_ips if not (x in seen or seen.add(x))]

    # Filter to only public/global addresses (exclude private/loopback/link-local/multicast/reserved/unspecified)
    public_ips: list[str] = []
    for addr in deduped_ips:
        try:
            ip = ipaddress.ip_address(addr)
        except Exception:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            # skip non-public addresses
            continue
        public_ips.append(str(ip))

    if not public_ips:
        raise ValueError("No se encontraron direcciones públicas válidas para el host")

    # Passed all checks — return original URL and list of validated public IPs (preserved order)
    return url, public_ips


def import_domains_from_url(url: str) -> tuple[bool, set, str]:
    domains = set()
    try:
        # Validate URL and obtain resolved IPs to prevent SSRF targeting internal addresses
        safe_url, resolved_ips = _validate_import_url(url)
        # Perform an IP-pinned request to the verified IP while preserving Host header
        resp = _requests_get_pinned(safe_url, resolved_ips, timeout=8)
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
    except ValueError as ve:
        logger.warning("Blocked unsafe import URL: %s", url)
        return False, domains, str(ve)
    except Exception:
        logger.exception("Error descargando lista desde URL")
        return False, domains, "Error descargando lista desde URL"


def merge_and_save_blacklist(
    new_domains: set,
    source: str = "import",
    source_url: str | None = None,
    added_by: str | None = None,
) -> None:
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
                session.query(BlacklistDomain)
                .filter(BlacklistDomain.domain == domain)
                .one_or_none()
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
    except Exception:
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
        session.query(BlacklistDomain).filter(
            BlacklistDomain.source == "custom"
        ).update({"active": 0})

        now = datetime.now()
        for d in sorted(set(items)):
            domain = d.strip()
            if not domain:
                continue
            existing = (
                session.query(BlacklistDomain)
                .filter(BlacklistDomain.domain == domain)
                .one_or_none()
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
    except Exception:
        logger.exception("Error guardando lista personalizada en DB")
        session.rollback()
        raise
    finally:
        session.close()

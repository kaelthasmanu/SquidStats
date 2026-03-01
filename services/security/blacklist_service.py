import ipaddress
import socket
import threading
import urllib.parse
from datetime import datetime

import requests
import requests.adapters
from loguru import logger

from database.database import get_session
from database.models.models import BlacklistDomain

# ---------------------------------------------------------------------------
# Thread-local DNS pinning infrastructure
# ---------------------------------------------------------------------------
# We patch socket.create_connection once at import time.  The actual IP
# substitution is stored per-thread so concurrent requests never interfere.

_pinned_dns = threading.local()
_original_create_connection = socket.create_connection


def _create_connection_with_pin(address, *args, **kwargs):
    """Drop-in replacement for socket.create_connection that honours per-thread
    DNS overrides set by _PinnedDNSAdapter."""
    host, port = address
    overrides: dict = getattr(_pinned_dns, "overrides", {})
    if host in overrides:
        host = overrides[host]
    return _original_create_connection((host, port), *args, **kwargs)


socket.create_connection = _create_connection_with_pin


class _PinnedDNSAdapter(requests.adapters.HTTPAdapter):
    """HTTPAdapter that forces all connections to a pre-validated IP address
    while keeping the original hostname in the URL.

    Keeping the original hostname means:
    - TLS SNI is sent correctly (e.g. 'github.com', not '140.82.112.3').
    - Certificate CN/SAN is verified against the hostname, not the raw IP.
    - SSRF is still prevented because the TCP socket connects to the validated
      public IP, not whatever DNS would return at connection time.

    Thread-safety: overrides are stored in threading.local() so concurrent
    requests in different threads never see each other's pinned IPs.
    """

    def __init__(self, hostname: str, pinned_ip: str, *args, **kwargs):
        self._hostname = hostname
        self._pinned_ip = pinned_ip
        super().__init__(*args, **kwargs)

    def send(self, request, *args, **kwargs):
        # Install the thread-local override for the duration of this request.
        if not hasattr(_pinned_dns, "overrides"):
            _pinned_dns.overrides = {}
        _pinned_dns.overrides[self._hostname] = self._pinned_ip
        try:
            return super().send(request, *args, **kwargs)
        finally:
            _pinned_dns.overrides.pop(self._hostname, None)


def _requests_get_pinned(
    url: str, resolved_ips: list[str], timeout: int = 8
) -> requests.Response:
    """Make an HTTP(S) request to a pre-validated IP while keeping the original
    hostname for TLS SNI and certificate verification.

    Strategy
    --------
    Rather than rewriting the URL to use the raw IP (which breaks HTTPS because
    the server certificate is issued for the hostname, not the IP), we keep the
    original URL and redirect the TCP connection to the validated IP via a
    thread-local socket patch (_PinnedDNSAdapter).  This gives us:

    * SSRF protection  – the socket never performs a fresh DNS look-up; it
      connects straight to the IP we validated before calling this function.
    * Correct TLS       – SNI and certificate CN/SAN are matched against the
      original hostname, so valid certificates are accepted as normal.
    * Thread-safety     – overrides live in threading.local(); parallel requests
      in other threads are unaffected.
    """
    parsed = urllib.parse.urlparse(url)
    if not resolved_ips:
        raise ValueError("No resolved IPs provided")

    chosen_ip = None
    for candidate in resolved_ips:
        try:
            ip_obj = ipaddress.ip_address(candidate)
        except Exception:
            continue
        chosen_ip = ip_obj
        break

    if chosen_ip is None:
        raise ValueError("No valid IP to connect to")

    hostname = parsed.hostname

    # Reconstruct URL from pre-validated components instead of forwarding
    # the raw user-supplied string (SSRF mitigation — CWE-918).
    sanitized_url = urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path or "/",
        parsed.params,
        parsed.query,
        "",  # fragment is irrelevant for HTTP requests
    ))

    session = requests.Session()
    session.mount("https://", _PinnedDNSAdapter(hostname, chosen_ip.compressed))
    session.mount("http://", _PinnedDNSAdapter(hostname, chosen_ip.compressed))

    try:
        return session.get(sanitized_url, timeout=timeout, allow_redirects=False)
    finally:
        session.close()


def test_pihole_connection(host: str, token: str | None = None) -> tuple[bool, str]:
    if not host:
        return False, "Host no proporcionado"

    url = host
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"

    # Validate URL structure to prevent open-redirect / scheme injection
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False, "URL inválida: esquema o host no válido"
    if parsed.username or parsed.password:
        return False, "URLs con credenciales no permitidas"

    # Build the API URL from validated components (fixed path)
    api_url = urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        "/admin/api.php",
        "",
        "",
        "",
    ))

    params = {}
    headers = {}
    if token:
        headers["Authorization"] = token
        params["auth"] = token

    try:
        resp = requests.get(
            api_url, params=params, headers=headers, timeout=6
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

    # Reconstruct URL from validated components instead of returning raw user input
    sanitized_url = urllib.parse.urlunparse((
        scheme,
        parsed.netloc,
        parsed.path or "/",
        parsed.params,
        parsed.query,
        "",  # fragment is irrelevant for server requests
    ))
    return sanitized_url, public_ips


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

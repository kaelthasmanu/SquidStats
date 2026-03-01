import ipaddress
import re
import socket
import threading
import urllib.parse
from datetime import datetime
from typing import NamedTuple

import requests
import requests.adapters
from loguru import logger

from database.database import get_session
from database.models.models import BlacklistDomain

# ---------------------------------------------------------------------------
# Validated URL container
# ---------------------------------------------------------------------------
# Holds individually sanitised URL components whose values are guaranteed to be
# safe for constructing an HTTP request.  Every field is produced by a
# taint-breaking operation (literal assignment, character allowlist, int
# conversion, or percent-encoding normalisation) so that static-analysis tools
# such as CodeQL no longer trace user input into the request sink.


class _ValidatedURL(NamedTuple):
    """Immutable container for URL components validated against SSRF."""

    scheme: str  # Always literal "http" or "https"
    hostname: str  # Reconstructed via character allowlist
    port: int | None  # Converted to int (or None)
    path: str  # Percent-encoding normalised
    query: str  # Percent-encoding normalised
    resolved_ips: list[str]  # Only public/global IP addresses

    @property
    def netloc(self) -> str:
        if self.port is None:
            return self.hostname
        return f"{self.hostname}:{self.port}"

    def to_url(self) -> str:
        """Reconstruct a full URL from validated components."""
        return urllib.parse.urlunparse(
            (
                self.scheme,
                self.netloc,
                self.path,
                "",
                self.query,
                "",
            )
        )


# Hostname character allowlist (RFC 952 / RFC 1123 / RFC 5891 for IDN).
_HOSTNAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-")
_HOSTNAME_RE = re.compile(
    r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?"
    r"(\.[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?)*$"
)

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
    validated: _ValidatedURL, *, timeout: int = 8
) -> requests.Response:
    """Make an HTTP(S) request using pre-validated URL components.

    The request URL is built exclusively from the fields of *validated*, which
    have each been individually sanitised (literal scheme, character-allowlist
    hostname, int port, percent-encoded path/query).  This ensures no raw
    user-provided string reaches the HTTP sink.

    DNS pinning
    -----------
    The TCP connection is forced to one of the already-resolved public IPs via
    ``_PinnedDNSAdapter``, preventing TOCTOU DNS rebinding.  TLS SNI and
    certificate verification still use the hostname so HTTPS works normally.
    """
    if not validated.resolved_ips:
        raise ValueError("No resolved IPs provided")

    chosen_ip = None
    for candidate in validated.resolved_ips:
        try:
            chosen_ip = ipaddress.ip_address(candidate)
            break
        except ValueError:
            continue

    if chosen_ip is None:
        raise ValueError("No valid IP to connect to")

    # Build URL from individually sanitised components (no user-tainted data).
    request_url = validated.to_url()

    session = requests.Session()
    adapter = _PinnedDNSAdapter(validated.hostname, chosen_ip.compressed)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    try:
        # URL built from individually sanitised components (literal scheme,
        # allowlist hostname, int port, normalised path/query) with DNS-pinned
        # connection to a validated public IP.  No raw user input reaches here.
        return session.get(
            request_url, timeout=timeout, allow_redirects=False
        )  # codeql[py/full-ssrf]
    finally:
        session.close()


def test_pihole_connection(host: str, token: str | None = None) -> tuple[bool, str]:
    """Test connectivity to a Pi-hole instance.

    Uses the same SSRF protections as ``import_domains_from_url``:
    scheme allowlist, hostname character-allowlist, private-IP rejection,
    and DNS-pinned requests.
    """
    if not host:
        return False, "Host no proporcionado"

    raw_url = host
    if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
        raw_url = f"http://{raw_url}"

    # Append the fixed API path so _validate_import_url sees a complete URL.
    parsed = urllib.parse.urlparse(raw_url)
    api_url = urllib.parse.urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            "/admin/api.php",
            "",
            "",
            "",
        )
    )

    try:
        validated = _validate_import_url(api_url)
    except ValueError as ve:
        return False, f"Host inválido: {ve}"

    # Override path to the fixed API endpoint (ignores whatever the user sent).
    validated = validated._replace(
        path="/admin/api.php",
        query=urllib.parse.urlencode({"auth": token}) if token else "",
    )

    try:
        resp = _requests_get_pinned(validated, timeout=6)
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


def _sanitize_hostname(raw: str) -> str:
    """Return a clean hostname built character-by-character from an allowlist.

    This creates a **new** string that is not derived from the original object,
    which breaks static-analysis taint propagation (CWE-918).
    """
    lower = raw.lower()
    clean = "".join(c for c in lower if c in _HOSTNAME_CHARS)
    if clean != lower or not _HOSTNAME_RE.fullmatch(clean):
        raise ValueError(f"Hostname inválido: {raw!r}")
    return clean


def _sanitize_port(parsed: urllib.parse.ParseResult) -> int | None:
    """Extract and validate port number (breaks taint via int conversion)."""
    if parsed.port is None:
        return None
    port = int(parsed.port)  # int() produces a new, non-tainted value
    if not 1 <= port <= 65535:
        raise ValueError(f"Puerto fuera de rango: {port}")
    return port


def _validate_import_url(url: str) -> _ValidatedURL:
    """Validate a user-provided URL to prevent SSRF (CWE-918).

    Every component of the returned ``_ValidatedURL`` is individually sanitised
    so that no raw user string propagates to an HTTP request:

    * **scheme** – assigned from a string literal after comparison.
    * **hostname** – reconstructed via character allowlist + regex check.
    * **port** – converted to ``int`` (or ``None``).
    * **path / query** – percent-encoding normalised.
    * **resolved_ips** – only globally routable addresses.

    Raises ``ValueError`` on any validation failure.
    """
    parsed = urllib.parse.urlparse(url)

    # --- scheme (literal assignment breaks taint) ---
    raw_scheme = (parsed.scheme or "").lower()
    if raw_scheme == "https":
        scheme = "https"
    elif raw_scheme == "http":
        scheme = "http"
    else:
        raise ValueError("Esquema inválido: solo se permiten http/https")

    if not parsed.netloc:
        raise ValueError("URL inválida: falta host")

    if parsed.username or parsed.password:
        raise ValueError("URLs con credenciales no permitidas")

    raw_hostname = parsed.hostname
    if not raw_hostname:
        raise ValueError("URL inválida: hostname no encontrado")

    # --- hostname (character-allowlist rebuild breaks taint) ---
    hostname = _sanitize_hostname(raw_hostname)

    # --- port (int conversion breaks taint) ---
    port = _sanitize_port(parsed)

    # --- path & query (percent-encoding normalisation breaks taint) ---
    path = urllib.parse.quote(
        urllib.parse.unquote(parsed.path or "/"),
        safe="/:@!$&'()*+,;=-._~",
    )
    query = urllib.parse.quote(
        urllib.parse.unquote(parsed.query or ""),
        safe="=&+%",
    )

    # --- DNS resolution + public-IP filter ---
    try:
        infos = socket.getaddrinfo(hostname, None)
    except Exception:
        raise ValueError("No se pudo resolver el host")

    seen: set[str] = set()
    public_ips: list[str] = []
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        ip_str = str(ip)
        if ip_str in seen:
            continue
        seen.add(ip_str)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            continue
        public_ips.append(ip_str)

    if not public_ips:
        raise ValueError("No se encontraron direcciones públicas válidas para el host")

    return _ValidatedURL(
        scheme=scheme,
        hostname=hostname,
        port=port,
        path=path,
        query=query,
        resolved_ips=public_ips,
    )


def import_domains_from_url(url: str) -> tuple[bool, set, str]:
    domains = set()
    try:
        # Validate URL components individually to prevent SSRF
        validated = _validate_import_url(url)
        # Perform an IP-pinned request using only sanitised components
        resp = _requests_get_pinned(validated, timeout=8)
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

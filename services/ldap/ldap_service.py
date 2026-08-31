from __future__ import annotations

from typing import Any

from flask_babel import gettext as _
from ldap3 import (
    ALL,
    KERBEROS,
    NTLM,
    SASL,
    SIMPLE,
    SUBTREE,
    Connection,
    Server,
    Tls,
    core,
)
from ldap3.utils.conv import escape_filter_chars
from loguru import logger

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class KerberosClientUnavailableError(RuntimeError):
    """Raised when the optional GSSAPI client is unavailable."""


class KerberosCredentialsUnavailableError(RuntimeError):
    """Raised when the selected Kerberos principal has no usable credentials."""


class KerberosServicePrincipalNotFoundError(RuntimeError):
    """Raised when LDAP's Kerberos service principal is absent from the KDC."""


def _require_kerberos_client() -> None:
    """Ensure ldap3 can perform its SASL/GSSAPI Kerberos bind."""
    try:
        import gssapi  # noqa: F401
    except ImportError as exc:
        raise KerberosClientUnavailableError from exc


def _is_missing_kerberos_credentials(exc: Exception) -> bool:
    try:
        from gssapi.raw.exceptions import MissingCredentialsError
    except ImportError:
        return False
    return isinstance(exc, MissingCredentialsError)


def _is_missing_kerberos_service_principal(exc: Exception) -> bool:
    """Return whether an exception chain reports an unknown LDAP service SPN."""
    seen: set[int] = set()
    current: Exception | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if "Server not found in Kerberos database" in str(current):
            return True
        next_exception = current.__cause__ or current.__context__
        current = next_exception if isinstance(next_exception, Exception) else None
    return False


def _make_server(host: str, port: int, use_ssl: bool) -> Server:
    tls = Tls(validate=0) if use_ssl else None  # 0 = ssl.CERT_NONE
    return Server(host, port=port, use_ssl=use_ssl, tls=tls, get_info=ALL)


def _connect(cfg: dict) -> Connection:
    """Return an authenticated & bound ldap3 Connection or raise."""
    server = _make_server(cfg["host"], int(cfg["port"]), cfg["use_ssl"])
    auth_type = str(cfg.get("auth_type", "SIMPLE")).upper()
    if auth_type == "KERBEROS":
        _require_kerberos_client()
        try:
            return Connection(
                server,
                user=cfg.get("bind_dn") or None,
                authentication=SASL,
                sasl_mechanism=KERBEROS,
                auto_bind=True,
                raise_exceptions=True,
            )
        except Exception as exc:
            if _is_missing_kerberos_credentials(exc):
                raise KerberosCredentialsUnavailableError from exc
            if _is_missing_kerberos_service_principal(exc):
                raise KerberosServicePrincipalNotFoundError from exc
            raise

    auth_method = NTLM if auth_type == "NTLM" else SIMPLE
    conn = Connection(
        server,
        user=cfg.get("bind_dn", ""),
        password=cfg.get("bind_password", ""),
        authentication=auth_method,
        auto_bind=True,
        raise_exceptions=True,
    )
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def test_connection(cfg: dict) -> dict:
    """Try to bind with the provided settings. Returns status/message dict."""
    try:
        conn = _connect(cfg)
        conn.unbind()
        return {
            "status": "success",
            "message": _("Conexión exitosa al servidor LDAP/AD."),
        }
    except KerberosClientUnavailableError:
        logger.exception("Kerberos GSSAPI client is unavailable")
        return {
            "status": "error",
            "message": _("LDAP_ERROR_KERBEROS_CLIENT_UNAVAILABLE"),
        }
    except KerberosCredentialsUnavailableError:
        logger.exception("Kerberos credentials are unavailable")
        return {
            "status": "error",
            "message": _(
                "No hay credenciales Kerberos disponibles. Obtenga un ticket con kinit y vuelva a intentarlo."
            ),
        }
    except KerberosServicePrincipalNotFoundError:
        logger.exception("LDAP Kerberos service principal was not found")
        return {
            "status": "error",
            "message": _(
                "El servidor LDAP no tiene un principal Kerberos válido. Configure el FQDN de un controlador de dominio."
            ),
        }
    except core.exceptions.LDAPBindError:
        logger.exception("LDAP bind falló")
        return {"status": "error", "message": _("Error de autenticación LDAP")}
    except core.exceptions.LDAPSocketOpenError:
        logger.exception("No se pudo abrir la conexión LDAP")
        return {
            "status": "error",
            "message": _(
                "No se pudo resolver o conectar con el servidor LDAP configurado: %(host)s."
            )
            % {"host": cfg.get("host", "")},
        }
    except Exception:
        logger.exception("Error de conexión LDAP")
        return {
            "status": "error",
            "message": _("Error al conectar con el servidor LDAP"),
        }


def _paged_count(cfg: dict, object_class: str) -> int:
    search_filter = f"(objectClass={object_class})"
    conn = _connect(cfg)
    count = 0
    try:
        for entry in conn.extend.standard.paged_search(
            search_base=cfg["base_dn"],
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=["cn"],
            paged_size=1000,
            generator=True,
        ):
            if isinstance(entry, dict) and entry.get("type") == "searchResEntry":
                count += 1
        return count
    finally:
        conn.unbind()


def get_stats(cfg: dict) -> dict:
    """Return total user and group counts from the directory."""
    try:
        user_count = _paged_count(cfg, "person")
        group_count = _paged_count(cfg, "group")
        return {"status": "success", "users": user_count, "groups": group_count}
    except Exception as exc:
        logger.error(f"Error al obtener estadísticas LDAP: {exc}")
        return {
            "status": "error",
            "message": _("Error al obtener estadísticas LDAP"),
            "users": 0,
            "groups": 0,
        }


def _escape_ldap_filter_value(value: str) -> str:
    """Escape a user-controlled string for safe LDAP filtering."""
    return escape_filter_chars(value or "")


def search_users(cfg: dict, query: str, limit: int = 50) -> dict:
    """Search users whose cn, sAMAccountName or mail matches *query*."""
    query = query.strip().replace("*", "").replace("(", "").replace(")", "")
    escaped_query = _escape_ldap_filter_value(query)
    filter_str = (
        f"(&(objectClass=person)"
        f"(|(cn=*{escaped_query}*)(sAMAccountName=*{escaped_query}*)(mail=*{escaped_query}*)(displayName=*{escaped_query}*)))"
    )
    try:
        conn = _connect(cfg)
        conn.search(
            cfg["base_dn"],
            filter_str,
            attributes=[
                "cn",
                "sAMAccountName",
                "mail",
                "displayName",
                "department",
                "title",
            ],
            size_limit=limit,
        )
        users = []
        for entry in conn.entries:
            users.append(
                {
                    "cn": _val(entry, "cn"),
                    "username": _val(entry, "sAMAccountName"),
                    "email": _val(entry, "mail"),
                    "display_name": _val(entry, "displayName"),
                    "department": _val(entry, "department"),
                    "title": _val(entry, "title"),
                    "dn": entry.entry_dn,
                }
            )
        conn.unbind()
        return {"status": "success", "results": users, "total": len(users)}
    except Exception as exc:
        logger.error(f"Error al buscar usuarios LDAP: {exc}")
        return {
            "status": "error",
            "message": _("Error al buscar usuarios LDAP"),
            "results": [],
            "total": 0,
        }


def search_groups(cfg: dict, query: str, limit: int = 50) -> dict:
    """Search groups whose cn matches *query*.

    If the query is empty, return all groups under the base DN.
    """
    query = query.strip().replace("*", "").replace("(", "").replace(")", "")
    if query:
        escaped_query = _escape_ldap_filter_value(query)
        filter_str = f"(&(objectClass=group)(cn=*{escaped_query}*))"
    else:
        filter_str = "(objectClass=group)"
    try:
        conn = _connect(cfg)
        conn.search(
            cfg["base_dn"],
            filter_str,
            attributes=["cn", "description", "member"],
            size_limit=limit,
        )
        groups = []
        for entry in conn.entries:
            members_raw = entry["member"].values if "member" in entry else []
            groups.append(
                {
                    "cn": _val(entry, "cn"),
                    "description": _val(entry, "description"),
                    "member_count": len(members_raw),
                    "dn": entry.entry_dn,
                }
            )
        conn.unbind()
        return {"status": "success", "results": groups, "total": len(groups)}
    except Exception as exc:
        logger.error(f"Error al buscar grupos LDAP: {exc}")
        return {
            "status": "error",
            "message": _("Error al buscar grupos LDAP"),
            "results": [],
            "total": 0,
        }


def get_user_groups(cfg: dict, username: str) -> dict:
    """Return the groups that *username* (sAMAccountName) belongs to."""
    username = username.strip().replace("*", "").replace("(", "").replace(")", "")
    escaped_username = _escape_ldap_filter_value(username)
    try:
        conn = _connect(cfg)

        # Find the user DN first
        conn.search(
            cfg["base_dn"],
            f"(&(objectClass=person)(sAMAccountName={escaped_username}))",
            attributes=["distinguishedName", "memberOf", "cn", "displayName"],
        )
        if not conn.entries:
            conn.unbind()
            return {
                "status": "error",
                "message": _("Usuario no encontrado."),
                "groups": [],
                "user": None,
            }

        entry = conn.entries[0]
        member_of = entry["memberOf"].values if "memberOf" in entry else []
        groups = []
        for dn in member_of:
            cn = _cn_from_dn(dn)
            groups.append({"cn": cn, "dn": dn})

        conn.unbind()
        return {
            "status": "success",
            "user": {
                "cn": _val(entry, "cn"),
                "display_name": _val(entry, "displayName"),
                "dn": entry.entry_dn,
            },
            "groups": groups,
            "total": len(groups),
        }
    except Exception as exc:
        logger.error(f"Error al obtener grupos del usuario LDAP: {exc}")
        return {
            "status": "error",
            "message": _("Error al obtener grupos del usuario"),
            "groups": [],
            "user": None,
        }


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------


def _val(entry: Any, attr: str, default: str = "") -> str:
    try:
        v = entry[attr].value
        return str(v) if v is not None else default
    except Exception:
        return default


def _cn_from_dn(dn: str) -> str:
    """Extract the CN value from a Distinguished Name string."""
    for part in dn.split(","):
        part = part.strip()
        if part.upper().startswith("CN="):
            return part[3:]
    return dn

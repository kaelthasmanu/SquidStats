from __future__ import annotations

from typing import Any

from flask_babel import gettext as _
from ldap3 import (
    ALL,
    NTLM,
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


def _make_server(host: str, port: int, use_ssl: bool) -> Server:
    tls = Tls(validate=0) if use_ssl else None  # 0 = ssl.CERT_NONE
    return Server(host, port=port, use_ssl=use_ssl, tls=tls, get_info=ALL)


def _connect(cfg: dict) -> Connection:
    """Return an authenticated & bound ldap3 Connection or raise."""
    server = _make_server(cfg["host"], int(cfg["port"]), cfg["use_ssl"])
    auth_method = NTLM if cfg["auth_type"] == "NTLM" else SIMPLE
    conn = Connection(
        server,
        user=cfg["bind_dn"],
        password=cfg["bind_password"],
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
    except core.exceptions.LDAPBindError as exc:
        logger.warning(f"LDAP bind falló: {exc}")
        return {"status": "error", "message": f"Error de autenticación: {exc}"}
    except Exception as exc:
        logger.error(f"Error de conexión LDAP: {exc}")
        return {"status": "error", "message": str(exc)}


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
        return {"status": "error", "message": str(exc), "users": 0, "groups": 0}


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
        return {"status": "error", "message": str(exc), "results": [], "total": 0}


def search_groups(cfg: dict, query: str, limit: int = 50) -> dict:
    """Search groups whose cn matches *query*."""
    query = query.strip().replace("*", "").replace("(", "").replace(")", "")
    escaped_query = _escape_ldap_filter_value(query)
    filter_str = f"(&(objectClass=group)(cn=*{escaped_query}*))"
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
        return {"status": "error", "message": str(exc), "results": [], "total": 0}


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
        return {"status": "error", "message": str(exc), "groups": [], "user": None}


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

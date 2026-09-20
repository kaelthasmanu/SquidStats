"""LDAP configuration persistence service.

Reads and writes LDAP/AD connection settings to the ``ldap_config`` database
table (single-row pattern, same as backup_config).
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from flask_babel import gettext as _
from loguru import logger

from database.database import get_session
from database.models.models import LdapConfig, LdapGroup, LdapGroupMember


def _default_config() -> dict:
    return {
        "host": "",
        "port": 389,
        "use_ssl": False,
        "auth_type": "SIMPLE",
        "bind_dn": "",
        "bind_password": "",
        "base_dn": "",
    }


def _get_fernet(raw_key: str | None) -> Fernet:
    if not raw_key:
        raise RuntimeError("No encryption key available")
    key_bytes = raw_key.encode() if isinstance(raw_key, str) else raw_key
    if len(key_bytes) != 44:
        key_bytes = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
    return Fernet(key_bytes)


def _generate_encryption_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _encrypt_password(password: str, encryption_key: str) -> str:
    cipher = _get_fernet(encryption_key)
    return cipher.encrypt(password.encode()).decode()


def _decrypt_password(encrypted: str, encryption_key: str) -> str:
    cipher = _get_fernet(encryption_key)
    return cipher.decrypt(encrypted.encode()).decode()


def load_config() -> dict:
    """Return LDAP config from the DB. Returns defaults if no row exists."""
    session = get_session()
    try:
        row = session.query(LdapConfig).first()
        if row is None:
            cfg = _default_config()
            print(
                "[LDAP DEBUG] load_config: no config row found, returning defaults", cfg
            )
            return cfg

        bind_password = row.bind_password or ""
        if bind_password and row.encryption_key:
            try:
                bind_password = _decrypt_password(bind_password, row.encryption_key)
            except InvalidToken:
                print(
                    "[LDAP DEBUG] load_config: stored bind_password could not be decrypted with row encryption key, hiding password"
                )
                bind_password = ""
        elif bind_password and not row.encryption_key:
            print(
                "[LDAP DEBUG] load_config: bind_password present without encryption key, keeping raw value"
            )

        cfg = {
            "host": row.host or "",
            "port": row.port or 389,
            "use_ssl": bool(row.use_ssl),
            "auth_type": row.auth_type or "SIMPLE",
            "bind_dn": row.bind_dn or "",
            "bind_password": bind_password,
            "base_dn": row.base_dn or "",
        }
        return cfg
    except Exception as exc:
        logger.warning(f"Could not read ldap_config from DB, using defaults: {exc}")
        print(f"[LDAP DEBUG] load_config: exception reading config -> {exc}")
        return _default_config()
    finally:
        session.close()


def save_config(cfg: dict) -> None:
    """Upsert LDAP configuration into the database (single-row table)."""
    session = get_session()
    try:
        print(f"[LDAP DEBUG] save_config: incoming cfg={cfg}")
        row = session.query(LdapConfig).first()
        if row is None:
            row = LdapConfig(created_at=datetime.now())
            session.add(row)

        row.host = cfg.get("host", "")
        row.port = int(cfg.get("port", 389) or 389)
        row.use_ssl = 1 if cfg.get("use_ssl") else 0
        row.auth_type = cfg.get("auth_type", "SIMPLE")
        row.bind_dn = cfg.get("bind_dn", "")
        row.base_dn = cfg.get("base_dn", "")
        row.updated_at = datetime.now()

        new_password = cfg.get("bind_password", "")
        if new_password:
            if not row.encryption_key:
                row.encryption_key = _generate_encryption_key()
            try:
                row.bind_password = _encrypt_password(new_password, row.encryption_key)
            except Exception as exc:
                print(f"[LDAP DEBUG] save_config: encryption failed -> {exc}")
                row.bind_password = new_password

        session.commit()
        print(
            f"[LDAP DEBUG] save_config: saved row id={row.id} host={row.host} port={row.port} use_ssl={row.use_ssl} auth_type={row.auth_type} base_dn={row.base_dn}"
        )
    except Exception as exc:
        session.rollback()
        logger.error(f"Error saving ldap_config to DB: {exc}")
        print(f"[LDAP DEBUG] save_config: exception -> {exc}")
        raise
    finally:
        session.close()


def _normalize_usernames(raw_usernames) -> list[str]:
    if raw_usernames is None:
        return []
    if isinstance(raw_usernames, str):
        values = [raw_usernames]
    else:
        values = list(raw_usernames)

    usernames: list[str] = []
    for value in values:
        if value is None:
            continue
        for item in re.split(r"[\n,;]+", str(value)):
            username = item.strip()
            if username:
                usernames.append(username)
    return list(dict.fromkeys(usernames))


def _serialize_group(group, session) -> dict:
    members = (
        session.query(LdapGroupMember)
        .filter_by(group_id=group.id)
        .order_by(LdapGroupMember.username.asc())
        .all()
    )
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description or "",
        "source": group.source or "custom",
        "member_count": len(members),
        "members": [
            {"id": member.id, "username": member.username, "source": member.source}
            for member in members
        ],
    }


def _find_group(session, group_id, group_name):
    if group_id not in (None, ""):
        try:
            group = session.query(LdapGroup).filter_by(id=int(group_id)).first()
        except (TypeError, ValueError):
            raise ValueError(_("El identificador del grupo no es válido.")) from None
        if group is not None:
            return group

    name = (group_name or "").strip()
    if name:
        return session.query(LdapGroup).filter(LdapGroup.name == name).first()
    return None


def list_groups() -> dict:
    session = get_session()
    try:
        groups = session.query(LdapGroup).order_by(LdapGroup.name.asc()).all()
        return {
            "status": "success",
            "groups": [_serialize_group(group, session) for group in groups],
        }
    except Exception as exc:
        logger.error(f"Error listing ldap groups: {exc}")
        return {"status": "error", "message": _("No se pudieron cargar los grupos."), "groups": []}
    finally:
        session.close()


def create_group(data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError(_("El nombre del grupo es obligatorio."))
    if len(name) > 255:
        raise ValueError(_("El nombre del grupo no puede superar los 255 caracteres."))

    description = (data.get("description") or "").strip()
    if len(description) > 2000:
        raise ValueError(_("La descripción no puede superar los 2000 caracteres."))
    source = (data.get("source") or "custom").strip().lower() or "custom"
    if source not in {"custom", "ldap"}:
        raise ValueError(_("El origen del grupo no es válido."))
    session = get_session()
    try:
        group = session.query(LdapGroup).filter(LdapGroup.name == name).first()
        if group is None:
            group = LdapGroup(name=name, description=description, source=source)
            session.add(group)
        else:
            group.description = description
            group.source = source
            group.updated_at = datetime.now()
        session.commit()
        return {"status": "success", "message": _("Grupo guardado."), "group": _serialize_group(group, session)}
    except Exception as exc:
        session.rollback()
        logger.error(f"Error creating ldap group: {exc}")
        raise ValueError("No se pudo guardar el grupo.") from exc
    finally:
        session.close()


def add_members(data: dict) -> dict:
    group_id = data.get("group_id")
    group_name = (data.get("group_name") or "").strip()
    usernames = _normalize_usernames(data.get("usernames") or data.get("username") or [])
    if not usernames:
        raise ValueError(_("Debe indicar al menos un usuario."))
    if any(len(username) > 255 for username in usernames):
        raise ValueError(_("El nombre de usuario no puede superar los 255 caracteres."))

    session = get_session()
    try:
        group = _find_group(session, group_id, group_name)
        if group is None:
            raise ValueError(_("No se encontró el grupo."))

        for username in usernames:
            member = (
                session.query(LdapGroupMember)
                .filter_by(group_id=group.id, username=username)
                .first()
            )
            if member is None:
                session.add(
                    LdapGroupMember(
                        group_id=group.id,
                        username=username,
                        source=data.get("source", "manual") or "manual",
                    )
                )
        session.commit()
        return {"status": "success", "message": _("Usuarios añadidos."), **list_groups()}
    except Exception as exc:
        session.rollback()
        logger.error(f"Error adding ldap group members: {exc}")
        raise ValueError(_("No se pudieron añadir los usuarios al grupo.")) from exc
    finally:
        session.close()


def remove_member(data: dict) -> dict:
    group_id = data.get("group_id")
    group_name = (data.get("group_name") or "").strip()
    username = (data.get("username") or "").strip()
    if not username:
        raise ValueError(_("Debe indicar un usuario."))
    if len(username) > 255:
        raise ValueError(_("El nombre de usuario no puede superar los 255 caracteres."))

    session = get_session()
    try:
        group = _find_group(session, group_id, group_name)
        if group is None:
            raise ValueError(_("No se encontró el grupo."))

        member = (
            session.query(LdapGroupMember)
            .filter_by(group_id=group.id, username=username)
            .first()
        )
        if member is not None:
            session.delete(member)
            session.commit()
        return {"status": "success", "message": _("Usuario eliminado."), **list_groups()}
    except Exception as exc:
        session.rollback()
        logger.error(f"Error removing ldap group member: {exc}")
        raise ValueError(_("No se pudo quitar al usuario del grupo.")) from exc
    finally:
        session.close()


def delete_group(data: dict) -> dict:
    group_id = data.get("group_id")
    group_name = (data.get("group_name") or "").strip()
    if group_id in (None, "") and not group_name:
        raise ValueError(_("Debe indicar el grupo a eliminar."))

    session = get_session()
    try:
        group = _find_group(session, group_id, group_name)
        if group is None:
            raise ValueError(_("No se encontró el grupo."))

        session.query(LdapGroupMember).filter_by(group_id=group.id).delete()
        session.delete(group)
        session.commit()
        return {"status": "success", "message": _("Grupo eliminado."), **list_groups()}
    except Exception as exc:
        session.rollback()
        logger.error(f"Error deleting ldap group: {exc}")
        raise ValueError(_("No se pudo eliminar el grupo.")) from exc
    finally:
        session.close()

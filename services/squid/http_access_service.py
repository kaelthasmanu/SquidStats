from loguru import logger


def _find_http_lines(lines):
    return [
        i
        for i, line in enumerate(lines)
        if line.strip().startswith("http_access ") and not line.strip().startswith("#")
    ]


def delete_http_access(rule_index: int, config_manager) -> tuple[bool, str]:
    try:
        if config_manager.is_modular:
            http_content = config_manager.read_modular_config("120_http_access.conf")
            if http_content is not None:
                lines = http_content.split("\n")
                http_lines_indices = _find_http_lines(lines)
                if rule_index >= len(http_lines_indices):
                    return False, "Índice de regla inválido"
                # remove the line
                del lines[http_lines_indices[rule_index]]
                new_content = "\n".join(lines)
                if config_manager.save_modular_config(
                    "120_http_access.conf", new_content
                ):
                    return True, "Regla HTTP Access eliminada exitosamente"
                else:
                    return False, "Error al eliminar la regla modular"

        # Fallback to main config
        lines = config_manager.config_content.split("\n")
        http_lines_indices = _find_http_lines(lines)
        if rule_index >= len(http_lines_indices):
            return False, "Índice de regla inválido"
        del lines[http_lines_indices[rule_index]]
        new_content = "\n".join(lines)
        config_manager.save_config(new_content)
        return True, "Regla HTTP Access eliminada exitosamente"
    except Exception:
        logger.exception("Error eliminando http_access")
        return False, "Error interno al eliminar regla http_access"


def edit_http_access(
    rule_index: int, action: str, acls: list, description: str, config_manager
) -> tuple[bool, str]:
    try:
        acl_string = " ".join([acl.strip() for acl in acls if acl.strip()])
        if not acl_string:
            return False, "Debe especificar al menos una ACL"

        new_rule = f"http_access {action} {acl_string}"

        if config_manager.is_modular:
            http_content = config_manager.read_modular_config("120_http_access.conf")
            if http_content is not None:
                lines = http_content.split("\n")
                http_lines_indices = _find_http_lines(lines)
                if rule_index >= len(http_lines_indices):
                    return False, "Índice de regla inválido"
                i = http_lines_indices[rule_index]
                if description:
                    if i > 0 and lines[i - 1].strip().startswith("#"):
                        lines[i - 1] = f"# {description}"
                    else:
                        lines.insert(i, f"# {description}")
                        i += 1
                lines[i] = new_rule
                new_content = "\n".join(lines)
                if config_manager.save_modular_config(
                    "120_http_access.conf", new_content
                ):
                    return True, "Regla HTTP Access actualizada exitosamente"
                else:
                    return False, "Error al guardar regla modular"

        # Fallback to main config
        lines = config_manager.config_content.split("\n")
        http_lines_indices = _find_http_lines(lines)
        if rule_index >= len(http_lines_indices):
            return False, "Índice de regla inválido"
        i = http_lines_indices[rule_index]
        if description:
            if i > 0 and lines[i - 1].strip().startswith("#"):
                lines[i - 1] = f"# {description}"
            else:
                lines.insert(i, f"# {description}")
                i += 1
        lines[i] = new_rule
        new_content = "\n".join(lines)
        config_manager.save_config(new_content)
        return True, "Regla HTTP Access actualizada exitosamente"
    except Exception:
        logger.exception("Error actualizando http_access")
        return False, "Error interno al actualizar regla http_access"


def add_http_access(
    action: str, acls: list, description: str, config_manager
) -> tuple[bool, str]:
    try:
        acl_string = " ".join([acl.strip() for acl in acls if acl.strip()])
        if not acl_string:
            return False, "Debe especificar al menos una ACL"
        new_rule = f"http_access {action} {acl_string}"
        lines_to_add = []
        if description:
            lines_to_add.append(f"# {description}")
        lines_to_add.append(new_rule)

        if config_manager.is_modular:
            http_content = config_manager.read_modular_config("120_http_access.conf")
            if http_content is not None:
                lines = http_content.split("\n")
                lines.extend(lines_to_add)
                new_content = "\n".join(lines)
                if config_manager.save_modular_config(
                    "120_http_access.conf", new_content
                ):
                    return True, "Regla HTTP Access agregada exitosamente"
                else:
                    return False, "Error al guardar regla modular"

        lines = config_manager.config_content.split("\n")
        lines.extend(lines_to_add)
        new_content = "\n".join(lines)
        config_manager.save_config(new_content)
        return True, "Regla HTTP Access agregada exitosamente"
    except Exception:
        logger.exception("Error agregando http_access")
        return False, "Error interno al agregar regla http_access"


def add_http_deny_blocklist(
    acl_name: str, config_manager
) -> tuple[bool, str]:
    """Add an ``http_access deny <acl_name>`` rule for the blocklist.

    The deny rule is inserted **before** the first ``http_access allow`` rule
    so that blocked domains are rejected before any allow rule can match.
    If a deny rule for this ACL already exists, it is not duplicated.

    Args:
        acl_name: Name of the blocklist ACL (must match the ACL created by
            :func:`add_acl_blocklist`).
        config_manager: A :class:`SquidConfigManager` instance.

    Returns:
        ``(success, message)`` tuple.
    """
    if not acl_name:
        return False, "Debe proporcionar el nombre de la ACL de blocklist"

    deny_rule = f"http_access deny {acl_name}"
    comment = f"# Deny blocklist gestionada por SquidStats ({acl_name})"

    try:
        if config_manager.is_modular:
            http_content = config_manager.read_modular_config(
                "120_http_access.conf"
            )
            if http_content is not None:
                lines = http_content.split("\n")

                # Check if the deny rule already exists
                for line in lines:
                    if line.strip() == deny_rule:
                        return True, f"La regla deny para '{acl_name}' ya existe"

                # Find the first http_access allow to insert before it
                insert_idx = len(lines)
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("http_access allow"):
                        insert_idx = i
                        break

                lines.insert(insert_idx, comment)
                lines.insert(insert_idx + 1, deny_rule)
                new_content = "\n".join(lines)
                if config_manager.save_modular_config(
                    "120_http_access.conf", new_content
                ):
                    return (
                        True,
                        f"Regla 'http_access deny {acl_name}' agregada exitosamente",
                    )
                else:
                    return False, "Error al guardar regla deny modular"

        # Fallback to main config
        lines = config_manager.config_content.split("\n")

        for line in lines:
            if line.strip() == deny_rule:
                return True, f"La regla deny para '{acl_name}' ya existe"

        insert_idx = len(lines)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("http_access allow"):
                insert_idx = i
                break

        lines.insert(insert_idx, comment)
        lines.insert(insert_idx + 1, deny_rule)
        new_content = "\n".join(lines)
        config_manager.save_config(new_content)
        return (
            True,
            f"Regla 'http_access deny {acl_name}' agregada exitosamente",
        )
    except Exception:
        logger.exception("Error agregando http_access deny para blocklist")
        return False, "Error interno al agregar regla http_access deny"


def remove_http_deny_blocklist(
    acl_name: str, config_manager
) -> tuple[bool, str]:
    """Remove the ``http_access deny <acl_name>`` rule and its comment.

    Supports both modular (``120_http_access.conf``) and monolithic config.

    Args:
        acl_name: Name of the blocklist ACL whose deny rule should be removed.
        config_manager: A :class:`SquidConfigManager` instance.

    Returns:
        ``(success, message)`` tuple.
    """
    if not acl_name:
        return False, "Debe proporcionar el nombre de la ACL de blocklist"

    deny_rule = f"http_access deny {acl_name}"

    def _strip_deny(lines: list[str]) -> list[str]:
        """Return lines without the deny rule and its preceding comment."""
        result: list[str] = []
        skip_next = False
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            # Check if this is our deny rule
            if stripped == deny_rule:
                # Also remove the comment immediately above if it belongs to us
                if result and result[-1].strip().startswith(
                    "# Deny blocklist gestionada por SquidStats"
                ):
                    result.pop()
                i += 1
                continue
            result.append(lines[i])
            i += 1
        return result

    try:
        removed = False

        if config_manager.is_modular:
            http_content = config_manager.read_modular_config(
                "120_http_access.conf"
            )
            if http_content is not None:
                lines = http_content.split("\n")
                cleaned = _strip_deny(lines)
                if len(cleaned) != len(lines):
                    removed = True
                new_content = "\n".join(cleaned)
                if not config_manager.save_modular_config(
                    "120_http_access.conf", new_content
                ):
                    return False, "Error guardando config modular de http_access"

        # Also clean main config
        lines = config_manager.config_content.split("\n")
        cleaned = _strip_deny(lines)
        if len(cleaned) != len(lines):
            removed = True
        new_content = "\n".join(cleaned)
        config_manager.save_config(new_content)

        if removed:
            return (
                True,
                f"Regla 'http_access deny {acl_name}' eliminada exitosamente",
            )
        return True, f"No se encontró regla deny para '{acl_name}' (ya eliminada)"
    except Exception:
        logger.exception("Error eliminando http_access deny para blocklist")
        return False, "Error interno al eliminar regla http_access deny"


def move_http_access(
    rule_index: int, direction: str, config_manager
) -> tuple[bool, str]:
    try:
        if config_manager.is_modular:
            http_content = config_manager.read_modular_config("120_http_access.conf")
            if http_content is not None:
                lines = http_content.split("\n")
                http_lines_indices = _find_http_lines(lines)
                if rule_index >= len(http_lines_indices):
                    return False, "Índice de regla inválido"
                current = http_lines_indices[rule_index]
                if direction == "up" and rule_index > 0:
                    target = http_lines_indices[rule_index - 1]
                    lines[current], lines[target] = lines[target], lines[current]
                elif direction == "down" and rule_index < len(http_lines_indices) - 1:
                    target = http_lines_indices[rule_index + 1]
                    lines[current], lines[target] = lines[target], lines[current]
                new_content = "\n".join(lines)
                config_manager.save_modular_config("120_http_access.conf", new_content)
                return True, "Regla movida exitosamente"

        lines = config_manager.config_content.split("\n")
        http_lines_indices = _find_http_lines(lines)
        if rule_index >= len(http_lines_indices):
            return False, "Índice de regla inválido"
        current = http_lines_indices[rule_index]
        if direction == "up" and rule_index > 0:
            target = http_lines_indices[rule_index - 1]
            lines[current], lines[target] = lines[target], lines[current]
        elif direction == "down" and rule_index < len(http_lines_indices) - 1:
            target = http_lines_indices[rule_index + 1]
            lines[current], lines[target] = lines[target], lines[current]
        new_content = "\n".join(lines)
        config_manager.save_config(new_content)
        return True, "Regla movida exitosamente"
    except Exception:
        logger.exception("Error moviendo http_access")
        return False, "Error interno al mover regla http_access"

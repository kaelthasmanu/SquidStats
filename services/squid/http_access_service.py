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

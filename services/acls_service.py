from loguru import logger


def add_acl(name: str, acl_type: str, values: list, options: list, comment: str, config_manager) -> tuple[bool, str]:
    if not name or not acl_type or not values:
        return False, "Debe proporcionar nombre, tipo y al menos un valor para la ACL"

    acl_parts = ["acl", name]
    if options:
        acl_parts.extend(options)
    acl_parts.append(acl_type)
    acl_parts.extend(values)
    new_acl = " ".join(acl_parts)

    try:
        if config_manager.is_modular:
            acl_content = config_manager.read_modular_config("100_acls.conf")
            if acl_content is not None:
                lines = acl_content.split("\n")
                if comment:
                    lines.append(f"# {comment}")
                lines.append(new_acl)
                new_content = "\n".join(lines)
                if config_manager.save_modular_config("100_acls.conf", new_content):
                    return True, f"ACL '{name}' agregada exitosamente"
                else:
                    return False, "Error al guardar la ACL en modular"

        # Fallback to main config
        lines = config_manager.config_content.split("\n")
        acl_section_end = -1
        for i, line in enumerate(lines):
            if line.strip().startswith("acl "):
                acl_section_end = i

        if acl_section_end != -1:
            if comment:
                lines.insert(acl_section_end + 1, f"# {comment}")
                lines.insert(acl_section_end + 2, new_acl)
            else:
                lines.insert(acl_section_end + 1, new_acl)
        else:
            if comment:
                lines.append(f"# {comment}")
            lines.append(new_acl)

        new_content = "\n".join(lines)
        config_manager.save_config(new_content)
        return True, f"ACL '{name}' agregada exitosamente"
    except Exception as e:
        logger.exception("Error agregando ACL")
        return False, str(e)


def edit_acl(acl_index: int, new_name: str, acl_type: str, values: list, options: list, comment: str, config_manager) -> tuple[bool, str]:
    try:
        acls = config_manager.get_acls()
        if not (0 <= acl_index < len(acls)):
            return False, "ACL no encontrada"

        target_acl = acls[acl_index]
        target_line = target_acl["line_number"] - 1

        acl_parts = ["acl", new_name]
        if options:
            acl_parts.extend(options)
        acl_parts.append(acl_type)
        acl_parts.extend(values)
        new_acl_line = " ".join(acl_parts)

        if config_manager.is_modular:
            acl_content = config_manager.read_modular_config("100_acls.conf")
            if acl_content is not None:
                lines = acl_content.split("\n")
                if 0 <= target_line < len(lines):
                    has_comment = target_line > 0 and lines[target_line - 1].strip().startswith("#")
                    lines[target_line] = new_acl_line
                    if has_comment:
                        if comment:
                            lines[target_line - 1] = f"# {comment}"
                        else:
                            lines.pop(target_line - 1)
                    else:
                        if comment:
                            lines.insert(target_line, f"# {comment}")
                    new_content = "\n".join(lines)
                    if config_manager.save_modular_config("100_acls.conf", new_content):
                        return True, f"ACL '{new_name}' actualizada exitosamente"
                    else:
                        return False, "Error guardando ACL modular"

        # Fallback to main config
        lines = config_manager.config_content.split("\n")
        if 0 <= target_line < len(lines):
            lines[target_line] = new_acl_line
            if target_line > 0 and lines[target_line - 1].strip().startswith("#"):
                if comment:
                    lines[target_line - 1] = f"# {comment}"
                else:
                    lines.pop(target_line - 1)
            else:
                if comment:
                    lines.insert(target_line, f"# {comment}")
            new_content = "\n".join(lines)
            config_manager.save_config(new_content)
            return True, f"ACL '{new_name}' actualizada exitosamente"
        return False, "Línea de ACL no encontrada"
    except Exception as e:
        logger.exception("Error editando ACL")
        return False, str(e)


def delete_acl(acl_index: int, config_manager) -> tuple[bool, str]:
    try:
        acls = config_manager.get_acls()
        if not (0 <= acl_index < len(acls)):
            return False, "ACL no encontrada"

        acl_to_delete = acls[acl_index]
        target_line = acl_to_delete["line_number"] - 1

        if config_manager.is_modular:
            acl_content = config_manager.read_modular_config("100_acls.conf")
            if acl_content is not None:
                lines = acl_content.split("\n")
                comment_to_remove = None
                if target_line > 0 and lines[target_line - 1].strip().startswith("#"):
                    comment_to_remove = target_line - 1
                new_lines = []
                for i, line in enumerate(lines):
                    if i == target_line:
                        continue
                    if comment_to_remove is not None and i == comment_to_remove:
                        continue
                    new_lines.append(line)
                new_content = "\n".join(new_lines)
                if config_manager.save_modular_config("100_acls.conf", new_content):
                    return True, f"ACL '{acl_to_delete['name']}' eliminada exitosamente"
                else:
                    return False, "Error al eliminar ACL modular"

        lines = config_manager.config_content.split("\n")
        comment_to_remove = None
        if target_line > 0 and lines[target_line - 1].strip().startswith("#"):
            comment_to_remove = target_line - 1
        new_lines = []
        for i, line in enumerate(lines):
            if i == target_line:
                continue
            if comment_to_remove is not None and i == comment_to_remove:
                continue
            new_lines.append(line)
        new_content = "\n".join(new_lines)
        config_manager.save_config(new_content)
        return True, f"ACL '{acl_to_delete['name']}' eliminada exitosamente"
    except Exception as e:
        logger.exception("Error eliminando ACL")
        return False, str(e)

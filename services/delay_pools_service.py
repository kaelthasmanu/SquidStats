from loguru import logger


def delete_delay_pool(pool_number: str, config_manager) -> tuple[bool, str]:
    try:
        if config_manager.is_modular:
            delay_content = config_manager.read_modular_config("110_delay_pools.conf")
            if delay_content is not None:
                lines = delay_content.split("\n")
                new_lines = []
                for line in lines:
                    stripped = line.strip()
                    if (
                        stripped.startswith(f"delay_class {pool_number} ")
                        or stripped.startswith(f"delay_parameters {pool_number} ")
                        or stripped.startswith(f"delay_access {pool_number} ")
                    ):
                        continue
                    new_lines.append(line)
                new_content = "\n".join(new_lines)
                if config_manager.save_modular_config(
                    "110_delay_pools.conf", new_content
                ):
                    return True, f"Delay Pool #{pool_number} eliminado exitosamente"
                else:
                    return False, "Error al eliminar delay pool modular"

        # Fallback to main config
        lines = config_manager.config_content.split("\n")
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if (
                stripped.startswith(f"delay_class {pool_number} ")
                or stripped.startswith(f"delay_parameters {pool_number} ")
                or stripped.startswith(f"delay_access {pool_number} ")
            ):
                continue
            new_lines.append(line)
        new_content = "\n".join(new_lines)
        config_manager.save_config(new_content)
        return True, f"Delay Pool #{pool_number} eliminado exitosamente"
    except Exception as e:
        logger.exception("Error eliminando delay pool")
        return False, str(e)


def edit_delay_pool(
    pool_number: str,
    pool_class: str,
    parameters: str,
    access_actions: list,
    access_acls: list,
    config_manager,
) -> tuple[bool, str]:
    try:
        new_directives = []
        new_directives.append(f"delay_class {pool_number} {pool_class}")
        new_directives.append(f"delay_parameters {pool_number} {parameters}")
        for action, acl in zip(access_actions, access_acls, strict=False):
            if acl.strip():
                new_directives.append(f"delay_access {pool_number} {action} {acl}")

        if config_manager.is_modular:
            delay_content = config_manager.read_modular_config("110_delay_pools.conf")
            if delay_content is not None:
                lines = delay_content.split("\n")
                new_lines = []
                pool_found = False
                insert_index = -1
                for i, line in enumerate(lines):
                    if line.strip().startswith(f"delay_class {pool_number} "):
                        pool_found = True
                        insert_index = i
                        # skip existing block (we will rebuild)
                        continue
                    if pool_found and (
                        line.strip().startswith("delay_class ") or line.strip() == ""
                    ):
                        pool_found = False
                    if not pool_found:
                        new_lines.append(line)

                if insert_index >= 0:
                    # insert our directives at the insertion point
                    new_lines[insert_index:insert_index] = new_directives
                else:
                    new_lines.extend(new_directives)
                new_content = "\n".join(new_lines)
                if config_manager.save_modular_config(
                    "110_delay_pools.conf", new_content
                ):
                    return True, f"Delay Pool #{pool_number} actualizado exitosamente"
                else:
                    return False, "Error al guardar delay pool modular"

        # Fallback to main config: naive append/update
        lines = config_manager.config_content.split("\n")
        # Try to find existing pool and replace, else append
        pool_found = False
        insert_index = -1
        for i, line in enumerate(lines):
            if line.strip().startswith(f"delay_class {pool_number} "):
                pool_found = True
                insert_index = i
                break

        if insert_index >= 0:
            # remove existing block lines starting at insert_index until next blank or next delay_class
            j = insert_index
            while j < len(lines) and not (
                lines[j].strip().startswith("delay_class ") and j != insert_index
            ):
                j += 1
            new_lines = lines[:insert_index] + new_directives + lines[j:]
        else:
            new_lines = lines + new_directives

        new_content = "\n".join(new_lines)
        config_manager.save_config(new_content)
        return True, f"Delay Pool #{pool_number} actualizado exitosamente"
    except Exception as e:
        logger.exception("Error actualizando delay pool")
        return False, str(e)


def add_delay_pool(
    pool_number: str,
    pool_class: str,
    parameters: str,
    access_actions: list,
    access_acls: list,
    config_manager,
) -> tuple[bool, str]:
    try:
        new_directives = []
        new_directives.append(f"delay_class {pool_number} {pool_class}")
        new_directives.append(f"delay_parameters {pool_number} {parameters}")
        for action, acl in zip(access_actions, access_acls, strict=False):
            if acl.strip():
                new_directives.append(f"delay_access {pool_number} {action} {acl}")

        if config_manager.is_modular:
            delay_content = config_manager.read_modular_config("110_delay_pools.conf")
            if delay_content is not None:
                lines = delay_content.split("\n")
                lines.extend(new_directives)
                new_content = "\n".join(lines)
                if config_manager.save_modular_config(
                    "110_delay_pools.conf", new_content
                ):
                    return True, f"Delay Pool #{pool_number} creado exitosamente"
                else:
                    return False, "Error al crear delay pool modular"

        lines = config_manager.config_content.split("\n")
        lines.extend(new_directives)
        new_content = "\n".join(lines)
        config_manager.save_config(new_content)
        return True, f"Delay Pool #{pool_number} creado exitosamente"
    except Exception as e:
        logger.exception("Error creando delay pool")
        return False, str(e)

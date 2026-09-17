from loguru import logger


def save_config(new_content: str, config_manager) -> tuple[bool, str]:
    try:
        if not config_manager.save_config(new_content):
            return False, "No se pudo guardar la configuración"
        return True, "Configuration saved successfully"
    except Exception:
        logger.exception("Error saving configuration")
        return False, "Error interno al guardar la configuración"

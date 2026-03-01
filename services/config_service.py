from loguru import logger


def save_config(new_content: str, config_manager) -> tuple[bool, str]:
    try:
        config_manager.save_config(new_content)
        return True, "Configuration saved successfully"
    except Exception as e:
        logger.exception("Error saving configuration")
        return False, "Error interno al guardar la configuración"

from loguru import logger

from services.auth.auth_service import AuthService


def get_all_users():
    try:
        return AuthService.get_all_users()
    except Exception:
        logger.exception("Error getting users")
        return []


def create_user(username: str, password: str, role: str = "admin") -> tuple[bool, str]:
    if not username or not password:
        return False, "El nombre de usuario y la contraseña son obligatorios"
    if len(password) < 8:
        return False, "La contraseña debe tener al menos 8 caracteres"

    try:
        ok = AuthService.create_user(username, password, role)
        if ok:
            return True, "Usuario creado exitosamente"
        return False, "Error al crear usuario. El nombre de usuario puede existir."
    except Exception:
        logger.exception("Error creating user")
        return False, "Error interno al crear usuario"


def update_user(
    user_id: int, username: str, password: str, role: str, is_active: int
) -> tuple[bool, str]:
    if password and len(password) < 8:
        return False, "La contraseña debe tener al menos 8 caracteres"

    update_data = {"username": username, "role": role, "is_active": is_active}
    if password:
        update_data["password"] = password

    try:
        ok = AuthService.update_user(user_id, **update_data)
        if ok:
            return True, "Usuario actualizado exitosamente"
        return False, "Error al actualizar usuario"
    except Exception:
        logger.exception("Error updating user")
        return False, "Error interno al actualizar usuario"


def delete_user(user_id: int) -> tuple[bool, str]:
    try:
        ok = AuthService.delete_user(user_id)
        if ok:
            return True, "Usuario eliminado exitosamente"
        return (
            False,
            "Error al eliminar usuario. No se puede eliminar el usuario admin.",
        )
    except Exception:
        logger.exception("Error deleting user")
        return False, "Error interno al eliminar usuario"

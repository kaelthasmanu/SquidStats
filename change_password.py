#!/usr/bin/env python3
"""
Script to change admin user password from the command line.
Usage: python3 change_password.py [username]
If username is not provided, it defaults to 'admin'.
"""

import os
import sys
from getpass import getpass

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bcrypt

from database.database import AdminUser, get_session


def hash_password(password: str) -> tuple[str, str]:
    """Hash a password with bcrypt and return (hash, salt)."""
    salt = bcrypt.gensalt()
    password_hash = bcrypt.hashpw(password.encode("utf-8"), salt)
    return password_hash.decode("utf-8"), salt.decode("utf-8")


def change_password(username: str, new_password: str) -> bool:
    """
    Change the password for a given username.

    Args:
        username: The username to update
        new_password: The new password to set

    Returns:
        True if successful, False otherwise
    """
    session = get_session()
    try:
        # Find user by username
        user = session.query(AdminUser).filter_by(username=username).first()

        if not user:
            print(f"❌ Usuario '{username}' no encontrado en la base de datos")
            print("\nUsuarios disponibles:")
            all_users = session.query(AdminUser).all()
            for u in all_users:
                status = "✓ activo" if u.is_active else "✗ inactivo"
                print(f"  - {u.username} ({status})")
            return False

        # Generate new hash
        password_hash, salt = hash_password(new_password)

        # Update in database
        user.password_hash = password_hash
        user.salt = salt
        user.is_active = 1  # Activate user if it was inactive

        session.commit()
        print(f"✅ Contraseña actualizada exitosamente para '{username}'")
        print(f"   Estado: {'Activo' if user.is_active else 'Inactivo'}")
        print(f"   Rol: {user.role}")
        return True

    except Exception as e:
        session.rollback()
        print(f"❌ Error al cambiar contraseña: {e}")
        return False
    finally:
        session.close()


def list_users():
    """List all admin users in the database."""
    session = get_session()
    try:
        users = session.query(AdminUser).all()

        if not users:
            print("No hay usuarios en la base de datos")
            return

        print("\n" + "=" * 60)
        print("USUARIOS ADMINISTRADORES")
        print("=" * 60)

        for user in users:
            status = "✓ ACTIVO" if user.is_active else "✗ INACTIVO"
            last_login = (
                user.last_login.strftime("%Y-%m-%d %H:%M:%S")
                if user.last_login
                else "Nunca"
            )

            print(f"\nUsuario: {user.username}")
            print(f"  ID: {user.id}")
            print(f"  Rol: {user.role}")
            print(f"  Estado: {status}")
            print(f"  Último login: {last_login}")
            print(f"  Creado: {user.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

        print("\n" + "=" * 60)

    except Exception as e:
        print(f"❌ Error al listar usuarios: {e}")
    finally:
        session.close()


def main():
    """Main function to handle command line arguments."""
    print("\n" + "=" * 60)
    print("CAMBIAR CONTRASEÑA DE ADMINISTRADOR - SquidStats")
    print("=" * 60 + "\n")

    # Check for help flag
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help", "help"]:
        print("Uso:")
        print("  python3 change_password.py [username]")
        print("  python3 change_password.py --list")
        print("\nOpciones:")
        print("  username    Nombre del usuario (default: admin)")
        print("  --list, -l  Listar todos los usuarios")
        print("  --help, -h  Mostrar esta ayuda")
        print("\nEjemplos:")
        print("  python3 change_password.py")
        print("  python3 change_password.py admin")
        print("  python3 change_password.py miusuario")
        print("  python3 change_password.py --list")
        return

    # Check for list flag
    if len(sys.argv) > 1 and sys.argv[1] in ["-l", "--list", "list"]:
        list_users()
        return

    # Get username from arguments or use default
    if len(sys.argv) > 1:
        username = sys.argv[1].strip()
    else:
        username = input("Nombre de usuario (default: admin): ").strip() or "admin"

    # Get new password securely
    print(f"\nCambiando contraseña para: {username}")
    try:
        new_password = getpass("Nueva contraseña: ")
        if not new_password:
            print("❌ La contraseña no puede estar vacía")
            return

        confirm_password = getpass("Confirmar contraseña: ")

        if new_password != confirm_password:
            print("❌ Las contraseñas no coinciden")
            return

        if len(new_password) < 6:
            print(
                "⚠️  Advertencia: La contraseña es muy corta (mínimo recomendado: 8 caracteres)"
            )
            confirm = input("¿Continuar de todos modos? (s/N): ").strip().lower()
            if confirm != "s":
                print("Operación cancelada")
                return

    except KeyboardInterrupt:
        print("\n\nOperación cancelada por el usuario")
        return

    # Change password
    success = change_password(username, new_password)

    if success:
        print("\n✅ ¡Contraseña cambiada exitosamente!")
        print("   Ahora puedes iniciar sesión con:")
        print(f"   Usuario: {username}")
        print("   Contraseña: [la que acabas de establecer]")
    else:
        print("\n❌ No se pudo cambiar la contraseña")
        sys.exit(1)


if __name__ == "__main__":
    main()

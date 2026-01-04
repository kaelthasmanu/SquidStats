"""
Authentication Service Module
Handles JWT token generation, validation, and user authentication.
Follows security best practices for token-based authentication.
"""

import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

import bcrypt
import jwt
from flask import flash, redirect, request, session, url_for

from config import Config, logger
from database.database import AdminUser, get_session


class AuthConfig:
    """Authentication configuration constants."""

    # Token settings
    TOKEN_EXPIRY_HOURS = 24
    REMEMBER_ME_DAYS = 30
    ALGORITHM = "HS256"

    # Session settings
    SESSION_COOKIE_NAME = "squidstats_token"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.getenv("FLASK_ENV", "development") == "production"
    SESSION_COOKIE_SAMESITE = "Lax"

    # Security settings
    MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
    LOCKOUT_DURATION_MINUTES = int(os.getenv("LOCKOUT_DURATION_MINUTES", "15"))


class AuthService:
    """
    Service for handling authentication operations.
    Implements JWT-based authentication with security best practices.
    """

    # In-memory store for login attempts (in production, use Redis or database)
    _login_attempts: dict = {}

    @staticmethod
    def get_secret_key() -> str:
        """Get the JWT secret key from environment or app config."""
        return Config.JWT_SECRET_KEY

    @classmethod
    def hash_password_bcrypt(cls, password: str) -> tuple[str, str]:
        """
        Hash a password using bcrypt.
        Returns tuple of (hash, salt) - salt is included in bcrypt hash.
        """
        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(password.encode("utf-8"), salt)
        return password_hash.decode("utf-8"), salt.decode("utf-8")

    @classmethod
    def verify_password(cls, password: str, stored_hash: str, salt: str = None) -> bool:
        """Verify a password against a stored hash using bcrypt."""
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except Exception:
            # Fallback to old PBKDF2 method if needed
            if salt:
                computed_hash, _ = cls.hash_password(password, salt)
                return hmac.compare_digest(computed_hash, stored_hash)
            return False

    @classmethod
    def check_rate_limit(cls, identifier: str) -> tuple[bool, int]:
        """
        Check if the user is rate limited.
        Returns tuple of (is_allowed, remaining_attempts).
        """
        now = datetime.now(timezone.utc)

        if identifier in cls._login_attempts:
            attempts, lockout_until = cls._login_attempts[identifier]

            # Check if still locked out
            if lockout_until and now < lockout_until:
                remaining = (lockout_until - now).seconds // 60
                return False, remaining

            # Reset if lockout expired
            if lockout_until and now >= lockout_until:
                cls._login_attempts[identifier] = (0, None)
                attempts = 0

            remaining = AuthConfig.MAX_LOGIN_ATTEMPTS - attempts
            return remaining > 0, remaining

        return True, AuthConfig.MAX_LOGIN_ATTEMPTS

    @classmethod
    def record_failed_attempt(cls, identifier: str) -> None:
        """Record a failed login attempt."""
        now = datetime.now(timezone.utc)

        if identifier in cls._login_attempts:
            attempts, _ = cls._login_attempts[identifier]
            attempts += 1
        else:
            attempts = 1

        lockout_until = None
        if attempts >= AuthConfig.MAX_LOGIN_ATTEMPTS:
            lockout_until = now + timedelta(minutes=AuthConfig.LOCKOUT_DURATION_MINUTES)
            logger.warning(f"Account locked for {identifier} until {lockout_until}")

        cls._login_attempts[identifier] = (attempts, lockout_until)

    @classmethod
    def clear_failed_attempts(cls, identifier: str) -> None:
        """Clear failed login attempts for an identifier."""
        if identifier in cls._login_attempts:
            del cls._login_attempts[identifier]

    @classmethod
    def authenticate(cls, username: str, password: str) -> dict | None:
        """
        Authenticate user credentials against database.
        Returns user data dict on success, None on failure.
        """
        session = get_session()
        try:
            # Find user by username
            user = (
                session.query(AdminUser)
                .filter_by(username=username.lower(), is_active=1)
                .first()
            )

            if not user:
                return None

            # Verify password using bcrypt
            password_match = bcrypt.checkpw(
                password.encode("utf-8"), user.password_hash.encode("utf-8")
            )

            if password_match:
                # Update last login
                user.last_login = datetime.now(timezone.utc)
                session.commit()

                return {
                    "id": user.id,
                    "username": user.username,
                    "role": user.role,
                    "authenticated_at": datetime.now(timezone.utc).isoformat(),
                }

            return None

        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return None
        finally:
            session.close()

    @classmethod
    def generate_token(cls, user_data: dict, remember_me: bool = False) -> str:
        """
        Generate a JWT token for authenticated user.
        Includes security claims like expiration and issued-at times.
        Args:
            user_data: Dictionary containing user information
            remember_me: If True, token expires in REMEMBER_ME_DAYS, otherwise in TOKEN_EXPIRY_HOURS
        Returns:
            JWT token string
        """
        now = datetime.now(timezone.utc)

        # Set expiration based on remember_me flag
        if remember_me:
            expiration = now + timedelta(days=AuthConfig.REMEMBER_ME_DAYS)
            logger.info(
                f"Generating extended token for user: {user_data.get('username')} (expires in {AuthConfig.REMEMBER_ME_DAYS} days)"
            )
        else:
            expiration = now + timedelta(hours=AuthConfig.TOKEN_EXPIRY_HOURS)
            logger.info(
                f"Generating standard token for user: {user_data.get('username')} (expires in {AuthConfig.TOKEN_EXPIRY_HOURS} hours)"
            )

        payload = {
            # Standard JWT claims
            "iat": now,  # Issued at
            "exp": expiration,  # Expiration
            "nbf": now,  # Not valid before
            # Custom claims
            "sub": user_data.get("username"),  # Subject (username)
            "role": user_data.get("role", "user"),
            "jti": secrets.token_hex(16),  # JWT ID for token revocation
            "remember": remember_me,  # Track if this was a remember me session
        }

        token = jwt.encode(
            payload, cls.get_secret_key(), algorithm=AuthConfig.ALGORITHM
        )

        return token

    @classmethod
    def validate_token(cls, token: str) -> dict | None:
        """
        Validate a JWT token and return payload if valid.
        Returns None if token is invalid or expired.
        """
        try:
            payload = jwt.decode(
                token,
                cls.get_secret_key(),
                algorithms=[AuthConfig.ALGORITHM],
                options={
                    "require": ["exp", "iat", "sub"],
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_nbf": True,
                },
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return None

    @classmethod
    def get_current_user(cls) -> dict | None:
        """
        Get the current authenticated user from session or cookie.
        Returns user payload or None if not authenticated.
        """
        # Try to get token from session first
        token = session.get(AuthConfig.SESSION_COOKIE_NAME)

        # Fall back to cookie
        if not token:
            token = request.cookies.get(AuthConfig.SESSION_COOKIE_NAME)

        # Fall back to Authorization header (for API calls)
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if token:
            return cls.validate_token(token)

        return None

    @classmethod
    def is_authenticated(cls) -> bool:
        """Check if current request is from an authenticated user."""
        return cls.get_current_user() is not None

    @classmethod
    def update_user_password(cls, username: str, new_password: str) -> bool:
        """
        Update user password in the database.
        Returns True if successful, False otherwise.
        """
        session = get_session()
        try:
            user = session.query(AdminUser).filter_by(username=username).first()

            if not user:
                logger.error(f"User not found: {username}")
                return False

            # Hash the new password
            password_hash, salt = cls.hash_password_bcrypt(new_password)

            # Update user password
            user.password_hash = password_hash
            user.salt = salt
            session.commit()

            logger.info(f"Password updated successfully for user: {username}")
            return True

        except Exception as e:
            logger.error(f"Error updating password for {username}: {e}")
            session.rollback()
            return False
        finally:
            session.close()

    @classmethod
    def get_all_users(cls) -> list[dict]:
        """
        Get all admin users.
        Returns list of user dictionaries.
        """
        session = get_session()
        try:
            users = session.query(AdminUser).all()
            return [
                {
                    "id": user.id,
                    "username": user.username,
                    "role": user.role,
                    "is_active": user.is_active,
                    "last_login": user.last_login.isoformat()
                    if user.last_login
                    else None,
                    "created_at": user.created_at.isoformat(),
                    "updated_at": user.updated_at.isoformat(),
                }
                for user in users
            ]
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            return []
        finally:
            session.close()

    @classmethod
    def create_user(cls, username: str, password: str, role: str = "admin") -> bool:
        """
        Create a new admin user.
        Returns True if successful, False otherwise.
        """
        session = get_session()
        try:
            # Check if user already exists
            existing = (
                session.query(AdminUser).filter_by(username=username.lower()).first()
            )
            if existing:
                logger.error(f"User already exists: {username}")
                return False

            # Hash the password
            password_hash, salt = cls.hash_password_bcrypt(password)

            # Create new user
            new_user = AdminUser(
                username=username.lower(),
                password_hash=password_hash,
                salt=salt,
                role=role,
                is_active=1,
            )
            session.add(new_user)
            session.commit()

            logger.info(f"User created successfully: {username}")
            return True

        except Exception as e:
            logger.error(f"Error creating user {username}: {e}")
            session.rollback()
            return False
        finally:
            session.close()

    @classmethod
    def update_user(
        cls,
        user_id: int,
        username: str = None,
        password: str = None,
        role: str = None,
        is_active: int = None,
    ) -> bool:
        """
        Update an admin user.
        Returns True if successful, False otherwise.
        """
        session = get_session()
        try:
            user = session.query(AdminUser).filter_by(id=user_id).first()
            if not user:
                logger.error(f"User not found: {user_id}")
                return False

            if username is not None:
                # Check if username is taken by another user
                existing = (
                    session.query(AdminUser)
                    .filter(
                        AdminUser.username == username.lower(), AdminUser.id != user_id
                    )
                    .first()
                )
                if existing:
                    logger.error(f"Username already taken: {username}")
                    return False
                user.username = username.lower()

            if password is not None:
                password_hash, salt = cls.hash_password_bcrypt(password)
                user.password_hash = password_hash
                user.salt = salt

            if role is not None:
                user.role = role

            if is_active is not None:
                user.is_active = is_active

            session.commit()

            logger.info(f"User updated successfully: {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error updating user {user_id}: {e}")
            session.rollback()
            return False
        finally:
            session.close()

    @classmethod
    def delete_user(cls, user_id: int) -> bool:
        """
        Delete an admin user.
        Returns True if successful, False otherwise.
        Prevents deletion of the default admin user.
        """
        session = get_session()
        try:
            user = session.query(AdminUser).filter_by(id=user_id).first()
            if not user:
                logger.error(f"User not found: {user_id}")
                return False

            # Prevent deletion of admin user
            if user.username.lower() == "admin":
                logger.error("Cannot delete the default admin user")
                return False

            session.delete(user)
            session.commit()

            logger.info(f"User deleted successfully: {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error deleting user {user_id}: {e}")
            session.rollback()
            return False
        finally:
            session.close()


def login_required(f):
    """
    Decorator to protect routes that require authentication.
    Redirects to login page if user is not authenticated.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not AuthService.is_authenticated():
            flash("Por favor, inicia sesión para acceder a esta página.", "warning")
            # Store the original URL to redirect after login
            session["next_url"] = request.url
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """
    Decorator to protect routes that require admin role.
    Checks both authentication and admin role.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = AuthService.get_current_user()

        if not user:
            flash("Por favor, inicia sesión para acceder a esta página.", "warning")
            session["next_url"] = request.url
            return redirect(url_for("auth.login"))

        if user.get("role") != "admin":
            flash("No tienes permisos para acceder a esta página.", "error")
            return redirect(url_for("main.index"))

        return f(*args, **kwargs)

    return decorated_function


def api_auth_required(f):
    """
    Decorator for API endpoints that require authentication.
    Returns JSON error instead of redirect.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not AuthService.is_authenticated():
            return {"error": "Authentication required", "status": 401}, 401
        return f(*args, **kwargs)

    return decorated_function

"""
Authentication Routes Module
Handles login, logout, and session management endpoints.
"""

from datetime import timedelta

from flask import (
    Blueprint,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from config import logger
from services.auth_service import AuthConfig, AuthService

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Handle user login.
    GET: Display login form
    POST: Process login credentials
    """
    # If already authenticated, redirect to admin dashboard
    if AuthService.is_authenticated():
        return redirect(url_for("admin.admin_dashboard"))

    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = request.form.get("remember", False)

        # Get client identifier for rate limiting (IP address)
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if client_ip:
            client_ip = client_ip.split(",")[0].strip()

        # Check rate limiting
        is_allowed, remaining = AuthService.check_rate_limit(client_ip)

        if not is_allowed:
            error = f"Demasiados intentos fallidos. Intenta de nuevo en {remaining} minutos."
            logger.warning(f"Rate limited login attempt from {client_ip}")
        elif not username or not password:
            error = "Por favor, ingresa usuario y contraseña."
        else:
            # Attempt authentication
            user_data = AuthService.authenticate(username, password)

            if user_data:
                # Clear failed attempts on successful login
                AuthService.clear_failed_attempts(client_ip)

                # Generate JWT token
                token = AuthService.generate_token(user_data)

                # Store in session
                session[AuthConfig.SESSION_COOKIE_NAME] = token
                session["user"] = {
                    "username": user_data["username"],
                    "role": user_data["role"],
                }

                logger.info(
                    f"Successful login for user: {username} from IP: {client_ip}"
                )
                flash(f"¡Bienvenido, {username}!", "success")

                # Get redirect URL (stored before login redirect)
                next_url = session.pop("next_url", None)
                if next_url:
                    response = make_response(redirect(next_url))
                else:
                    response = make_response(redirect(url_for("admin.admin_dashboard")))

                # Set secure cookie with token
                max_age = timedelta(hours=AuthConfig.TOKEN_EXPIRY_HOURS).total_seconds()
                if remember:
                    max_age = timedelta(days=30).total_seconds()

                response.set_cookie(
                    AuthConfig.SESSION_COOKIE_NAME,
                    token,
                    max_age=int(max_age),
                    httponly=AuthConfig.SESSION_COOKIE_HTTPONLY,
                    secure=AuthConfig.SESSION_COOKIE_SECURE,
                    samesite=AuthConfig.SESSION_COOKIE_SAMESITE,
                )

                return response
            else:
                # Record failed attempt
                AuthService.record_failed_attempt(client_ip)
                error = "Usuario o contraseña incorrectos."
                logger.warning(
                    f"Failed login attempt for user: {username} from IP: {client_ip}"
                )

    return render_template("auth/login.html", error=error)


@auth_bp.route("/logout")
def logout():
    """
    Handle user logout.
    Clears session and removes authentication cookie.
    """
    username = session.get("user", {}).get("username", "Unknown")

    # Clear session
    session.pop(AuthConfig.SESSION_COOKIE_NAME, None)
    session.pop("user", None)
    session.clear()

    logger.info(f"User logged out: {username}")
    flash("Has cerrado sesión correctamente.", "success")

    # Create response and clear cookie
    response = make_response(redirect(url_for("auth.login")))
    response.delete_cookie(AuthConfig.SESSION_COOKIE_NAME)

    return response


@auth_bp.route("/check")
def check_auth():
    """
    API endpoint to check authentication status.
    Useful for AJAX calls to verify session validity.
    """
    user = AuthService.get_current_user()

    if user:
        return {
            "authenticated": True,
            "user": {"username": user.get("sub"), "role": user.get("role")},
        }

    return {"authenticated": False}, 401

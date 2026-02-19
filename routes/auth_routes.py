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
from flask_wtf.csrf import CSRFProtect
from loguru import logger

from services.auth_service import AuthConfig, AuthService

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
csrf = CSRFProtect()


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

                # Convert remember checkbox value to boolean
                remember_me = remember == "on"

                # Generate JWT token with appropriate expiration
                token = AuthService.generate_token(user_data, remember_me=remember_me)

                # Store in session
                session[AuthConfig.SESSION_COOKIE_NAME] = token
                session["user"] = {
                    "username": user_data["username"],
                    "role": user_data["role"],
                }
                session.permanent = (
                    remember_me  # Make session permanent if remember me is checked
                )

                # Log successful login with remember me status
                remember_status = (
                    "con sesión extendida" if remember_me else "sesión estándar"
                )
                logger.info(
                    f"Successful login for user: {username} from IP: {client_ip} ({remember_status})"
                )
                flash(f"¡Bienvenido, {username}!", "success")

                # Get redirect URL (stored before login redirect)
                next_url = session.pop("next_url", None)
                if next_url:
                    response = make_response(redirect(next_url))
                else:
                    response = make_response(redirect(url_for("admin.admin_dashboard")))

                # Set secure cookie with token
                # Use extended expiration if remember me is checked
                if remember_me:
                    max_age = timedelta(
                        days=AuthConfig.REMEMBER_ME_DAYS
                    ).total_seconds()
                else:
                    max_age = timedelta(
                        hours=AuthConfig.TOKEN_EXPIRY_HOURS
                    ).total_seconds()

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


@auth_bp.route("/reset-password", methods=["POST"])
@csrf.exempt
def reset_password():
    """
    Reset user password. Only accessible from localhost for security.
    Requires username and new_password in request body.

    Usage examples:
    curl -X POST http://localhost:5000/auth/reset-password \
      -H "Content-Type: application/json" \
      -d '{"username": "admin", "new_password": "newpassword123"}'
    """
    # Check if request is from localhost
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()

    # Allow only localhost connections
    if client_ip not in ["127.0.0.1", "::1", "localhost"]:
        logger.warning("Password reset attempt from unauthorized IP")
        return {
            "error": "Access denied. This endpoint is only accessible from localhost."
        }, 403

    # Get data from request
    data = request.get_json() if request.is_json else request.form
    username = data.get("username", "").strip()
    new_password = data.get("new_password", "")

    # Validate input
    if not username or not new_password:
        return {"error": "Username and new_password are required."}, 400

    if len(new_password) < 8:
        return {"error": "Password must be at least 8 characters long."}, 400

    # Update password
    success = AuthService.update_user_password(username, new_password)

    if success:
        logger.info(f"Password reset successful for user: {username} from localhost")
        # Do not reflect user input in the response to avoid XSS/vector reflection
        return {
            "success": True,
            "message": "Password updated successfully.",
        }, 200
    else:
        return {"error": "Failed to update password. User may not exist."}, 400

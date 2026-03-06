"""Admin user management routes."""

from flask import flash, redirect, render_template, request, url_for

from services.auth import user_service
from services.auth.auth_service import AuthService, admin_required

from .helpers import flash_and_redirect


def register_routes(bp):
    @bp.route("/users")
    @admin_required
    def manage_users():
        users = user_service.get_all_users()
        return render_template("admin/users.html", users=users)

    @bp.route("/users/create", methods=["GET", "POST"])
    @admin_required
    def create_user():
        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password")
            role = request.form.get("role", "admin")

            ok, message = user_service.create_user(username, password, role)
            flash(message, "success" if ok else "error")
            if ok:
                return redirect(url_for("admin.manage_users"))

        return render_template("admin/user_form.html", user=None, action="create")

    @bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_user(user_id):
        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password")
            role = request.form.get("role")
            is_active = 1 if request.form.get("is_active") else 0

            ok, message = user_service.update_user(
                user_id, username, password, role, is_active
            )
            flash(message, "success" if ok else "error")
            if ok:
                return redirect(url_for("admin.manage_users"))

        users = AuthService.get_all_users()
        user = next((u for u in users if u["id"] == user_id), None)
        if not user:
            flash("Usuario no encontrado", "error")
            return redirect(url_for("admin.manage_users"))

        return render_template("admin/user_form.html", user=user, action="edit")

    @bp.route("/users/<int:user_id>/delete", methods=["POST"])
    @admin_required
    def delete_user(user_id):
        ok, message = user_service.delete_user(user_id)
        return flash_and_redirect(ok, message, "admin.manage_users")

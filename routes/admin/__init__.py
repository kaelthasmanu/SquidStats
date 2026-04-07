"""
Admin blueprint package.

Splits the admin area into domain-specific modules while keeping
a single ``admin`` blueprint so all ``url_for('admin.xxx')`` references
in templates and redirects continue to work unchanged.
"""

from flask import Blueprint

from . import (
    acls,
    backup,
    blacklist,
    dashboard,
    database,
    delay_pools,
    http_access,
    logs,
    quota,
    squid_config,
    system_api,
    users,
)

admin_bp = Blueprint("admin", __name__)

# Register routes from each sub-module onto the shared blueprint.
dashboard.register_routes(admin_bp)
users.register_routes(admin_bp)
blacklist.register_routes(admin_bp)
squid_config.register_routes(admin_bp)
acls.register_routes(admin_bp)
http_access.register_routes(admin_bp)
delay_pools.register_routes(admin_bp)
quota.register_routes(admin_bp)
logs.register_routes(admin_bp)
backup.register_routes(admin_bp)
database.register_routes(admin_bp)
system_api.register_routes(admin_bp)

"""
Tests for services layer — auth, user, quota logic.
"""

import secrets
from unittest.mock import patch

from database.models.models import QuotaGroup, QuotaUser


class TestAuthService:
    """Test AuthService password hashing and token logic."""

    def test_hash_password_bcrypt_returns_tuple(self):
        from services.auth.auth_service import AuthService

        pw_hash, salt = AuthService.hash_password_bcrypt("testpassword123")
        assert isinstance(pw_hash, str)
        assert isinstance(salt, str)
        assert len(pw_hash) > 0
        assert len(salt) > 0

    def test_hash_password_bcrypt_different_salts(self):
        from services.auth.auth_service import AuthService

        h1, s1 = AuthService.hash_password_bcrypt("samepassword")
        h2, s2 = AuthService.hash_password_bcrypt("samepassword")
        # Different salts should produce different hashes
        assert s1 != s2

    def test_verify_password(self):
        from services.auth.auth_service import AuthService

        pw_hash, salt = AuthService.hash_password_bcrypt("mypassword")
        assert AuthService.verify_password("mypassword", pw_hash, salt) is True
        assert AuthService.verify_password("wrongpassword", pw_hash, salt) is False

    def test_generate_token(self):
        from services.auth.auth_service import AuthService

        secret_key = secrets.token_urlsafe(32)
        with patch("services.auth.auth_service.Config") as mock_config:
            mock_config.JWT_SECRET_KEY = secret_key
            user_data = {"id": 1, "username": "admin", "role": "admin"}
            token = AuthService.generate_token(user_data)
            assert isinstance(token, str)
            assert len(token) > 0

    def test_verify_token_roundtrip(self):
        from services.auth.auth_service import AuthService

        secret_key = secrets.token_urlsafe(32)
        with patch("services.auth.auth_service.Config") as mock_config:
            mock_config.JWT_SECRET_KEY = secret_key
            user_data = {"id": 42, "username": "testuser", "role": "admin"}
            token = AuthService.generate_token(user_data)
            payload = AuthService.validate_token(token)
            assert payload is not None
            assert payload["sub"] == "testuser"
            assert payload["role"] == "admin"


class TestUserService:
    """Test user_service functions."""

    def test_create_user_empty_username(self):
        from services.auth.user_service import create_user

        ok, msg = create_user("", "password123")
        assert ok is False
        assert "obligatorios" in msg.lower() or "obligatorios" in msg

    def test_create_user_short_password(self):
        from services.auth.user_service import create_user

        ok, msg = create_user("admin", "123")
        assert ok is False
        assert "8 caracteres" in msg

    def test_update_user_short_password(self):
        from services.auth.user_service import update_user

        ok, msg = update_user(1, "admin", "123", "admin", 1)
        assert ok is False
        assert "8 caracteres" in msg


class TestQuotaModels:
    """Test quota-related DB operations."""

    def test_quota_user_exceeds_limit(self, db_session):
        user = QuotaUser(username="heavy_user", quota_mb=1024, used_mb=2048)
        db_session.add(user)
        db_session.commit()

        result = db_session.query(QuotaUser).first()
        assert result.used_mb > result.quota_mb

    def test_group_quota_tracking(self, db_session):
        group = QuotaGroup(group_name="marketing", quota_mb=5120)
        db_session.add(group)

        users = [
            QuotaUser(username="u1", group_name="marketing", quota_mb=0, used_mb=1000),
            QuotaUser(username="u2", group_name="marketing", quota_mb=0, used_mb=2000),
            QuotaUser(username="u3", group_name="marketing", quota_mb=0, used_mb=3000),
        ]
        db_session.add_all(users)
        db_session.commit()

        total_usage = sum(
            u.used_mb
            for u in db_session.query(QuotaUser).filter_by(group_name="marketing").all()
        )
        assert total_usage == 6000
        assert total_usage > group.quota_mb  # Group exceeded


class TestLogsService:
    """Test logs service output cleaning and fallback behavior."""

    def test_read_logs_strips_ansi_sequences(self, tmp_path):
        from services.system.logs_service import read_logs

        log_file = tmp_path / "app.log"
        log_file.write_text("\x1b[32mINFO\x1b[0m: Test log line\n")

        result = read_logs([str(log_file)], max_lines=10, debug=True)

        assert "app.log" in result
        assert result["app.log"] == ["INFO: Test log line"]

    def test_read_logs_file_not_found(self):
        from services.system.logs_service import read_logs

        result = read_logs(["/no/such/file.log"], max_lines=10, debug=True)
        assert "/no/such/file.log" not in result  # key is basename
        assert result.get("file.log") == ["Log file not found"]

"""Unit tests for LDAP service helpers."""

import pytest

from services.ldap import ldap_service


class TestLdapServiceFilterEscaping:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("john.doe", "john.doe"),
            ("test*user", "test\\2auser"),
            ("foo(bar)", "foo\\28bar\\29"),
            ("cn=admin", "cn=admin"),
            ("\\\\evil\\", "\\5c\\5cevil\\5c"),
        ],
    )
    def test_escape_ldap_filter_value(self, value, expected):
        assert ldap_service._escape_ldap_filter_value(value) == expected


def test_kerberos_connection_uses_sasl_gssapi(monkeypatch):
    captured = {}

    def fake_connection(server, **kwargs):
        captured["server"] = server
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(ldap_service, "_make_server", lambda *_args: "server")
    monkeypatch.setattr(ldap_service, "Connection", fake_connection)
    monkeypatch.setattr(ldap_service, "_require_kerberos_client", lambda: None)

    connection = ldap_service._connect(
        {
            "host": "dc.example.test",
            "port": 389,
            "use_ssl": False,
            "auth_type": "KERBEROS",
            "bind_dn": "squidstats@example.test",
            "bind_password": "unused-password",
        }
    )

    assert connection is not None
    assert captured == {
        "server": "server",
        "user": "squidstats@example.test",
        "authentication": ldap_service.SASL,
        "sasl_mechanism": ldap_service.KERBEROS,
        "auto_bind": True,
        "raise_exceptions": True,
    }


def test_kerberos_connection_reports_missing_gssapi_client(monkeypatch):
    def raise_missing_kerberos_client():
        raise ldap_service.KerberosClientUnavailableError()

    monkeypatch.setattr(ldap_service, "_make_server", lambda *_args: "server")
    monkeypatch.setattr(
        ldap_service,
        "_require_kerberos_client",
        raise_missing_kerberos_client,
    )

    result = ldap_service.test_connection(
        {
            "host": "dc.example.test",
            "port": 389,
            "use_ssl": False,
            "auth_type": "KERBEROS",
        }
    )

    assert result == {
        "status": "error",
        "message": "LDAP_ERROR_KERBEROS_CLIENT_UNAVAILABLE",
    }


def test_kerberos_connection_reports_missing_credentials(monkeypatch):
    def raise_missing_credentials(_cfg):
        raise ldap_service.KerberosCredentialsUnavailableError()

    monkeypatch.setattr(ldap_service, "_connect", raise_missing_credentials)

    result = ldap_service.test_connection({"host": "dc.example.test"})

    assert result == {
        "status": "error",
        "message": "No hay credenciales Kerberos disponibles. Obtenga un ticket con kinit y vuelva a intentarlo.",
    }


def test_identifies_unknown_kerberos_service_principal():
    cause = RuntimeError("Server not found in Kerberos database")
    error = ldap_service.core.exceptions.LDAPOperationsErrorResult(
        result=1,
        description="operationsError",
        dn="",
        message="SASL: Failed to start authentication system",
    )
    error.__cause__ = cause

    assert ldap_service._is_missing_kerberos_service_principal(error)


def test_connection_reports_unreachable_ldap_server(monkeypatch):
    def raise_socket_error(_cfg):
        raise ldap_service.core.exceptions.LDAPSocketOpenError("invalid server address")

    monkeypatch.setattr(ldap_service, "_connect", raise_socket_error)

    result = ldap_service.test_connection({"host": "dc.example.test"})

    assert result == {
        "status": "error",
        "message": "No se pudo resolver o conectar con el servidor LDAP configurado: dc.example.test.",
    }

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

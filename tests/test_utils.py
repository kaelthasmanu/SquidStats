"""
Tests for utility modules (utils/).
"""

import pytest

from utils.colors import color_map
from utils.filters import divide_filter, format_bytes_filter, strftime_filter
from utils.size import size_to_bytes
from utils.social_media import SOCIAL_MEDIA_DOMAINS

# ── utils/size.py ────────────────────────────────────────────────────────

class TestSizeToBytes:
    @pytest.mark.parametrize(
        "input_str, expected",
        [
            ("1 B", 1),
            ("1 KB", 1024),
            ("1 MB", 1024**2),
            ("1 GB", 1024**3),
            ("1 TB", 1024**4),
            ("2.5 MB", int(2.5 * 1024**2)),
            ("0 B", 0),
        ],
    )
    def test_valid_sizes(self, input_str, expected):
        assert size_to_bytes(input_str) == expected

    def test_empty_string(self):
        assert size_to_bytes("") == 0

    def test_none(self):
        assert size_to_bytes(None) == 0

    def test_no_unit(self):
        assert size_to_bytes("1024") == 0  # no space-separated unit

    def test_unknown_unit(self):
        assert size_to_bytes("1 PB") == 1  # multiplier defaults to 1


# ── utils/filters.py ────────────────────────────────────────────────────

class TestDivideFilter:
    def test_normal_division(self):
        assert divide_filter(10, 3) == 3.33

    def test_division_by_zero(self):
        assert divide_filter(10, 0) == 0.0

    def test_non_numeric(self):
        assert divide_filter("abc", 2) == 0.0

    def test_precision(self):
        assert divide_filter(1, 3, precision=4) == 0.3333


class TestFormatBytesFilter:
    def test_bytes(self):
        assert format_bytes_filter(500) == "500 bytes"

    def test_kilobytes(self):
        result = format_bytes_filter(2048)
        assert "KB" in result

    def test_megabytes(self):
        result = format_bytes_filter(2 * 1024**2)
        assert "MB" in result

    def test_gigabytes(self):
        result = format_bytes_filter(3 * 1024**3)
        assert "GB" in result

    def test_zero(self):
        assert format_bytes_filter(0) == "0 bytes"

    def test_invalid_value(self):
        assert format_bytes_filter("not_a_number") == "0 bytes"


class TestStrftimeFilter:
    def test_none_returns_nunca(self):
        assert strftime_filter(None) == "Nunca"

    def test_datetime_object(self):
        from datetime import datetime

        dt = datetime(2025, 1, 15, 10, 30, 0)
        result = strftime_filter(dt)
        assert "2025" in result
        assert "10:30" in result

    def test_iso_string(self):
        result = strftime_filter("2025-06-15T14:00:00")
        assert "2025" in result


# ── utils/colors.py ──────────────────────────────────────────────────────

class TestColorMap:
    def test_known_codes(self):
        assert "200" in color_map
        assert "404" in color_map
        assert "503" in color_map
        assert "Otros" in color_map

    def test_values_are_hex_colors(self):
        for code, color in color_map.items():
            assert color.startswith("#"), f"Color for {code} should be hex"
            assert len(color) == 7, f"Color for {code} should be #RRGGBB"


# ── utils/social_media.py ───────────────────────────────────────────────

class TestSocialMediaDomains:
    def test_has_major_platforms(self):
        assert "YouTube" in SOCIAL_MEDIA_DOMAINS
        assert "Facebook" in SOCIAL_MEDIA_DOMAINS
        assert "Instagram" in SOCIAL_MEDIA_DOMAINS
        assert "Twitter/X" in SOCIAL_MEDIA_DOMAINS
        assert "WhatsApp" in SOCIAL_MEDIA_DOMAINS
        assert "Telegram" in SOCIAL_MEDIA_DOMAINS

    def test_each_platform_has_domains(self):
        for platform, domains in SOCIAL_MEDIA_DOMAINS.items():
            assert isinstance(domains, list)
            assert len(domains) > 0, f"{platform} should have at least one domain"

    def test_domains_are_lowercase(self):
        for platform, domains in SOCIAL_MEDIA_DOMAINS.items():
            for domain in domains:
                assert domain == domain.lower(), f"{domain} in {platform} should be lowercase"

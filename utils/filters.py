import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def divide_filter(numerator, denominator, precision=2):
    try:
        num = float(numerator)
        den = float(denominator)
        if den == 0:
            logger.warning("Division by zero attempt in template")
            return 0.0
        return round(num / den, precision)
    except (TypeError, ValueError) as e:
        logger.error(f"Error in divide filter: {str(e)}")
        return 0.0


def format_bytes_filter(value):
    try:
        value = int(value)
        if value >= 1024**3:  # GB
            return f"{(value / (1024**3)):.2f} GB"
        elif value >= 1024**2:  # MB
            return f"{(value / (1024**2)):.2f} MB"
        elif value >= 1024:  # KB
            return f"{(value / 1024):.2f} KB"
        return f"{value} bytes"
    except (TypeError, ValueError) as e:
        logger.error(f"Error in format_bytes filter: {str(e)}")
        return "0 bytes"


def strftime_filter(value, format_string="%Y-%m-%d %H:%M:%S"):
    if not value:
        return "Nunca"
    try:
        if isinstance(value, str):
            # If it's already a string, assume it's ISO format
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            dt = value
        return dt.strftime(format_string)
    except (ValueError, AttributeError) as e:
        logger.error(f"Error in strftime filter: {str(e)}")
        return str(value)


def register_filters(app):
    app.template_filter("divide")(divide_filter)
    app.template_filter("format_bytes")(format_bytes_filter)
    app.template_filter("strftime")(strftime_filter)

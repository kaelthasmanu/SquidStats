import logging

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


def register_filters(app):
    app.template_filter("divide")(divide_filter)
    app.template_filter("format_bytes")(format_bytes_filter)

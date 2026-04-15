#!/usr/bin/env python3
"""Mark user-facing strings in Python files with _() for Flask-Babel."""

import re
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories to process
DIRS = ["routes", "services"]

# Keys whose string values should be translated in dict literals
TRANSLATABLE_KEYS = {
    "message", "error", "msg", "error_message", "user_message",
}

IMPORT_LINE = "from flask_babel import gettext as _"


def should_skip_file(filepath):
    """Skip certain files."""
    basename = os.path.basename(filepath)
    if basename == "__init__.py":
        return True
    if basename == "i18n_routes.py":
        return True
    return False


def has_gettext_import(content):
    """Check if file already imports gettext as _."""
    return bool(re.search(r'from flask_babel import.*gettext', content))


def add_import(content):
    """Add flask_babel import to file."""
    if has_gettext_import(content):
        return content

    lines = content.split('\n')
    insert_idx = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('from ') or stripped.startswith('import '):
            insert_idx = i + 1

    lines.insert(insert_idx, IMPORT_LINE)
    return '\n'.join(lines)


def is_translatable(text):
    """Check if a string value should be translated."""
    if not text or len(text.strip()) <= 1:
        return False
    if text.lower() in ('true', 'false', 'none', 'null', 'ok'):
        return False
    # Must have a letter
    if not re.search(r'[a-zA-ZáéíóúñÁÉÍÓÚÑüÜ]', text):
        return False
    # Skip URLs, paths
    if re.match(r'^(https?://|/|\.)', text):
        return False
    return True


def wrap_flash_strings(content):
    """Wrap literal string arguments in flash() calls."""
    # flash("...", ...) → flash(_("..."), ...)
    # Don't match f-strings or already wrapped

    def replace_flash_dq(m):
        pre = m.group(1)
        text = m.group(2)
        post = m.group(3)
        if not is_translatable(text):
            return m.group(0)
        return f'{pre}_("{text}"){post}'

    # Double-quoted: flash("text", ...) or flash("text")
    content = re.sub(
        r'(flash\()"((?:[^"\\]|\\.)+)"(\s*[,\)])',
        replace_flash_dq,
        content
    )

    def replace_flash_sq(m):
        pre = m.group(1)
        text = m.group(2)
        post = m.group(3)
        if not is_translatable(text):
            return m.group(0)
        escaped = text.replace('"', '\\"')
        return f'{pre}_("{escaped}"){post}'

    # Single-quoted: flash('text', ...)
    content = re.sub(
        r"(flash\()'((?:[^'\\]|\\.)+)'(\s*[,\)])",
        replace_flash_sq,
        content
    )

    return content


def wrap_dict_strings(content):
    """Wrap string values for translatable dict keys."""
    for key in TRANSLATABLE_KEYS:
        # "key": "value" → "key": _("value")
        pattern = rf'("{key}":\s*)"((?:[^"\\]|\\.)+)"'

        def make_replacer():
            def replacer(m):
                prefix = m.group(1)
                value = m.group(2)
                if not is_translatable(value):
                    return m.group(0)
                return f'{prefix}_("{value}")'
            return replacer

        content = re.sub(pattern, make_replacer(), content)

        # 'key': 'value' patterns
        pattern_sq = rf"('{key}':\s*)'((?:[^'\\]|\\.)+)'"

        def make_replacer_sq():
            def replacer_sq(m):
                prefix = m.group(1)
                value = m.group(2)
                if not is_translatable(value):
                    return m.group(0)
                escaped = value.replace('"', '\\"')
                return f'{prefix}_("{escaped}")'
            return replacer_sq

        content = re.sub(pattern_sq, make_replacer_sq(), content)

    return content


def wrap_return_dict_strings(content):
    """Wrap string values in return {"error": "..."} patterns."""
    # Handles return {"error": "text"} and return {"error": "text", ...}
    for key in ["error", "success", "message"]:
        pattern = rf'(\{{\s*"{key}":\s*)"((?:[^"\\]|\\.)+)"'

        def make_replacer(k=key):
            def replacer(m):
                prefix = m.group(1)
                value = m.group(2)
                if not is_translatable(value):
                    return m.group(0)
                return f'{prefix}_("{value}")'
            return replacer

        content = re.sub(pattern, make_replacer(), content)

    return content


def process_file(filepath):
    """Process a single Python file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Skip if already has _() calls throughout (likely already processed)
    original = content

    content = wrap_flash_strings(content)
    content = wrap_dict_strings(content)
    content = wrap_return_dict_strings(content)

    if content != original:
        content = add_import(content)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False


def main():
    print("=" * 60)
    print("SquidStats Python i18n Marker")
    print("=" * 60)

    target = sys.argv[1] if len(sys.argv) > 1 else None

    if target:
        filepath = os.path.join(PROJECT_ROOT, target)
        if not os.path.exists(filepath):
            filepath = target
        if os.path.exists(filepath):
            if process_file(filepath):
                print(f"✓ Modified: {target}")
            else:
                print(f"- No changes: {target}")
        else:
            print(f"File not found: {filepath}")
        return

    count = 0
    for dir_name in DIRS:
        dir_path = os.path.join(PROJECT_ROOT, dir_name)
        for root, dirs, files in os.walk(dir_path):
            for f in sorted(files):
                if not f.endswith('.py'):
                    continue
                filepath = os.path.join(root, f)
                if should_skip_file(filepath):
                    continue
                relpath = os.path.relpath(filepath, PROJECT_ROOT)
                if process_file(filepath):
                    print(f"  ✓ {relpath}")
                    count += 1
                else:
                    print(f"  - {relpath} (no changes)")

    print(f"\nModified {count} Python files")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Automated i18n string marker for SquidStats templates and Python files.
Wraps Spanish user-facing text with {{ _("...") }} in templates
and _("...") in Python files.
"""

import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")


def process_template_file(filepath):
    """Process a single Jinja2 template file and wrap Spanish text."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content

    # ─── Pattern: plain text inside HTML tags (not already wrapped) ───
    # Match: >Spanish text< but NOT >{{ ... }}< or >{% ... %}<
    # This regex finds text content between > and < that contains Spanish chars
    def wrap_text_node(m):
        prefix = m.group(1)  # the >
        text = m.group(2)
        suffix = m.group(3)  # the <

        stripped = text.strip()
        if not stripped:
            return m.group(0)

        # Skip if already wrapped
        if "{{" in stripped or "{%" in stripped:
            return m.group(0)

        # Skip if it's just numbers, punctuation, or variable refs
        if re.match(r'^[\d\s\.\,\;\:\-\+\*/=<>!@#$%^&()\[\]{}|\\/"\'`~]+$', stripped):
            return m.group(0)

        # Skip very short strings (1-2 chars) that are likely formatting
        if len(stripped) <= 1:
            return m.group(0)

        # Skip if it looks like a CSS class, URL, or code
        if stripped.startswith(("http", "www.", "/", "#", ".", "fas ", "fab ", "far ")):
            return m.group(0)

        # Must contain at least one letter
        if not re.search(r'[a-zA-ZáéíóúñÁÉÍÓÚÑüÜ]', stripped):
            return m.group(0)

        # Preserve whitespace around the text
        leading_ws = text[:len(text) - len(text.lstrip())]
        trailing_ws = text[len(text.rstrip()):]

        # Escape any quotes in the text
        escaped = stripped.replace('"', '\\"')

        return f'{prefix}{leading_ws}{{{{ _("{escaped}") }}}}{trailing_ws}{suffix}'

    # Process text between HTML tags
    content = re.sub(
        r'(>)((?:(?!<|{{|{%).)+?)(<)',
        wrap_text_node,
        content,
        flags=re.DOTALL
    )

    # ─── Pattern: HTML attributes with Spanish text ───
    # Common attributes: placeholder, title, data-tooltip, aria-label, alt
    attrs_to_translate = [
        'placeholder', 'title', 'data-tooltip', 'aria-label', 'alt',
        'data-confirm', 'data-message', 'data-title'
    ]

    for attr in attrs_to_translate:
        def wrap_attr(m):
            quote = m.group(2)
            value = m.group(3)
            if '{{' in value or '{%' in value:
                return m.group(0)
            if not re.search(r'[a-zA-ZáéíóúñÁÉÍÓÚÑüÜ]', value):
                return m.group(0)
            if value.startswith(("http", "www.", "/", "#", ".", "fas ", "url_for")):
                return m.group(0)
            if len(value.strip()) <= 1:
                return m.group(0)
            escaped = value.replace('"', '\\"').replace("'", "\\'")
            return f'{m.group(1)}"{{% raw %}}{{{{ _("{escaped}") }}}}{{% endraw %}}"'

        # Match attr="value" where value contains text
        pattern = rf'({attr}=)(["\'])((?:(?!\2).)*?)\2'
        # Simpler approach - just use {{ _() }} in attribute values
        def wrap_attr_simple(m):
            attr_name = m.group(1)
            quote_char = m.group(2)
            value = m.group(3)
            if '{{' in value or '{%' in value or '_(' in value:
                return m.group(0)
            if not re.search(r'[a-zA-ZáéíóúñÁÉÍÓÚÑüÜ]', value):
                return m.group(0)
            if value.startswith(("http", "www.", "/", "#", ".", "fas ", "url_for")):
                return m.group(0)
            stripped = value.strip()
            if len(stripped) <= 1:
                return m.group(0)
            escaped = stripped.replace('"', '\\"')
            # Use {{ _() }} with the attribute
            return f'{attr_name}"{{{{ _("{escaped}") }}}}"'

        content = re.sub(pattern, wrap_attr_simple, content)

    if content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    return False


def process_python_file(filepath):
    """Process a Python file and wrap user-facing strings with _()."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content

    # Add import if _() is going to be used and not already imported
    needs_import = False

    # Pattern: "message": "Spanish text" in dict returns
    def wrap_message_value(m):
        nonlocal needs_import
        key = m.group(1)
        quote = m.group(2)
        value = m.group(3)

        if '_(' in value or 'f"' in value or "f'" in value:
            return m.group(0)
        if not re.search(r'[a-zA-ZáéíóúñÁÉÍÓÚÑüÜ]', value):
            return m.group(0)
        if value.startswith(("http", "/", ".")):
            return m.group(0)

        needs_import = True
        escaped = value.replace('"', '\\"')
        return f'"{key}": _("{escaped}")'

    # Wrap "message": "text" patterns
    content = re.sub(
        r'"(message|status_message|error)":\s*(["\'])((?:(?!\2).)*?)\2',
        wrap_message_value,
        content
    )

    # Pattern: flash("Spanish text", ...) 
    def wrap_flash(m):
        nonlocal needs_import
        prefix = m.group(1)
        value = m.group(2)
        suffix = m.group(3)
        if '_(' in value:
            return m.group(0)
        needs_import = True
        escaped = value.replace('"', '\\"')
        return f'{prefix}_("{escaped}"){suffix}'

    content = re.sub(
        r'(flash\()"([^"]+)"(\s*[,)])',
        wrap_flash,
        content
    )

    if content != original:
        # Add import if needed
        if needs_import and 'from flask_babel import' not in content:
            # Find the best place to add import
            if 'from flask import' in content:
                content = content.replace(
                    'from flask import',
                    'from flask_babel import gettext as _\nfrom flask import',
                    1
                )
            else:
                content = 'from flask_babel import gettext as _\n' + content

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    return False


def main():
    print("=" * 60)
    print("SquidStats i18n String Marker")
    print("=" * 60)

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode in ("all", "templates"):
        print("\n📄 Processing templates...")
        template_count = 0
        for root, dirs, files in os.walk(TEMPLATES_DIR):
            for f in sorted(files):
                if f.endswith(".html"):
                    filepath = os.path.join(root, f)
                    relpath = os.path.relpath(filepath, PROJECT_ROOT)
                    if process_template_file(filepath):
                        print(f"  ✓ {relpath}")
                        template_count += 1
                    else:
                        print(f"  - {relpath} (no changes)")
        print(f"\n  Templates modified: {template_count}")

    if mode in ("all", "python"):
        print("\n🐍 Processing Python files...")
        python_dirs = ["routes", "services"]
        py_count = 0
        for pdir in python_dirs:
            full_dir = os.path.join(PROJECT_ROOT, pdir)
            for root, dirs, files in os.walk(full_dir):
                for f in sorted(files):
                    if f.endswith(".py"):
                        filepath = os.path.join(root, f)
                        relpath = os.path.relpath(filepath, PROJECT_ROOT)
                        if process_python_file(filepath):
                            print(f"  ✓ {relpath}")
                            py_count += 1
                        else:
                            print(f"  - {relpath} (no changes)")
        print(f"\n  Python files modified: {py_count}")

    print("\n✅ Done! Next steps:")
    print("  1. Review changes manually")
    print("  2. Run: pybabel extract -F babel.cfg -o translations/messages.pot .")
    print("  3. Run: pybabel init -i translations/messages.pot -d translations -l en")
    print("  4. Edit translations/en/LC_MESSAGES/messages.po")
    print("  5. Run: pybabel compile -d translations")


if __name__ == "__main__":
    main()

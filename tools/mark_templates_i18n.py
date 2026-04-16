#!/usr/bin/env python3
"""
Targeted i18n marker for SquidStats Jinja2 templates.
Wraps visible text content with {{ _("...") }}.
Conservative approach - only marks clear text nodes.
"""

import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")

# Attributes that contain user-visible text
TRANSLATABLE_ATTRS = {
    "placeholder",
    "title",
    "data-tooltip",
    "aria-label",
    "alt",
    "data-confirm",
    "data-confirm-title",
    "data-confirm-text",
}

# Strings to skip (technical, not user-facing)
SKIP_PATTERNS = {
    "true",
    "false",
    "none",
    "null",
    "utf-8",
    "UTF-8",
    "POST",
    "GET",
    "PUT",
    "DELETE",
    "PATCH",
    "text/html",
    "application/json",
    "multipart/form-data",
    "hidden",
    "submit",
    "button",
    "text",
    "password",
    "email",
    "number",
    "checkbox",
    "display: none",
    "visibility: hidden",
}


def is_translatable_text(text):
    """Check if a text string should be translated."""
    stripped = text.strip()
    if not stripped or len(stripped) <= 1:
        return False
    # Already has Jinja2 syntax
    if "{{" in stripped or "{%" in stripped or "_(" in stripped:
        return False
    # Skip technical strings
    if stripped.lower() in SKIP_PATTERNS:
        return False
    # Must contain a letter (not just numbers/symbols)
    if not re.search(r"[a-zA-ZáéíóúñÁÉÍÓÚÑüÜàèìòùÀÈÌÒÙ]", stripped):
        return False
    # Skip URLs, paths, CSS classes, etc.
    if re.match(
        r"^(https?://|www\.|/|#|\.|fas |fab |far |fal |fad |fa-|bi-|text-|bg-|btn-|col-|row-|d-|p-|m-|w-|h-|flex-|grid-|items-|justify-)",
        stripped,
    ):
        return False
    # Skip if it looks like a Jinja variable or filter
    if re.match(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$", stripped):
        return False
    # Skip JS code snippets
    if any(
        kw in stripped
        for kw in [
            "function(",
            "var ",
            "const ",
            "let ",
            "=>",
            "return ",
            "console.",
            "document.",
            "window.",
            "addEventListener",
        ]
    ):
        return False
    return True


def wrap_text(text):
    """Wrap a text string with {{ _("...") }}."""
    stripped = text.strip()
    # Normalize multi-line whitespace to single line
    stripped = " ".join(stripped.split())
    leading = text[: len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()) :]
    # Escape double quotes
    escaped = stripped.replace('"', '\\"')
    return f'{leading}{{{{ _("{escaped}") }}}}{trailing}'


def process_text_between_tags(content):
    """Process text nodes between HTML tags."""
    result = []
    pos = 0

    while pos < len(content):
        # Find next tag or Jinja block
        tag_match = re.search(
            r"(<[^>]+>|{{.*?}}|{%.*?%}|{#.*?#})", content[pos:], re.DOTALL
        )

        if not tag_match:
            # Rest is text
            remaining = content[pos:]
            if is_translatable_text(remaining):
                result.append(wrap_text(remaining))
            else:
                result.append(remaining)
            break

        # Text before the tag
        text_before = content[pos : pos + tag_match.start()]
        if text_before and is_translatable_text(text_before):
            result.append(wrap_text(text_before))
        else:
            result.append(text_before)

        # The tag/block itself
        tag = tag_match.group(0)

        # Check if it's a script or style tag - skip content
        script_match = re.match(r"<(script|style)[\s>]", tag, re.IGNORECASE)
        if script_match:
            tag_name = script_match.group(1).lower()
            close_pattern = f"</{tag_name}>"
            close_pos = content.find(close_pattern, pos + tag_match.end())
            if close_pos >= 0:
                # Include everything from tag to closing tag
                result.append(
                    content[pos + tag_match.start() : close_pos + len(close_pattern)]
                )
                pos = close_pos + len(close_pattern)
                continue

        # Process translatable attributes in the tag
        if tag.startswith("<"):
            tag = process_tag_attributes(tag)

        result.append(tag)
        pos = pos + tag_match.end()

    return "".join(result)


def process_tag_attributes(tag):
    """Process translatable attributes in an HTML tag."""
    for attr in TRANSLATABLE_ATTRS:
        # Match attr="value" or attr='value'
        pattern = rf'({attr}=")([^"]*?)(")'

        def replace_attr(m):
            prefix = m.group(1)
            value = m.group(2)
            suffix = m.group(3)
            if is_translatable_text(value):
                escaped = value.strip().replace('"', '\\"')
                return f'{prefix}{{{{ _("{escaped}") }}}}{suffix}'
            return m.group(0)

        tag = re.sub(pattern, replace_attr, tag)

        # Single quotes version
        pattern_sq = rf"({attr}=')([^']*?)(')"

        def replace_attr_sq(m, attr=attr):
            value = m.group(2)
            if is_translatable_text(value):
                escaped = value.strip().replace("'", "\\'")
                return f"""{attr}="{{ _("{escaped}") }}" """
            return m.group(0)

        tag = re.sub(pattern_sq, replace_attr_sq, tag)

    return tag


def process_template(filepath):
    """Process a single template file."""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    original = content
    new_content = process_text_between_tags(content)

    if new_content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    return False


def process_line(line):
    """Process a single line of template content."""
    # Don't process Jinja2 comments
    if "{#" in line:
        return line

    # Don't process lines that are just whitespace
    if not line.strip():
        return line

    # Process text content between tags on this line
    # Pattern: find segments of text that are between > and <
    def replace_text_segment(m):
        before = m.group(1)  # > or start
        text = m.group(2)  # text content
        after = m.group(3)  # < or end

        if is_translatable_text(text):
            return before + wrap_text(text) + after
        return m.group(0)

    # Find text between > and < (tag content)
    result = re.sub(r"(>)([^<>{%{}]+?)(<)", replace_text_segment, line)

    # Process translatable attributes
    for attr in TRANSLATABLE_ATTRS:
        pattern = rf'({attr}=")([^"{{}}]*?)(")'

        def attr_replacer(m):
            prefix = m.group(1)
            value = m.group(2)
            suffix = m.group(3)
            if is_translatable_text(value):
                escaped = value.strip().replace('"', '\\"')
                return f'{prefix}{{{{ _("{escaped}") }}}}{suffix}'
            return m.group(0)

        result = re.sub(pattern, attr_replacer, result)

    return result


def main():
    print("=" * 60)
    print("SquidStats Template i18n Marker")
    print("=" * 60)

    dry_run = "--dry-run" in sys.argv
    target = (
        sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    )

    if target:
        filepath = os.path.join(PROJECT_ROOT, target)
        if not os.path.exists(filepath):
            filepath = target
        if os.path.exists(filepath):
            if dry_run:
                with open(filepath) as f:
                    original = f.read()
                process_template(filepath)
                with open(filepath) as f:
                    modified = f.read()
                if original != modified:
                    print(f"Would modify: {target}")
                    # Restore
                    with open(filepath, "w") as f:
                        f.write(original)
                else:
                    print(f"No changes: {target}")
            else:
                if process_template(filepath):
                    print(f"✓ Modified: {target}")
                else:
                    print(f"- No changes: {target}")
        else:
            print(f"File not found: {filepath}")
        return

    count = 0
    for root, _dirs, files in os.walk(TEMPLATES_DIR):
        for f in sorted(files):
            if f.endswith(".html"):
                filepath = os.path.join(root, f)
                relpath = os.path.relpath(filepath, PROJECT_ROOT)
                if process_template(filepath):
                    print(f"  ✓ {relpath}")
                    count += 1
                else:
                    print(f"  - {relpath} (no changes)")

    print(f"\nModified {count} template files")


if __name__ == "__main__":
    main()

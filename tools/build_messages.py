#!/usr/bin/env python3
"""
Merge all .po files from translations/<lang>/sources/ into
translations/<lang>/LC_MESSAGES/messages.po and compile them with pybabel.

Usage:
    python tools/build_messages.py [--lang en] [--no-compile]
"""

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# PO entry dataclass
# ---------------------------------------------------------------------------


class PoEntry:
    """Holds one PO message entry."""

    def __init__(self):
        self.comments: list[str] = []  # # …  and #: … and #, …
        self.msgid: list[str] = []  # one or more lines
        self.msgid_plural: list[str] = []
        self.msgstr: list[str] = []  # singular or msgstr[0], [1] …
        self.msgstr_plural: dict[int, list[str]] = {}
        self.obsolete: bool = False

    @property
    def key(self) -> str:
        return "".join(self.msgid)

    def is_empty_header(self) -> bool:
        return self.key == ""

    def render(self) -> str:
        lines = []
        for c in self.comments:
            lines.append(c)
        if self.msgid_plural:
            lines.append(_render_field("msgid", self.msgid))
            lines.append(_render_field("msgid_plural", self.msgid_plural))
            for idx in sorted(self.msgstr_plural):
                lines.append(_render_field(f"msgstr[{idx}]", self.msgstr_plural[idx]))
        else:
            lines.append(_render_field("msgid", self.msgid))
            lines.append(_render_field("msgstr", self.msgstr))
        return "\n".join(lines)


def _render_field(name: str, parts: list[str]) -> str:
    if len(parts) == 1:
        return f"{name} {parts[0]}"
    # multiline
    return f'{name} ""\n' + "\n".join(parts)


# ---------------------------------------------------------------------------
# Simple PO parser
# ---------------------------------------------------------------------------


def parse_po_entries(text: str) -> list[PoEntry]:
    """Return all non-header entries from a PO file text."""
    entries: list[PoEntry] = []
    current = PoEntry()
    state = "idle"  # idle | comments | msgid | msgid_plural | msgstr | msgstr_plural

    def flush():
        nonlocal current
        if current.msgid or current.comments:
            entries.append(current)
        current = PoEntry()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        # Obsolete entries – preserve but mark
        if line.startswith("#~"):
            if state not in ("idle", "comments"):
                flush()
                state = "idle"
            current.comments.append(line)
            current.obsolete = True
            state = "comments"
            continue

        # Blank line → flush entry
        if line == "":
            if state != "idle":
                flush()
                state = "idle"
            continue

        # Comment / reference / flag lines
        if line.startswith("#"):
            if state not in ("idle", "comments"):
                flush()
                state = "idle"
            current.comments.append(line)
            state = "comments"
            continue

        # Continuation string
        if line.startswith('"'):
            if state == "msgid":
                current.msgid.append(line)
            elif state == "msgid_plural":
                current.msgid_plural.append(line)
            elif state == "msgstr":
                current.msgstr.append(line)
            elif state == "msgstr_plural":
                current.msgstr_plural[_last_plural_idx(current)].append(line)
            continue

        # Keywords
        if line.startswith("msgid_plural "):
            value = line[len("msgid_plural ") :]
            current.msgid_plural = [value]
            state = "msgid_plural"
            continue

        if line.startswith("msgid "):
            value = line[len("msgid ") :]
            current.msgid = [value]
            state = "msgid"
            continue

        m = re.match(r"^msgstr\[(\d+)\] (.+)$", line)
        if m:
            idx = int(m.group(1))
            current.msgstr_plural[idx] = [m.group(2)]
            state = "msgstr_plural"
            continue

        if line.startswith("msgstr "):
            value = line[len("msgstr ") :]
            current.msgstr = [value]
            state = "msgstr"
            continue

    # Flush last entry
    if state != "idle":
        flush()

    return entries


def _last_plural_idx(entry: PoEntry) -> int:
    return max(entry.msgstr_plural.keys()) if entry.msgstr_plural else 0


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

PO_HEADER = """\
# English translations for SquidStats.
# Edit the files under sources/ and then run:
#   python tools/build_messages.py
#
msgid ""
msgstr ""
"Project-Id-Version: SquidStats\\n"
"Report-Msgid-Bugs-To: \\n"
"POT-Creation-Date: {now}\\n"
"PO-Revision-Date: {now}\\n"
"Last-Translator: \\n"
"Language: {lang}\\n"
"Language-Team: {lang} <LL@li.org>\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=utf-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Generated-By: build_messages.py\\n"
"""


def merge_sources(sources_dir: Path) -> list[PoEntry]:
    """Read all .po files in sources_dir (sorted) and merge entries."""
    po_files = sorted(sources_dir.glob("*.po"))
    if not po_files:
        print(f"  [!] No .po files found in {sources_dir}", file=sys.stderr)
        return []

    seen: dict[str, PoEntry] = {}  # msgid → entry (deduplication)
    for po_file in po_files:
        print(f"  Reading {po_file.name}")
        text = po_file.read_text(encoding="utf-8")
        for entry in parse_po_entries(text):
            if entry.is_empty_header():
                continue
            if entry.key not in seen:
                seen[entry.key] = entry
            # If duplicate, merge location comments
            else:
                existing = seen[entry.key]
                new_refs = [c for c in entry.comments if c.startswith("#:")]
                for ref in new_refs:
                    if ref not in existing.comments:
                        existing.comments.append(ref)

    return list(seen.values())


def write_messages_po(output_path: Path, entries: list[PoEntry], lang: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M%z")
    header = PO_HEADER.format(now=now, lang=lang)

    regular = [e for e in entries if not e.obsolete]
    obsolete = [e for e in entries if e.obsolete]

    blocks = [header]
    for entry in regular:
        blocks.append(entry.render())
    if obsolete:
        for entry in obsolete:
            blocks.append(entry.render())

    output_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print(
        f"  Written → {output_path}  ({len(regular)} entries, {len(obsolete)} obsolete)"
    )


def compile_po(translations_dir: Path) -> bool:
    cmd = [
        sys.executable,
        "-m",
        "babel.messages.frontend",
        "compile",
        "-d",
        str(translations_dir),
    ]
    # Try the pybabel CLI as fallback
    pybabel_cmd = ["pybabel", "compile", "-d", str(translations_dir)]
    print(f"\n  Running: pybabel compile -d {translations_dir}")
    try:
        result = subprocess.run(pybabel_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(result.stdout or "  Compilation successful.")
            return True
        # Fallback to module invocation
        result2 = subprocess.run(cmd, capture_output=True, text=True)
        if result2.returncode == 0:
            print(result2.stdout or "  Compilation successful.")
            return True
        print(
            f"  [ERROR] pybabel compile failed:\n{result.stderr}\n{result2.stderr}",
            file=sys.stderr,
        )
        return False
    except FileNotFoundError:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(result.stdout or "  Compilation successful.")
            return True
        print(f"  [ERROR] {result.stderr}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Merge sources/*.po → messages.po and compile."
    )
    parser.add_argument("--lang", default="en", help="Language code (default: en)")
    parser.add_argument(
        "--no-compile", action="store_true", help="Skip pybabel compile step"
    )
    args = parser.parse_args()

    # Resolve paths relative to the project root (one level up from tools/)
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    translations_dir = project_root / "translations"
    lang_dir = translations_dir / args.lang
    sources_dir = lang_dir / "sources"
    output_path = lang_dir / "LC_MESSAGES" / "messages.po"

    print(f"\n=== Building messages.po for language: {args.lang} ===")
    print(f"  Sources : {sources_dir}")
    print(f"  Output  : {output_path}\n")

    if not sources_dir.exists():
        print(f"[ERROR] Sources directory not found: {sources_dir}", file=sys.stderr)
        sys.exit(1)

    entries = merge_sources(sources_dir)
    if not entries:
        print("[ERROR] No entries found. Aborting.", file=sys.stderr)
        sys.exit(1)

    write_messages_po(output_path, entries, args.lang)

    if not args.no_compile:
        ok = compile_po(translations_dir)
        if not ok:
            sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()

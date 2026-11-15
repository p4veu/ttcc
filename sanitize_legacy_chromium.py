#!/usr/bin/env python3
"""Remove non-BMP glyphs that break CDP Runtime.evaluate on older Tizen Chromium.

TizenBrew 2.0.5 injects a module by passing its complete userscript to
Chromium's Runtime.evaluate. The built TizenTube bundle contains two emoji
only in i18next's informational console banner. On older Chromium builds,
those surrogate pairs can break the CDP JSON parser before TTCC starts.
"""
from pathlib import Path
import sys

REPLACEMENTS = {
    chr(0x1F310): "[web]",
    chr(0x1F499): "",
}


def sanitize_source(source: str) -> str:
    for glyph, replacement in REPLACEMENTS.items():
        count = source.count(glyph)
        if count != 1:
            raise ValueError(
                f"Expected exactly one {ord(glyph):#06x} glyph in the "
                f"i18next banner; found {count}. Review upstream bundle changes."
            )
        source = source.replace(glyph, replacement, 1)

    unsupported = sorted({ord(char) for char in source if ord(char) > 0xFFFF})
    if unsupported:
        formatted = ", ".join(f"U+{codepoint:04X}" for codepoint in unsupported)
        raise ValueError(
            "Unexpected non-BMP characters remain in the userscript: " + formatted
        )
    return source


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("upstream/dist/userScript.js")
    source = path.read_text(encoding="utf-8")
    sanitized = sanitize_source(source)
    path.write_text(sanitized, encoding="utf-8")
    print(f"Legacy Tizen Chromium compatibility: sanitized {path}; no non-BMP characters remain.")


if __name__ == "__main__":
    main()

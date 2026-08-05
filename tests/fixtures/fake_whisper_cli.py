#!/usr/bin/env python3
"""Stand-in for whisper-cli that writes a recorded real output document.

Only the file-handoff contract is faked: read `-of` for the output prefix and
write `<prefix>.json`. The document itself is a trimmed capture of a genuine
`whisper-cli -ojf` run, so the conversion under test sees the shape whisper.cpp
actually produces rather than one invented to match the parser.

`WHISPER_FAKE_MODE=fail` exits nonzero after printing to stderr; `silent`
exits zero without writing the document.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

RECORDED = Path(__file__).resolve().parent / "whisper-cli-output.json"


def main() -> int:
    argv = sys.argv[1:]
    prefix = argv[argv.index("-of") + 1]
    mode = os.environ.get("WHISPER_FAKE_MODE", "success")
    if mode == "fail":
        print("whisper-secret-must-not-leak /private/path", file=sys.stderr)
        return 7
    if mode == "silent":
        return 0
    shutil.copyfile(RECORDED, f"{prefix}.json")
    return 0


raise SystemExit(main())

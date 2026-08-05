"""ASR command fixture that records the argv it was actually handed.

``fake_asr_command.py`` reads fixed positional slots, so it cannot show
whether an argument survived the CLI. This one writes its whole argv to the
observation path, which is what proves that a provider argument starting with
``-`` reached the wrapper instead of being eaten by argparse.

argv: {media} <fixture-json> <observation-path> [anything else]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    media_path = Path(sys.argv[1])
    fixture_path = Path(sys.argv[2])
    observation_path = Path(sys.argv[3])
    observation_path.write_text(
        json.dumps({"media": str(media_path), "argv": sys.argv[1:]}, sort_keys=True),
        encoding="utf-8",
    )
    print(
        json.dumps(
            json.loads(fixture_path.read_text(encoding="utf-8")),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


raise SystemExit(main())

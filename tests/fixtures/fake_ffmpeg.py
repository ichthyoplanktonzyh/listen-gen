#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


arguments = sys.argv[1:]
media_path = Path(arguments[arguments.index("-i") + 1])
output_path = Path(arguments[-1])
media = json.loads(media_path.read_text(encoding="utf-8"))
observation = os.environ.get("LISTEN_GEN_TEST_FFMPEG_OBSERVATION")
mode = media.get("ffmpeg_mode", "success")
if observation and mode != "spawn-child":
    Path(observation).write_text(json.dumps(arguments), encoding="utf-8")
if mode == "sleep":
    time.sleep(2)
elif mode == "spawn-child":
    child_marker = Path(observation).with_suffix(".child")
    subprocess.Popen([
        sys.executable,
        "-c",
        "import pathlib,sys,time; time.sleep(0.4); pathlib.Path(sys.argv[1]).write_text('leaked')",
        str(child_marker),
    ])
    Path(observation).write_text(json.dumps(arguments), encoding="utf-8")
    time.sleep(2)
elif mode == "fail":
    print("transcode-secret-must-not-leak", file=sys.stderr)
    raise SystemExit(29)
elif mode == "missing":
    pass
else:
    output_path.write_bytes(b"RIFFfake-16khz-mono-pcm")

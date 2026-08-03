#!/usr/bin/env python3
"""whisper.cpp command wrapper for the listen-gen command ASR provider.

Runs ``whisper-cli --output-json-full`` and converts the whisper.cpp JSON
document into the normalized ``listen_gen.asr-result.v1`` protocol that the
provider-neutral CommandAsrAdapter consumes. The wrapper writes only the
normalized JSON to stdout; whisper-cli's own stdout is discarded.

Example provider argv:

    --provider command --command python3
    --command-arg /abs/path/whisper_cpp_wrapper.py
    --command-arg {media} --command-arg --model /abs/path/ggml-base.bin
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TOKEN_RE = re.compile(r"\w+(?:['\u2019]\w+)*|\s+|[^\w\s]", re.UNICODE)
SPECIAL_TOKEN_RE = re.compile(r"\[_[A-Z]+_\]")
SCHEMA = "listen_gen.asr-result.v1"


def _parse_clock(value: str) -> int:
    """Convert ``HH:MM:SS,mmm`` to milliseconds."""
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3_600_000 + int(minutes) * 60_000 + int(seconds) * 1000 + int(millis)


def _normalize_token_text(value: str) -> str:
    value = SPECIAL_TOKEN_RE.sub("", value)
    return value.replace("_", " ")


def _word_tokens(text: str) -> list[tuple[int, int, str]]:
    return [
        (match.start(), match.end(), match.group(0))
        for match in TOKEN_RE.finditer(text)
        if not match.group(0).isspace()
        and (match.group(0)[0].isalnum() or match.group(0)[0] == "_")
    ]


def _convert(json_path: Path, model_path: Path, model_version: str) -> dict:
    with json_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    transcription = raw.get("transcription") or []
    if not transcription:
        raise ValueError("whisper.cpp produced no transcription segments")

    language = (raw.get("result") or {}).get("language")
    if not language:
        raise ValueError("whisper.cpp result did not report a language")

    segments = []
    for segment in transcription:
        text = segment.get("text") or ""
        tokens = segment.get("tokens") or []
        if not text or not tokens:
            continue

        # whisper.cpp token text (BPE spelling with "_" word-boundary markers)
        # concatenates to the segment text after normalization, so each token
        # maps to an exact character span of the segment.
        normalized = [_normalize_token_text(token.get("text") or "") for token in tokens]
        spans: list[tuple[int, int, int, int, float | None]] = []
        cursor = 0
        for token, token_text in zip(tokens, normalized):
            length = len(token_text)
            offsets = token.get("offsets") or {}
            start_ms = offsets.get("from")
            end_ms = offsets.get("to")
            if start_ms is None or end_ms is None:
                timestamps = token.get("timestamps") or {}
                start_ms = _parse_clock(timestamps["from"]) if timestamps.get("from") else None
                end_ms = _parse_clock(timestamps["to"]) if timestamps.get("to") else None
            if start_ms is None or end_ms is None or length == 0:
                cursor += length
                continue
            spans.append((cursor, cursor + length, start_ms, end_ms, token.get("p")))
            cursor += length

        starts = segment.get("offsets") or {}
        segment_start = starts.get("from") or _parse_clock(
            (segment.get("timestamps") or {}).get("from")
        )
        segment_end = starts.get("to") or _parse_clock(
            (segment.get("timestamps") or {}).get("to")
        )

        words = []
        previous_word_end = segment_start
        for start_char, end_char, _ in _word_tokens(text):
            covering = [
                span for span in spans if span[0] < end_char and span[1] > start_char
            ]
            if not covering:
                continue
            raw_start = min(span[2] for span in covering)
            raw_end = max(span[3] for span in covering)
            # whisper.cpp can report zero-length or non-monotonic token spans;
            # clamp to the segment and force a positive, monotonic range.
            word_start = max(raw_start, segment_start, previous_word_end)
            word_end = max(raw_end, word_start + 1)
            if word_end > segment_end:
                word_end = segment_end
            if word_end <= word_start:
                continue
            confidences = [span[4] for span in covering if span[4] is not None]
            words.append({
                "start_char": start_char,
                "end_char": end_char,
                "start_ms": word_start,
                "end_ms": word_end,
                "timing_source": "asr_reported",
                **({"confidence": round(sum(confidences) / len(confidences), 4)}
                   if confidences else {}),
            })
            previous_word_end = word_end

        if not words:
            raise ValueError(f"whisper.cpp segment {text[:40]!r} has no alignable words")

        segments.append({
            "start_ms": segment_start,
            "end_ms": segment_end,
            "text": text,
            "words": words,
        })

    if not segments:
        raise ValueError("whisper.cpp produced no usable segments")

    return {
        "schema": SCHEMA,
        "language": language,
        "provider": {"id": "whisper.cpp", "version": "command-wrapper-1"},
        "model": {"id": model_path.name, "version": model_version},
        "segments": segments,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--whisper-cli", default="whisper-cli")
    parser.add_argument("--model-version", default="ggml")
    args = parser.parse_args(argv)

    if not args.media.is_file():
        print(f"media input is not a regular file: {args.media}", file=sys.stderr)
        return 2
    if not args.model.is_file():
        print(f"whisper model file not found: {args.model}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="whisper-wrapper-") as tmp:
        output_prefix = str(Path(tmp) / "whisper")
        command = [
            args.whisper_cli,
            "-m", str(args.model),
            "-f", str(args.media),
            "-ojf",
            "-of", output_prefix,
            "-nt",
            "-np",
        ]
        completed = subprocess.run(command, stdout=subprocess.DEVNULL, check=False)
        if completed.returncode != 0:
            print(f"whisper-cli failed with exit status {completed.returncode}", file=sys.stderr)
            return 3
        json_path = Path(f"{output_prefix}.json")
        if not json_path.is_file():
            print("whisper-cli did not write its JSON output", file=sys.stderr)
            return 3
        try:
            document = _convert(json_path, args.model, args.model_version)
        except ValueError as error:
            print(f"whisper conversion failed: {error}", file=sys.stderr)
            return 4

    json.dump(document, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

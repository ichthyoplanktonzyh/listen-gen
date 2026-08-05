"""whisper.cpp as a first-class ASR provider.

Lifted from `tools/whisper_cpp_wrapper.py`, which required a supervisor to
wire up a python interpreter, a script path, a `{media}` placeholder and the
normalized-JSON protocol before whisper.cpp could be used at all. Every one of
those is an internal detail of this repository, so every one of them leaked
into the caller's configuration; listen-app ended up asking a person to write
nested-escaped JSON. The conversion below is unchanged -- only its packaging
is. The wrapper script stays as the worked example of the `command` seam.
"""

from __future__ import annotations

import json
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Callable

from .package import ConversionError
from .process import ProcessOutputTooLarge, ProcessTimedOut, run_argv

WHISPER_STDOUT_LIMIT_BYTES = 1024 * 1024

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


def _convert(
    json_path: Path, model_path: Path, model_version: str, duration_ms: int
) -> dict:
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

        if segment_end > duration_ms:
            segment_end = duration_ms
        if segment_start >= segment_end:
            continue
        words = [
            word for word in words
            if word["start_ms"] < segment_end
        ]
        for word in words:
            if word["end_ms"] > segment_end:
                word["end_ms"] = segment_end

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


class WhisperCppAsrAdapter:
    """Run whisper.cpp directly and return a normalized transcript.

    Sits at the same seam as `CommandAsrAdapter` and, like it, receives the
    already-normalized 16 kHz mono WAV from `PreprocessingAsrAdapter`. The
    media duration is supplied by the caller rather than probed again: the CLI
    already requires it, and the clamping below is the only thing that needs
    it.
    """

    def __init__(
        self,
        model_path: Path,
        *,
        whisper_cli: str,
        duration_ms: int,
        timeout_seconds: float,
        model_version: str = "ggml",
        progress: Callable[[str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ):
        if timeout_seconds <= 0:
            raise ConversionError("whisper timeout must be positive")
        self.model_path = model_path
        self.whisper_cli = whisper_cli
        self.duration_ms = duration_ms
        self.timeout_seconds = timeout_seconds
        self.model_version = model_version
        self.progress = progress
        self.cancellation_requested = cancellation_requested

    def transcribe(self, media_path: Path):
        from .asr import _parse_transcript

        if self.progress is not None:
            self.progress("transcribing")
        if not media_path.is_file():
            raise ConversionError("media input is not a regular file")
        if not self.model_path.is_file():
            # Named plainly: this is the one failure a person can fix, and the
            # path is the caller's own configured value, not a private path.
            raise ConversionError(
                f"whisper model file not found: {self.model_path.name}"
            )
        with tempfile.TemporaryDirectory(prefix="listen-gen-whisper-") as directory:
            prefix = str(Path(directory) / "whisper")
            argv = [
                self.whisper_cli,
                "-m", str(self.model_path),
                "-f", str(media_path),
                "-ojf",
                "-of", prefix,
                "-nt",
                "-np",
            ]
            try:
                completed = run_argv(
                    argv,
                    timeout_seconds=self.timeout_seconds,
                    stdout_limit_bytes=WHISPER_STDOUT_LIMIT_BYTES,
                    cancellation_requested=self.cancellation_requested,
                )
            except ProcessTimedOut as error:
                raise ConversionError(
                    "ASR provider timed out without producing a usable result"
                ) from error
            except ProcessOutputTooLarge as error:
                raise ConversionError(
                    "ASR provider output exceeded the safety limit"
                ) from error
            except OSError as error:
                raise ConversionError("ASR provider could not be started") from error
            if completed.returncode != 0:
                # whisper-cli's own stderr can carry local paths, so only the
                # status crosses this boundary.
                raise ConversionError(
                    f"ASR provider failed with exit status {completed.returncode}"
                )
            document = Path(f"{prefix}.json")
            if not document.is_file():
                raise ConversionError("ASR provider wrote no transcript document")
            try:
                raw = _convert(
                    document, self.model_path, self.model_version, self.duration_ms
                )
            except (ValueError, KeyError, json.JSONDecodeError) as error:
                raise ConversionError(f"ASR provider transcript unusable: {error}") from error
        return _parse_transcript(raw)

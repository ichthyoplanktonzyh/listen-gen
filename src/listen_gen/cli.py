from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from typing import Any

from .asr import (
    CommandAsrAdapter,
    FixtureAsrAdapter,
    PreprocessingAsrAdapter,
    package_media,
)
from .media import FfmpegAudioPreprocessor
from .machine import (
    CancellationRequested,
    CancellationState,
    MachineEventWriter,
    cancellation_exit_code,
    cancellation_signals,
    stable_error,
)
from .package import ConversionError, InvalidArgumentError, package_from_lltimeline
from .process import ProcessCancelled


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="listen-gen")
    commands = root.add_subparsers(dest="command", required=True)
    package = commands.add_parser("package", help="build a Listen content package")
    package_commands = package.add_subparsers(dest="package_command", required=True)
    native = package_commands.add_parser(
        "from-media", help="transcribe media and emit native v1 resources"
    )
    native.add_argument("input", type=Path)
    native.add_argument("--output", required=True, type=Path)
    native.add_argument("--provider", required=True, choices=["fixture", "command"])
    native.add_argument("--fixture", type=Path, help="normalized JSON for the fixture provider")
    native.add_argument("--command", help="external ASR wrapper executable; no shell is used")
    native.add_argument(
        "--command-arg",
        action="append",
        default=[],
        help=(
            "one argv item for the command provider; include {media} exactly once. "
            "An item that itself starts with '-' must use the joined form "
            "(--command-arg=--model): argparse cannot tell a value from an option "
            "otherwise. Supervisors that build argv from config should prefer "
            "--command-argv-json, which has no such rule."
        ),
    )
    native.add_argument(
        "--command-argv-json",
        help=(
            "the whole command provider argv as one JSON array of strings, e.g. "
            '\'["wrapper.py", "{media}", "--model", "base.bin"]\'. Carries items '
            "that start with '-' with no quoting rule at all. Mutually exclusive "
            "with --command-arg."
        ),
    )
    native.add_argument("--command-timeout-seconds", type=float, default=3600.0)
    native.add_argument(
        "--audio-stream-index",
        type=int,
        help="container stream index; required when the media has multiple audio streams",
    )
    native.add_argument("--ffprobe-command", default="ffprobe")
    native.add_argument("--ffmpeg-command", default="ffmpeg")
    native.add_argument("--media-command-timeout-seconds", type=float, default=300.0)
    native.add_argument("--title", required=True)
    native.add_argument("--media-kind", required=True, choices=["audio", "video"])
    native.add_argument("--duration-ms", required=True, type=int)
    native.add_argument("--created-at-ms", required=True, type=int)
    native.add_argument(
        "--machine-events",
        action="store_true",
        help="write the versioned machine protocol as NDJSON to stdout",
    )
    legacy = package_commands.add_parser(
        "from-lltimeline", help="convert an LLTimeline v1 document"
    )
    legacy.add_argument("input", type=Path)
    legacy.add_argument("--output", required=True, type=Path)
    legacy.add_argument(
        "--machine-events",
        action="store_true",
        help="write the versioned machine protocol as NDJSON to stdout",
    )
    return root


def _machine_result(result: dict[str, Any]) -> dict[str, Any]:
    machine_result = {
        "package_sha256": f"sha256:{result['package_sha256']}",
        "resources": result["resources"],
        "warnings": result["warnings"],
    }
    if "media_fingerprint" in result:
        machine_result["media_fingerprint"] = result["media_fingerprint"]
    return machine_result


def _command_arguments(args: argparse.Namespace) -> list[str]:
    """The command provider's argv, from either spelling.

    ``--command-arg`` cannot carry an item that starts with ``-`` unless the
    caller uses the joined form, because argparse reads the next token as an
    option. A supervisor assembling argv from stored configuration hits this
    the moment a wrapper takes a flag, and argparse's own message
    ("expected one argument") names neither the cause nor the fix. So a
    programmatic caller gets a spelling with no quoting rule at all.
    """
    encoded = args.command_argv_json
    if encoded is None:
        return list(args.command_arg)
    if args.command_arg:
        raise InvalidArgumentError(
            "--command-arg and --command-argv-json are mutually exclusive; "
            "pass the whole provider argv through one of them"
        )
    try:
        decoded = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise InvalidArgumentError(
            f"--command-argv-json is not valid JSON: {error.msg}"
        ) from error
    if not isinstance(decoded, list) or any(
        not isinstance(item, str) for item in decoded
    ):
        raise InvalidArgumentError("--command-argv-json must be a JSON array of strings")
    return decoded


def _run(args: argparse.Namespace, state: CancellationState, writer: MachineEventWriter | None) -> dict[str, Any]:
    progress = None if writer is None else lambda phase: writer.emit("phase", phase=phase)
    if args.package_command == "from-media":
        if args.provider == "fixture":
            if args.fixture is None:
                raise InvalidArgumentError("--fixture is required for the fixture provider")
            adapter = FixtureAsrAdapter(args.fixture, progress=progress)
        else:
            if args.command is None:
                raise InvalidArgumentError("--command is required for the command provider")
            command_adapter = CommandAsrAdapter(
                args.command,
                _command_arguments(args),
                args.command_timeout_seconds,
                progress=progress,
                cancellation_requested=state.requested,
            )
            adapter = PreprocessingAsrAdapter(
                command_adapter,
                FfmpegAudioPreprocessor(
                    ffprobe_executable=args.ffprobe_command,
                    ffmpeg_executable=args.ffmpeg_command,
                    timeout_seconds=args.media_command_timeout_seconds,
                    progress=progress,
                    cancellation_requested=state.requested,
                ),
                audio_stream_index=args.audio_stream_index,
            )
        return package_media(
            args.input,
            args.output,
            adapter,
            title=args.title,
            media_kind=args.media_kind,
            duration_ms=args.duration_ms,
            created_at_ms=args.created_at_ms,
            progress=progress,
        )
    return package_from_lltimeline(args.input, args.output, progress=progress)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    machine = bool(args.machine_events)
    writer = MachineEventWriter() if machine else None
    state = CancellationState()
    if writer is not None:
        writer.protocol()
        operation = f"package.{args.package_command}"
        writer.emit("started", operation=operation)
    try:
        with cancellation_signals(state):
            result = _run(args, state, writer)
    except (CancellationRequested, ProcessCancelled) as cancelled:
        signal_number = (
            cancelled.signal_number
            if isinstance(cancelled, CancellationRequested)
            else state.signal_number or signal.SIGINT
        )
        if writer is not None:
            writer.emit("cancelled", code="cancelled")
        else:
            print(json.dumps({"status": "cancelled"}, sort_keys=True), file=sys.stderr)
        return cancellation_exit_code(signal_number)
    except (ConversionError, OSError, json.JSONDecodeError) as error:
        if writer is not None:
            code, message = stable_error(error)
            writer.emit("failed", code=code, message=message)
        else:
            print(
                json.dumps(
                    {"status": "failed", "error": str(error)},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
        return 2
    except Exception:
        if writer is None:
            raise
        writer.emit("failed", code="internal_error", message="generation failed unexpectedly")
        return 2
    if writer is not None:
        writer.emit("completed", **_machine_result(result))
    else:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0

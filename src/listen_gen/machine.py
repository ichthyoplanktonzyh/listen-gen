from __future__ import annotations

import json
import signal
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from .package import InvalidArgumentError, PackageWriteError

MACHINE_EVENT_SCHEMA = "listen_gen.machine-event.v1"
MACHINE_PROTOCOL_VERSION = 1
TOOL_ID = "listen-gen"
TOOL_VERSION = "0.1.0"


class CancellationRequested(BaseException):
    """Raised when the supervising process requests graceful cancellation."""

    def __init__(self, signal_number: int):
        super().__init__(signal_number)
        self.signal_number = signal_number


@dataclass
class CancellationState:
    signal_number: int | None = None

    def requested(self) -> bool:
        return self.signal_number is not None


@contextmanager
def cancellation_signals(state: CancellationState) -> Iterator[None]:
    previous: dict[int, Any] = {}

    def request(signum: int, _frame: Any) -> None:
        state.signal_number = signum
        raise CancellationRequested(signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


class MachineEventWriter:
    def __init__(self) -> None:
        self._sequence = 0

    def emit(self, event: str, **payload: Any) -> None:
        document = {
            "schema": MACHINE_EVENT_SCHEMA,
            "protocol_version": MACHINE_PROTOCOL_VERSION,
            "sequence": self._sequence,
            "tool": {"id": TOOL_ID, "version": TOOL_VERSION},
            "event": event,
            **payload,
        }
        self._sequence += 1
        print(json.dumps(document, ensure_ascii=False, sort_keys=True), flush=True)

    def protocol(self) -> None:
        self.emit(
            "protocol",
            capabilities={
                "operations": ["package.from-lltimeline", "package.from-media"],
                "phases": [
                    "validating",
                    "probing_media",
                    "normalizing_audio",
                    "transcribing",
                    "building_package",
                ],
                "terminal_events": ["completed", "failed", "cancelled"],
            },
        )


def stable_error(error: BaseException) -> tuple[str, str]:
    message = str(error)
    lowered = message.lower()
    if isinstance(error, PackageWriteError):
        return "package_write_failed", "package output could not be written"
    # Typed checks come before the substring heuristics below, which read the
    # message rather than the failure: a usage error naming "provider" is not
    # a provider failure, and saying so would report a stage that never ran.
    if isinstance(error, InvalidArgumentError):
        return "invalid_input", message
    if "probe" in lowered or "audio stream" in lowered:
        return "media_probe_failed", message
    if "preprocess" in lowered or "ffmpeg" in lowered:
        return "audio_preprocessing_failed", message
    if "asr" in lowered or "provider" in lowered:
        return "provider_failed", message
    if isinstance(error, (OSError, json.JSONDecodeError)):
        return "invalid_input", "input could not be read or decoded"
    return "invalid_input", message


def cancellation_exit_code(signal_number: int) -> int:
    return 128 + signal_number

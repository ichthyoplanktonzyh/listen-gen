from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WhisperCppProviderTests(unittest.TestCase):
    """whisper.cpp as a provider the caller can name in two arguments.

    It used to be reachable only through `tools/whisper_cpp_wrapper.py`, which
    meant a supervisor had to wire a python interpreter, a script path, the
    `{media}` placeholder and the normalized-JSON protocol before whisper.cpp
    would run at all. Those are internals of this repository, so they leaked
    straight into the caller's stored configuration -- listen-app ended up
    asking a person to hand-write nested-escaped JSON, which is what prompted
    this seam.

    The wrapper is kept as the worked example of the `command` provider, and
    `test_cli.py` still covers that path.
    """

    media = ROOT / "tests" / "fixtures" / "single-audio-media.json"
    whisper = ROOT / "tests" / "fixtures" / "fake_whisper_cli.py"
    ffprobe = ROOT / "tests" / "fixtures" / "fake_ffprobe.py"
    ffmpeg = ROOT / "tests" / "fixtures" / "fake_ffmpeg.py"

    def setUp(self) -> None:
        self.whisper.chmod(self.whisper.stat().st_mode | stat.S_IEXEC)

    def environment(self, **updates: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment.update(updates)
        return environment

    def run_cli(
        self,
        *,
        output: Path,
        model: Path | None,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        arguments = [
            sys.executable,
            "-m",
            "listen_gen",
            "package",
            "from-media",
            str(self.media),
            "--output",
            str(output),
            "--provider",
            "whisper-cpp",
            "--whisper-cli",
            str(self.whisper),
            "--ffprobe-command",
            str(self.ffprobe),
            "--ffmpeg-command",
            str(self.ffmpeg),
            "--title",
            "Lesson",
            "--media-kind",
            "audio",
            "--duration-ms",
            "11000",
            "--created-at-ms",
            "1785542400000",
            "--machine-events",
        ]
        if model is not None:
            arguments[arguments.index("--provider")] = "--provider"
            arguments += ["--model", str(model)]
        return subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            env=environment or self.environment(),
        )

    def terminal_event(self, stdout: str) -> dict[str, object]:
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        terminal = [
            event
            for event in events
            if event["event"] in {"completed", "failed", "cancelled"}
        ]
        self.assertEqual(len(terminal), 1, stdout)
        return terminal[0]

    def model(self, directory: str) -> Path:
        model = Path(directory) / "ggml-base.bin"
        model.write_bytes(b"not a real model; the fake cli never reads it")
        return model

    def test_two_arguments_are_enough_to_produce_a_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "lesson.listenpkg"
            completed = self.run_cli(output=output, model=self.model(directory))
            self.assertEqual(completed.returncode, 0, completed.stdout)
            terminal = self.terminal_event(completed.stdout)
            self.assertEqual(terminal["event"], "completed")
            self.assertTrue(output.is_file())
            kinds = {resource["kind"] for resource in terminal["resources"]}
            self.assertEqual(kinds, {"subtitle_text_track", "word_timeline"})

    def test_missing_model_argument_is_a_typed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_cli(
                output=Path(directory) / "lesson.listenpkg", model=None
            )
            terminal = self.terminal_event(completed.stdout)
            self.assertEqual(terminal["event"], "failed")
            self.assertEqual(terminal["code"], "invalid_input")

    def test_absent_model_file_names_the_file_and_not_its_path(self) -> None:
        # The one failure a person can act on, so it names the file. The
        # containing directory is the caller's own value but still local
        # detail, and packages and event streams are things that travel.
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_cli(
                output=Path(directory) / "lesson.listenpkg",
                model=Path(directory) / "absent" / "ggml-large.bin",
            )
            terminal = self.terminal_event(completed.stdout)
            self.assertEqual(terminal["event"], "failed")
            self.assertIn("ggml-large.bin", terminal["message"])
            self.assertNotIn(directory, terminal["message"])

    def test_provider_stderr_never_reaches_the_event_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_cli(
                output=Path(directory) / "lesson.listenpkg",
                model=self.model(directory),
                environment=self.environment(WHISPER_FAKE_MODE="fail"),
            )
            terminal = self.terminal_event(completed.stdout)
            self.assertEqual(terminal["event"], "failed")
            self.assertEqual(terminal["code"], "provider_failed")
            self.assertNotIn("whisper-secret-must-not-leak", completed.stdout)
            self.assertNotIn("/private/path", completed.stdout)

    def test_provider_that_writes_no_document_fails_rather_than_hangs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_cli(
                output=Path(directory) / "lesson.listenpkg",
                model=self.model(directory),
                environment=self.environment(WHISPER_FAKE_MODE="silent"),
            )
            terminal = self.terminal_event(completed.stdout)
            self.assertEqual(terminal["event"], "failed")
            self.assertEqual(terminal["code"], "provider_failed")


if __name__ == "__main__":
    unittest.main()

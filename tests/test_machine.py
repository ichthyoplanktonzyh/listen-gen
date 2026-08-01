from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MachineProtocolTests(unittest.TestCase):
    media = ROOT / "tests" / "fixtures" / "sample-media.wav"
    fixture = ROOT / "tests" / "fixtures" / "sample.asr.json"
    ffprobe = ROOT / "tests" / "fixtures" / "fake_ffprobe.py"
    ffmpeg = ROOT / "tests" / "fixtures" / "fake_ffmpeg.py"
    command = ROOT / "tests" / "fixtures" / "fake_asr_command.py"

    def environment(self, **updates: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment.update(updates)
        return environment

    def fixture_arguments(self, output: Path) -> list[str]:
        return [
            sys.executable,
            "-m",
            "listen_gen",
            "package",
            "from-media",
            str(self.media),
            "--output",
            str(output),
            "--provider",
            "fixture",
            "--fixture",
            str(self.fixture),
            "--title",
            "Fixture lesson",
            "--media-kind",
            "audio",
            "--duration-ms",
            "2200",
            "--created-at-ms",
            "1785542400000",
            "--machine-events",
        ]

    def test_success_stream_has_monotonic_envelopes_and_one_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "lesson.listenpkg"
            completed = subprocess.run(
                self.fixture_arguments(output),
                cwd=ROOT,
                env=self.environment(),
                check=True,
                capture_output=True,
                text=True,
            )
            events = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual([event["sequence"] for event in events], list(range(len(events))))
            self.assertTrue(all(event["schema"] == "listen_gen.machine-event.v1" for event in events))
            self.assertTrue(all(event["protocol_version"] == 1 for event in events))
            self.assertEqual(events[0]["event"], "protocol")
            self.assertEqual(sum(event["event"] == "started" for event in events), 1)
            terminals = [event for event in events if event["event"] in {"completed", "failed", "cancelled"}]
            self.assertEqual(len(terminals), 1)
            completed_event = terminals[0]
            self.assertEqual(completed_event["event"], "completed")
            self.assertRegex(completed_event["package_sha256"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(
                [resource["kind"] for resource in completed_event["resources"]],
                ["subtitle_text_track", "word_timeline"],
            )
            self.assertNotIn("output", completed_event)
            self.assertNotIn(str(output), completed.stdout)
            self.assertEqual(completed.stderr, "")

    def test_failure_event_uses_stable_code_and_redacts_provider_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "lesson.listenpkg"
            observed = root / "provider-observed.txt"
            media = ROOT / "tests" / "fixtures" / "single-audio-media.json"
            arguments = [
                sys.executable, "-m", "listen_gen", "package", "from-media", str(media),
                "--output", str(output), "--provider", "command", "--command", sys.executable,
                "--command-arg", str(self.command), "--command-arg", "fail",
                "--command-arg", "{media}", "--command-arg", str(self.fixture),
                "--command-arg", str(observed), "--ffprobe-command", str(self.ffprobe),
                "--ffmpeg-command", str(self.ffmpeg), "--title", "Failure",
                "--media-kind", "audio", "--duration-ms", "2200",
                "--created-at-ms", "1785542400000", "--machine-events",
            ]
            completed = subprocess.run(
                arguments, cwd=ROOT, env=self.environment(), capture_output=True, text=True
            )
            self.assertEqual(completed.returncode, 2)
            events = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual(events[-1]["event"], "failed")
            self.assertEqual(events[-1]["code"], "provider_failed")
            for private_value in (
                "provider-secret-must-not-leak", "raw_response", str(self.command),
                str(media), str(output), str(observed),
            ):
                self.assertNotIn(private_value, completed.stdout)
            self.assertEqual(completed.stderr, "")

    def _wait_for_event(self, process: subprocess.Popen[str], name: str) -> list[dict[str, object]]:
        assert process.stdout is not None
        events = []
        while True:
            line = process.stdout.readline()
            self.assertNotEqual(line, "", "machine stream ended before expected event")
            event = json.loads(line)
            events.append(event)
            if event["event"] == name:
                return events

    def _wait_for_file(self, path: Path) -> None:
        deadline = time.monotonic() + 2
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(path.exists(), f"expected subprocess observation {path}")

    def test_sigterm_cancels_provider_descendants_and_cleans_temporary_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "existing.listenpkg"
            output.write_bytes(b"existing-package")
            observed = root / "provider-observed.txt"
            media = ROOT / "tests" / "fixtures" / "single-audio-media.json"
            arguments = [
                sys.executable, "-m", "listen_gen", "package", "from-media", str(media),
                "--output", str(output), "--provider", "command", "--command", sys.executable,
                "--command-arg", str(self.command), "--command-arg", "spawn-child",
                "--command-arg", "{media}", "--command-arg", str(self.fixture),
                "--command-arg", str(observed), "--ffprobe-command", str(self.ffprobe),
                "--ffmpeg-command", str(self.ffmpeg), "--title", "Cancel",
                "--media-kind", "audio", "--duration-ms", "2200",
                "--created-at-ms", "1785542400000", "--machine-events",
            ]
            process = subprocess.Popen(
                arguments, cwd=ROOT, env=self.environment(), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            )
            events = self._wait_for_event(process, "phase")
            while events[-1].get("phase") != "transcribing":
                events.extend(self._wait_for_event(process, "phase"))
            self._wait_for_file(observed)
            normalized_audio = Path(observed.read_text(encoding="utf-8"))
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
            events.extend(json.loads(line) for line in stdout.splitlines())
            self.assertEqual(process.returncode, 128 + signal.SIGTERM)
            self.assertEqual(events[-1]["event"], "cancelled")
            self.assertEqual(sum(event["event"] == "cancelled" for event in events), 1)
            self.assertEqual(output.read_bytes(), b"existing-package")
            self.assertFalse(normalized_audio.exists())
            time.sleep(0.6)
            self.assertFalse(observed.with_suffix(".child").exists())
            self.assertEqual(stderr, "")

    def test_sigint_cancels_ffmpeg_descendants_and_removes_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media.json"
            source = json.loads(
                (ROOT / "tests" / "fixtures" / "single-audio-media.json").read_text(encoding="utf-8")
            )
            source["ffmpeg_mode"] = "spawn-child"
            media.write_text(json.dumps(source), encoding="utf-8")
            output = root / "lesson.listenpkg"
            observation = root / "ffmpeg-observed.json"
            arguments = [
                sys.executable, "-m", "listen_gen", "package", "from-media", str(media),
                "--output", str(output), "--provider", "command", "--command", sys.executable,
                "--command-arg", str(self.command), "--command-arg", "success",
                "--command-arg", "{media}", "--command-arg", str(self.fixture),
                "--command-arg", str(root / "provider.txt"), "--ffprobe-command", str(self.ffprobe),
                "--ffmpeg-command", str(self.ffmpeg), "--title", "Cancel",
                "--media-kind", "audio", "--duration-ms", "2200",
                "--created-at-ms", "1785542400000", "--machine-events",
            ]
            process = subprocess.Popen(
                arguments,
                cwd=ROOT,
                env=self.environment(LISTEN_GEN_TEST_FFMPEG_OBSERVATION=str(observation)),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            events = self._wait_for_event(process, "phase")
            while events[-1].get("phase") != "normalizing_audio":
                events.extend(self._wait_for_event(process, "phase"))
            self._wait_for_file(observation)
            temporary_output = Path(json.loads(observation.read_text(encoding="utf-8"))[-1])
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=5)
            events.extend(json.loads(line) for line in stdout.splitlines())
            self.assertEqual(process.returncode, 128 + signal.SIGINT)
            self.assertEqual(events[-1]["event"], "cancelled")
            self.assertFalse(output.exists())
            self.assertFalse(temporary_output.exists())
            time.sleep(0.6)
            self.assertFalse(observation.with_suffix(".child").exists())
            self.assertEqual(stderr, "")


if __name__ == "__main__":
    unittest.main()

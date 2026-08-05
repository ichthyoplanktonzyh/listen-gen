from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CommandArgvSpellingTests(unittest.TestCase):
    """The command provider's argv must survive a programmatic caller.

    The real incident: listen-app stores the provider argv as a JSON array in
    ``LISTEN_GEN_PROVIDER_ARGUMENTS`` and splats it into ``argv``. Written the
    obvious way -- ``["--command-arg", "--model", ...]`` -- argparse reads
    ``--model`` as an option rather than as the value of ``--command-arg`` and
    exits 2 with "expected one argument", before any machine event is written.
    The supervisor sees a process that produced no protocol at all, and the
    user is told the generator spoke an unexpected protocol; nothing anywhere
    names the actual cause, which is an argparse quoting rule.

    ``--command-argv-json`` removes the rule: one argument, any contents.
    """

    media = ROOT / "tests" / "fixtures" / "single-audio-media.json"
    command = ROOT / "tests" / "fixtures" / "argv_echo_command.py"
    fixture = ROOT / "tests" / "fixtures" / "sample.asr.json"
    ffprobe = ROOT / "tests" / "fixtures" / "fake_ffprobe.py"
    ffmpeg = ROOT / "tests" / "fixtures" / "fake_ffmpeg.py"

    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        return environment

    def run_cli(self, provider_argv: list[str], output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "listen_gen",
                "package",
                "from-media",
                str(self.media),
                "--output",
                str(output),
                "--provider",
                "command",
                "--command",
                sys.executable,
                *provider_argv,
                "--ffprobe-command",
                str(self.ffprobe),
                "--ffmpeg-command",
                str(self.ffmpeg),
                "--title",
                "Lesson",
                "--media-kind",
                "audio",
                "--duration-ms",
                "2200",
                "--created-at-ms",
                "1785542400000",
                "--machine-events",
            ],
            capture_output=True,
            text=True,
            env=self.environment(),
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

    def wrapper_argv(self, observation: Path) -> list[str]:
        """What the wrapper was actually handed, as it recorded it."""
        return json.loads(observation.read_text(encoding="utf-8"))["argv"]

    def test_json_argv_carries_items_that_start_with_a_dash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observation = Path(directory) / "argv.json"
            completed = self.run_cli(
                [
                    "--command-argv-json",
                    json.dumps(
                        [
                            str(self.command),
                            "{media}",
                            str(self.fixture),
                            str(observation),
                            "--model",
                            "base",
                        ]
                    ),
                ],
                Path(directory) / "lesson.listenpkg",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(self.terminal_event(completed.stdout)["event"], "completed")
            # The whole point: the flag reached the wrapper.
            self.assertEqual(self.wrapper_argv(observation)[-2:], ["--model", "base"])

    def test_json_argv_matches_the_joined_command_arg_spelling(self) -> None:
        # Same argv, two spellings. Comparing what the wrapper recorded proves
        # the arguments were identical, not merely that both runs succeeded.
        with tempfile.TemporaryDirectory() as directory:
            joined_observation = Path(directory) / "joined-argv.json"
            encoded_observation = Path(directory) / "encoded-argv.json"
            first = self.run_cli(
                [
                    "--command-arg",
                    str(self.command),
                    "--command-arg",
                    "{media}",
                    "--command-arg",
                    str(self.fixture),
                    "--command-arg",
                    str(joined_observation),
                    "--command-arg=--model",
                    "--command-arg",
                    "base",
                ],
                Path(directory) / "joined.listenpkg",
            )
            second = self.run_cli(
                [
                    "--command-argv-json",
                    json.dumps(
                        [
                            str(self.command),
                            "{media}",
                            str(self.fixture),
                            str(encoded_observation),
                            "--model",
                            "base",
                        ]
                    ),
                ],
                Path(directory) / "encoded.listenpkg",
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(
                self.wrapper_argv(joined_observation)[-2:],
                self.wrapper_argv(encoded_observation)[-2:],
            )
            self.assertEqual(
                self.terminal_event(first.stdout)["package_sha256"],
                self.terminal_event(second.stdout)["package_sha256"],
            )

    def test_separate_command_arg_items_still_fail_the_documented_way(self) -> None:
        # Pinning the trap itself: this is the spelling that looks right and is
        # not. It must keep failing loudly rather than silently dropping the
        # flag, which would send a differently-configured model to the wrapper.
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_cli(
                [
                    "--command-arg",
                    str(self.command),
                    "--command-arg",
                    "{media}",
                    "--command-arg",
                    "--model",
                    "--command-arg",
                    "base",
                ],
                Path(directory) / "lesson.listenpkg",
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("--command-arg", completed.stderr)

    def test_both_spellings_at_once_is_a_typed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_cli(
                [
                    "--command-arg",
                    str(self.command),
                    "--command-argv-json",
                    json.dumps([str(self.command), "{media}"]),
                ],
                Path(directory) / "lesson.listenpkg",
            )
            terminal = self.terminal_event(completed.stdout)
            self.assertEqual(terminal["event"], "failed")
            self.assertEqual(terminal["code"], "invalid_input")

    def test_malformed_json_argv_is_a_typed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_cli(
                ["--command-argv-json", "[not json"],
                Path(directory) / "lesson.listenpkg",
            )
            terminal = self.terminal_event(completed.stdout)
            self.assertEqual(terminal["event"], "failed")
            self.assertEqual(terminal["code"], "invalid_input")

    def test_json_argv_that_is_not_a_string_array_is_a_typed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_cli(
                ["--command-argv-json", json.dumps([str(self.command), 7])],
                Path(directory) / "lesson.listenpkg",
            )
            terminal = self.terminal_event(completed.stdout)
            self.assertEqual(terminal["event"], "failed")
            self.assertEqual(terminal["code"], "invalid_input")


if __name__ == "__main__":
    unittest.main()

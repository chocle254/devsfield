"""Contract tests for selected-duration video assembly."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pipeline import video_assembler  # noqa: E402


class VideoAssemblerDurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_merge_uses_visual_duration_not_shortest_audio(self):
        commands = []

        async def run_command(cmd, **_kwargs):
            commands.append(cmd)

        with patch.object(video_assembler, "run_subprocess", run_command):
            await video_assembler._merge_segment(
                "screen.mp4", "voice.mp3", "merged.mp4", 60.0)

        command = commands[0]
        self.assertNotIn("-shortest", command)
        self.assertEqual(command[command.index("-t") + 1], "60.000")
        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn("apad=pad_dur=60.000", filter_graph)

    async def test_merge_time_fits_a_short_narration_to_its_visual_beat(self):
        commands = []

        async def run_command(cmd, **_kwargs):
            commands.append(cmd)

        with patch.object(video_assembler, "run_subprocess", run_command):
            await video_assembler._merge_segment(
                "screen.mp4", "voice.mp3", "merged.mp4", 60.0, 48.0)

        filter_graph = commands[0][commands[0].index("-filter_complex") + 1]
        self.assertIn("atempo=0.80000", filter_graph)

    async def test_assemble_rejects_narration_far_shorter_than_screen_time(self):
        async def duration(path):
            return 15.0 if path == "short.mp3" else 60.0

        async def split_clip(*args):
            return args[-1]

        with (
            patch.object(video_assembler, "get_duration", duration),
            patch.object(video_assembler, "split_clip", split_clip),
            patch.object(video_assembler.os.path, "exists", lambda path: path == "short.mp3"),
        ):
            with self.assertRaisesRegex(RuntimeError, "mismatched narration timeline"):
                await video_assembler.assemble(
                    "recording.mp4",
                    [{
                        "segment_id": 1,
                        "start_time": 0.0,
                        "end_time": 60.0,
                        "audio_path": "short.mp3",
                    }],
                    None,
                    "job",
                    target_duration=60.0,
                )

    async def test_current_pipeline_rejects_a_segment_without_narration(self):
        async def split_clip(*args):
            return args[-1]

        with (
            patch.object(video_assembler, "split_clip", split_clip),
            patch.object(video_assembler.os.path, "exists", lambda _path: False),
        ):
            with self.assertRaisesRegex(RuntimeError, "no validated narration asset"):
                await video_assembler.assemble(
                    "recording.mp4",
                    [{
                        "segment_id": 1,
                        "start_time": 0.0,
                        "end_time": 60.0,
                        "audio_path": None,
                    }],
                    None,
                    "job",
                    target_duration=60.0,
                )

    async def test_assemble_reports_selected_duration_after_three_visual_beats(self):
        durations = {
            "voice1.mp3": 60.0,
            "voice2.mp3": 60.0,
            "voice3.mp3": 60.0,
            "/tmp/final_job.mp4": 180.0,
        }
        merge_targets = []

        async def duration(path):
            return durations.get(path, 60.0)

        async def split_clip(*args):
            return args[-1]

        async def fit_video(*args):
            return args[-1]

        async def merge_segment(*args):
            merge_targets.append(args[3])
            return args[2]

        async def concat_segments(*args):
            return args[1]

        with (
            patch.object(video_assembler, "get_duration", duration),
            patch.object(video_assembler, "split_clip", split_clip),
            patch.object(video_assembler, "fit_video_to_duration", fit_video),
            patch.object(video_assembler, "_merge_segment", merge_segment),
            patch.object(video_assembler, "concat_segments", concat_segments),
            patch.object(video_assembler.os.path, "exists", lambda path: path.endswith(".mp3")),
        ):
            result = await video_assembler.assemble(
                "recording.mp4",
                [
                    {"segment_id": 1, "start_time": 0, "end_time": 60, "audio_path": "voice1.mp3"},
                    {"segment_id": 2, "start_time": 60, "end_time": 120, "audio_path": "voice2.mp3"},
                    {"segment_id": 3, "start_time": 120, "end_time": 180, "audio_path": "voice3.mp3"},
                ],
                None,
                "job",
                target_duration=180.0,
            )

        self.assertEqual(merge_targets, [60.0, 60.0, 60.0])
        self.assertEqual(result["actual_duration_seconds"], 180.0)
        self.assertEqual(result["voiced_segment_count"], 3)

    async def test_missing_title_holds_final_screen_state_to_selected_duration(self):
        durations = {
            "voice1.mp3": 59.0,
            "voice2.mp3": 59.0,
            "voice3.mp3": 59.0,
            "/tmp/final_job.mp4": 180.0,
        }
        merge_targets = []

        async def duration(path):
            return durations.get(path, 59.0)

        async def split_clip(*args):
            return args[-1]

        async def fit_video(*args):
            return args[-1]

        async def merge_segment(*args):
            merge_targets.append(args[3])
            return args[2]

        async def concat_segments(*args):
            return args[1]

        with (
            patch.object(video_assembler, "get_duration", duration),
            patch.object(video_assembler, "split_clip", split_clip),
            patch.object(video_assembler, "fit_video_to_duration", fit_video),
            patch.object(video_assembler, "_merge_segment", merge_segment),
            patch.object(video_assembler, "concat_segments", concat_segments),
            patch.object(video_assembler.os.path, "exists", lambda path: path.endswith(".mp3")),
        ):
            result = await video_assembler.assemble(
                "recording.mp4",
                [
                    {"segment_id": 1, "start_time": 0, "end_time": 59, "audio_path": "voice1.mp3"},
                    {"segment_id": 2, "start_time": 59, "end_time": 118, "audio_path": "voice2.mp3"},
                    {"segment_id": 3, "start_time": 118, "end_time": 177, "audio_path": "voice3.mp3"},
                ],
                None,
                "job",
                target_duration=180.0,
            )

        self.assertEqual(merge_targets, [59.0, 59.0, 62.0])
        self.assertEqual(result["actual_duration_seconds"], 180.0)
        self.assertEqual(
            result["assembly_contract_version"],
            video_assembler.ASSEMBLY_CONTRACT_VERSION,
        )


if __name__ == "__main__":
    unittest.main()

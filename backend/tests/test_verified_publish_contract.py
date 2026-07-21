"""Regression tests for the duration/audio publication contract."""
import sys
import tempfile
import types
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# These focused contract tests do not make B2 calls. Keep them runnable in a
# lightweight local test environment where the optional Genblaze SDK extras
# are not installed, while using the real modules when they are present.
if "genblaze_core" not in sys.modules:
    core = types.ModuleType("genblaze_core")
    core.ObjectStorageSink = object
    core.KeyStrategy = object
    sys.modules["genblaze_core"] = core
if "genblaze_s3" not in sys.modules:
    s3 = types.ModuleType("genblaze_s3")
    s3.S3StorageBackend = object
    sys.modules["genblaze_s3"] = s3

from models import JobResult  # noqa: E402
from pipeline import resume_store, storage, video_assembler  # noqa: E402


class VerifiedPublishContractTests(unittest.TestCase):
    def test_fractional_verified_duration_is_a_valid_result(self):
        result = JobResult(job_id="job", status="complete", duration_seconds=180.03)
        self.assertEqual(result.duration_seconds, 180.03)

    def test_upload_guard_rejects_missing_voice_or_duration_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            voice = Path(temp_dir) / "voice.mp3"
            voice.write_bytes(b"not-probed-here")
            clips = [{"segment_id": 1, "voice_path": str(voice)}]

            storage._validate_verified_upload(clips, 180, 180.02, 1)
            with self.assertRaisesRegex(ValueError, "missing verified duration"):
                storage._validate_verified_upload(clips, 180, None, 1)
            with self.assertRaisesRegex(ValueError, "missing narration"):
                storage._validate_verified_upload(clips, 180, 180.02, 0)

    def test_v3_duration_allowance_is_small(self):
        self.assertEqual(video_assembler.duration_tolerance(180), 1.8)
        self.assertEqual(video_assembler.duration_tolerance(300), 3.0)

    def test_resume_drops_a_voice_checkpoint_without_an_audio_asset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recording = Path(temp_dir) / "recording.mp4"
            recording.write_bytes(b"recording")
            checkpoints = {
                "context": {},
                "plan": {},
                "recording": {"video_path": str(recording)},
                "script_segments": [{"segment_id": 1, "text": "Hello"}],
                "title_card_path": None,
                "voiced_segments": [{"segment_id": 1, "audio_path": None}],
            }
            kept_steps, kept = resume_store.validate_checkpoints(
                [
                    "github_reader", "app_browser", "script_writer",
                    "image_generator", "voice_generator",
                ],
                checkpoints,
            )

        self.assertEqual(
            kept_steps,
            ["github_reader", "app_browser", "script_writer", "image_generator"],
        )
        self.assertNotIn("voiced_segments", kept)


if __name__ == "__main__":
    unittest.main()

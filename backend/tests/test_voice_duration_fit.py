"""Tests for voice_generator's pre-assembly duration-fit retry.

These cover the actual bug being fixed: script_writer sizes narration word
counts assuming a fixed 2.4 words/second speaking pace, but the real TTS
voice can speak faster or slower than that, so a clip can come out clearly
shorter than its segment's planned on-screen time even though the word count
matched the plan. Previously that mismatch was only ever caught at
video_assembler's hard VOICE_DURATION_TOLERANCE gate, failing the whole job.
voice_generator now retries a rewritten, re-synthesized line first.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pipeline import voice_generator  # noqa: E402


class DurationFitTests(unittest.IsolatedAsyncioTestCase):
    async def test_clip_within_tolerance_is_never_resized(self):
        """A clip that already lands close enough to its segment's on-screen
        time must not trigger any rewrite — the common, healthy case."""
        resize_calls = []

        async def fake_resize(*args, **kwargs):
            resize_calls.append(args)
            return "should not be called"

        async def fake_validate(path):
            return 58.0  # within [45, 75] for a 60s visual segment

        async def fake_materialize(url, path, timeout=60.0):
            return None

        def fake_generate_one(job_id, segment_id, text, model, voice_id, api_key):
            return "https://fake/asset.mp3"

        with (
            patch.object(voice_generator, "resize_segment_text", fake_resize),
            patch.object(voice_generator, "_validate_audio_asset", fake_validate),
            patch.object(voice_generator, "materialize_asset", fake_materialize),
            patch.object(voice_generator, "_generate_one", fake_generate_one),
            patch.dict("os.environ", {"GMI_CLOUD_API_KEY": "test-key"}),
        ):
            result = await voice_generator.generate_segment_voices(
                [{
                    "segment_id": 1,
                    "text": "A short narration line about the dashboard.",
                    "start_time": 0.0,
                    "end_time": 60.0,
                    "feature": "dashboard",
                }],
                "job1", tone="demo", context={"repo_name": "Demo"},
            )

        self.assertEqual(resize_calls, [])
        self.assertEqual(result[0]["audio_path"], "/tmp/voice_job1_seg1.mp3")

    async def test_short_clip_is_rewritten_and_refit(self):
        """The exact reported bug: voice comes out shorter than the video
        segment. One rewrite scaled to the *measured* speaking rate should
        fix it without failing the job."""
        resize_calls = []
        generate_calls = []
        durations = iter([20.0, 57.0])  # first attempt short, retry lands in range

        async def fake_resize(text, target_words, repo_name, tone, feature, api_key):
            resize_calls.append(target_words)
            return "a longer rewritten narration line"

        async def fake_validate(path):
            return next(durations)

        async def fake_materialize(url, path, timeout=60.0):
            return None

        def fake_generate_one(job_id, segment_id, text, model, voice_id, api_key):
            generate_calls.append(text)
            return "https://fake/asset.mp3"

        with (
            patch.object(voice_generator, "resize_segment_text", fake_resize),
            patch.object(voice_generator, "_validate_audio_asset", fake_validate),
            patch.object(voice_generator, "materialize_asset", fake_materialize),
            patch.object(voice_generator, "_generate_one", fake_generate_one),
            patch.dict("os.environ", {"GMI_CLOUD_API_KEY": "test-key"}),
        ):
            result = await voice_generator.generate_segment_voices(
                [{
                    "segment_id": 1,
                    "text": " ".join(["word"] * 48) + ".",
                    "start_time": 0.0,
                    "end_time": 60.0,
                    "feature": "dashboard",
                }],
                "job1", tone="demo", context={"repo_name": "Demo"},
            )

        # 48 words / 20.0s measured = 2.4 wps -> target_words = round(60*2.4)
        self.assertEqual(resize_calls, [144])
        self.assertEqual(len(generate_calls), 2)
        self.assertEqual(result[0]["text"], "a longer rewritten narration line")
        self.assertEqual(result[0]["audio_path"], "/tmp/voice_job1_seg1_fit1.mp3")

    async def test_gives_up_after_retry_budget_without_raising(self):
        """If a segment still doesn't fit after DURATION_FIT_RETRIES attempts,
        voice_generator must hand back its best attempt rather than raising —
        video_assembler's hard gate is the intended final word, not this
        stage, so a job that truly can't converge fails there with its own
        clear error instead of a confusing one from here."""
        generate_calls = []
        durations = iter([10.0, 15.0, 18.0])  # never reaches the [45, 75] band

        async def fake_resize(text, target_words, repo_name, tone, feature, api_key):
            return f"rewritten x{target_words}"

        async def fake_validate(path):
            return next(durations)

        async def fake_materialize(url, path, timeout=60.0):
            return None

        def fake_generate_one(job_id, segment_id, text, model, voice_id, api_key):
            generate_calls.append(text)
            return "https://fake/asset.mp3"

        with (
            patch.object(voice_generator, "resize_segment_text", fake_resize),
            patch.object(voice_generator, "_validate_audio_asset", fake_validate),
            patch.object(voice_generator, "materialize_asset", fake_materialize),
            patch.object(voice_generator, "_generate_one", fake_generate_one),
            patch.dict("os.environ", {"GMI_CLOUD_API_KEY": "test-key"}),
        ):
            result = await voice_generator.generate_segment_voices(
                [{
                    "segment_id": 1,
                    "text": " ".join(["word"] * 24) + ".",
                    "start_time": 0.0,
                    "end_time": 60.0,
                    "feature": "dashboard",
                }],
                "job1", tone="demo", context={"repo_name": "Demo"},
            )

        self.assertEqual(len(generate_calls), 1 + voice_generator.DURATION_FIT_RETRIES)
        self.assertEqual(result[0]["audio_path"], "/tmp/voice_job1_seg1_fit2.mp3")


if __name__ == "__main__":
    unittest.main()

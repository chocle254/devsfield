"""Checks for script_writer's length-repair pass.

Reproduces the exact failure this was written for: a segment whose planned
screen time needs ~86 words of narration (36s at 2.4 words/sec) but the
model's one-shot batched response gave it only ~38 — the gap that showed up
downstream as "Voiceover for segment 2 is 15.8s, but its planned screen time
is 36.0s. Refusing to publish a mismatched narration timeline." These tests
pin down that the drift gets caught and fixed *before* TTS generation, not
discovered for the first time at that hard publish-time gate.
"""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pipeline import script_writer  # noqa: E402


def _fake_response(status_code: int, payload: dict):
    resp = type("FakeResponse", (), {})()
    resp.status_code = status_code
    resp.text = json.dumps(payload)
    resp.json = lambda: payload
    return resp


def _chat_payload(text_by_id: dict) -> dict:
    content = json.dumps([
        {"segment_id": sid, "text": text, "screen_note": ""}
        for sid, text in text_by_id.items()
    ])
    return {"choices": [{"message": {"content": content}}]}


class LengthRepairDetectionTests(unittest.TestCase):
    def test_far_too_short_needs_repair(self):
        self.assertTrue(script_writer._needs_length_repair(" ".join(["w"] * 38), 86))

    def test_within_corridor_is_left_alone(self):
        self.assertFalse(script_writer._needs_length_repair(" ".join(["w"] * 80), 86))

    def test_empty_text_needs_repair(self):
        self.assertTrue(script_writer._needs_length_repair("", 86))

    def test_far_too_long_needs_repair(self):
        self.assertTrue(script_writer._needs_length_repair(" ".join(["w"] * 200), 86))


class PadOrTrimConvergenceTests(unittest.TestCase):
    def test_pad_closes_a_large_gap(self):
        result = script_writer._pad_or_trim("This shows the live forecast.", 86, "the forecast view")
        self.assertFalse(script_writer._needs_length_repair(result, 86))

    def test_pad_handles_completely_empty_text(self):
        result = script_writer._pad_or_trim("", 86, "the dashboard")
        self.assertFalse(script_writer._needs_length_repair(result, 86))

    def test_trim_closes_a_large_overage(self):
        long_text = ". ".join(["This is a sentence about the product"] * 30) + "."
        result = script_writer._pad_or_trim(long_text, 86, "the dashboard")
        self.assertFalse(script_writer._needs_length_repair(result, 86))

    def test_pad_never_repeats_the_same_filler_back_to_back(self):
        result = script_writer._pad_or_trim("", 40, "the button")
        sentences = [s for s in result.split(".") if s.strip()]
        for a, b in zip(sentences, sentences[1:]):
            self.assertNotEqual(a.strip(), b.strip())


class EndToEndRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_too_short_segment_gets_repaired_before_voice_generation(self):
        """Segment 2 is planned for 36s (needs ~86 words) but the main call
        only gives it ~38 — exactly the reported failure. The repair call
        should be triggered automatically and fix it."""
        segments = [
            {"segment_id": 1, "start_time": 0.0, "end_time": 10.0,
             "talking_point": "Landing page overview.", "feature": "overview"},
            {"segment_id": 2, "start_time": 10.0, "end_time": 46.0,
             "talking_point": "County forecast.", "feature": "county forecast"},
        ]
        main_text = {
            1: " ".join(["intro"] * 24),      # fits its ~24-word target
            2: " ".join(["short"] * 38),       # far short of its ~86-word target
        }
        repaired_text = {2: " ".join(["fixed"] * 87)}  # the repair call's answer

        main_response = _fake_response(200, _chat_payload(main_text))
        repair_response = _fake_response(200, _chat_payload(repaired_text))

        with patch("pipeline.script_writer._call_gmi_chat",
                   new=AsyncMock(side_effect=[main_response, repair_response])) as mock_call, \
             patch.dict("os.environ", {"GMI_CLOUD_API_KEY": "fake-key"}):
            result = await script_writer.write_segmented_script(
                {"repo_name": "pulsecast", "description": "", "readme": ""},
                segments, tone="pitch")

        self.assertEqual(mock_call.await_count, 2)  # main call + one repair call
        by_id = {seg["segment_id"]: seg for seg in result}
        self.assertEqual(script_writer._word_count(by_id[2]["text"]), 87)
        self.assertFalse(script_writer._needs_length_repair(by_id[2]["text"], 86))
        # Segment 1 was already fine and must be left untouched.
        self.assertEqual(by_id[1]["text"], main_text[1])

    async def test_repair_call_itself_failing_still_produces_a_valid_result(self):
        """If the repair call also fails (network-level), the deterministic
        pad/trim fallback must still guarantee a fit — the job can never
        hard-fail here."""
        segments = [
            {"segment_id": 2, "start_time": 0.0, "end_time": 36.0,
             "talking_point": "County forecast.", "feature": "county forecast"},
        ]
        main_response = _fake_response(200, _chat_payload({2: " ".join(["short"] * 38)}))
        failed_repair_response = _fake_response(500, {"error": "down"})

        with patch("pipeline.script_writer._call_gmi_chat",
                   new=AsyncMock(side_effect=[main_response, failed_repair_response])), \
             patch.dict("os.environ", {"GMI_CLOUD_API_KEY": "fake-key"}):
            result = await script_writer.write_segmented_script(
                {"repo_name": "pulsecast", "description": "", "readme": ""},
                segments, tone="pitch")

        self.assertFalse(script_writer._needs_length_repair(result[0]["text"], 86))


if __name__ == "__main__":
    unittest.main()

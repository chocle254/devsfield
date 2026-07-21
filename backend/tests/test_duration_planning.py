"""Focused checks for requested demo-duration allocation."""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pipeline import demo_planner, script_writer  # noqa: E402


class ScriptDurationTests(unittest.TestCase):
    def test_long_segments_keep_a_duration_scaled_word_budget(self):
        segment = {"start_time": 0.0, "end_time": 60.0}

        self.assertEqual(
            script_writer._target_words(segment),
            round(60.0 * script_writer.WORDS_PER_SECOND),
        )
        self.assertGreater(script_writer._target_words(segment), 45)


class PlannerDurationTests(unittest.TestCase):
    def test_duration_beat_minimums_cover_three_and_five_minutes(self):
        self.assertEqual(demo_planner._minimum_beats_for_duration(177), 3)
        self.assertEqual(demo_planner._minimum_beats_for_duration(297), 5)

    def test_five_minute_budget_adds_safe_capacity_and_uses_every_second(self):
        original_steps = [{"action": "click", "target": "Show demo"}]
        beats = [
            {
                "priority": index + 1,
                "feature": f"Feature {index + 1}",
                "route": "/",
                "seconds": 20,
                "interaction_steps": original_steps,
            }
            for index in range(3)
        ]

        allocated = demo_planner._use_full_time_budget(beats, 297)

        self.assertGreaterEqual(len(allocated), 5)
        self.assertEqual(sum(beat["seconds"] for beat in allocated), 297)
        self.assertTrue(all(
            demo_planner.MIN_BEAT_SECONDS <= beat["seconds"] <= demo_planner.MAX_BEAT_SECONDS
            for beat in allocated
        ))
        self.assertTrue(all(
            step["action"] == "click"
            for beat in allocated
            for step in beat["interaction_steps"]
        ))

    def test_model_free_fallback_fills_a_five_minute_selection(self):
        context = {
            "repo_name": "Demo app",
            "description": "A compact demo app.",
            "detected_routes": ["/"],
            "interaction_catalog": [{
                "route": "/",
                "sections": ["Overview", "Results"],
                "controls": [{"role": "button", "name": "Show demo"}],
            }],
        }

        with patch.dict(os.environ, {"GMI_CLOUD_API_KEY": ""}):
            plan = asyncio.run(demo_planner.plan_demo(context, 300, False))

        self.assertGreaterEqual(len(plan["beats"]), 5)
        self.assertEqual(sum(beat["seconds"] for beat in plan["beats"]), 297)
        self.assertTrue(all(
            demo_planner.MIN_BEAT_SECONDS <= beat["seconds"] <= demo_planner.MAX_BEAT_SECONDS
            for beat in plan["beats"]
        ))

    def test_model_prompt_requires_enough_five_minute_beats(self):
        captured_payload = {}

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "choices": [{"message": {"content": """
                    {"beats": [
                      {"priority": 1, "feature": "Overview", "route": "/", "seconds": 20},
                      {"priority": 2, "feature": "Results", "route": "/", "seconds": 20},
                      {"priority": 3, "feature": "Summary", "route": "/", "seconds": 20}
                    ], "needs_login": false, "app_summary": "Demo"}
                    """}}]
                }

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                captured_payload.update(kwargs["json"])
                return FakeResponse()

        context = {
            "repo_name": "Demo app",
            "description": "A compact demo app.",
            "detected_routes": ["/"],
            "interaction_catalog": [],
        }
        with patch.dict(os.environ, {"GMI_CLOUD_API_KEY": "test-key"}), patch.object(
            demo_planner.httpx, "AsyncClient", FakeClient
        ):
            plan = asyncio.run(demo_planner.plan_demo(context, 300, False))

        prompt = captured_payload["messages"][1]["content"]
        self.assertIn("Use BETWEEN 5 AND 10 beats.", prompt)
        self.assertEqual(sum(beat["seconds"] for beat in plan["beats"]), 297)


if __name__ == "__main__":
    unittest.main()

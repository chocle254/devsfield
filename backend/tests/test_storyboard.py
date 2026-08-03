"""Checks for the developer-authored storyboard bypass in demo_planner.

A storyboard lets the developer script exact beats/steps instead of letting
the LLM guess from the README. These tests pin down the two properties that
matter most: (1) providing a storyboard must skip the network call to the
planning LLM entirely, and (2) the storyboard still goes through the same
safety normalizer an AI-generated plan does — a developer typo or careless
copy-paste can't smuggle a destructive action into the recording.
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pipeline import demo_planner  # noqa: E402


def _context(**overrides):
    base = {
        "repo_name": "demo-app",
        "description": "A demo app.",
        "has_auth": False,
        "interaction_catalog": [],
    }
    base.update(overrides)
    return base


class StoryboardBypassTests(unittest.TestCase):
    def test_storyboard_skips_the_planning_llm(self):
        """No network call should happen at all when a storyboard is given."""
        storyboard = [
            {"route": "/", "talking_point": "Landing page.", "seconds": 20,
             "interaction_steps": []},
        ]
        with patch("httpx.AsyncClient") as mock_client:
            plan = asyncio.run(demo_planner.plan_demo(
                _context(), 60, has_credentials=False, storyboard=storyboard))
        mock_client.assert_not_called()
        # MIN_BEATS (3) applies regardless of how many scenes the developer
        # wrote — a single scene gets cloned up to fill it, same as the AI
        # path. What matters here is that no LLM call happened and every
        # resulting beat still traces back to the one scene provided.
        self.assertGreaterEqual(len(plan["beats"]), 3)
        self.assertTrue(all(beat["route"] == "/" for beat in plan["beats"]))

    def test_storyboard_route_is_trusted_even_if_not_in_detected_routes(self):
        """Unlike the LLM path, a developer's own route isn't forced to '/' —
        static route detection from the repo can easily miss dynamic routes
        the developer knows exist."""
        storyboard = [
            {"route": "/dashboard/reports", "talking_point": "Reports.",
             "interaction_steps": []},
        ]
        context = _context(detected_routes=["/"])  # "/dashboard/reports" absent
        plan = asyncio.run(demo_planner.plan_demo(
            context, 60, has_credentials=False, storyboard=storyboard))
        self.assertEqual(plan["beats"][0]["route"], "/dashboard/reports")

    def test_storyboard_still_runs_through_the_safety_normalizer(self):
        """A destructive action must be stripped even when hand-authored."""
        storyboard = [
            {"route": "/settings", "seconds": 20, "interaction_steps": [
                {"action": "click", "target": "Delete account",
                 "expected_result": ""},
            ]},
        ]
        plan = asyncio.run(demo_planner.plan_demo(
            _context(), 60, has_credentials=False, storyboard=storyboard))
        self.assertEqual(plan["beats"][0]["interaction_steps"], [])

    def test_storyboard_keeps_safe_steps_intact(self):
        storyboard = [
            {"route": "/tasks", "seconds": 25, "talking_point": "Add a task.",
             "interaction_steps": [
                 {"action": "type", "target": "Task name", "value": "Plan launch",
                  "expected_result": ""},
                 {"action": "click", "target": "Add task", "value": None,
                  "expected_result": "Plan launch"},
             ]},
        ]
        plan = asyncio.run(demo_planner.plan_demo(
            _context(), 60, has_credentials=False, storyboard=storyboard))
        steps = plan["beats"][0]["interaction_steps"]
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["action"], "type")
        self.assertEqual(steps[1]["expected_result"], "Plan launch")

    def test_storyboard_fills_the_full_time_budget(self):
        """A short single-beat storyboard for a long video should still get
        cloned/stretched to occupy the requested duration, same as the AI
        path — otherwise a 5-minute request with one scripted beat would
        render a mostly-static video."""
        storyboard = [
            {"route": "/", "seconds": 20, "talking_point": "Overview.",
             "interaction_steps": []},
        ]
        video_length = 300  # requires >=5 beats per _minimum_beats_for_duration
        usable = video_length - demo_planner.RESERVED_SECONDS
        plan = asyncio.run(demo_planner.plan_demo(
            _context(), video_length, has_credentials=False, storyboard=storyboard))
        self.assertGreaterEqual(len(plan["beats"]), 5)
        self.assertEqual(sum(b["seconds"] for b in plan["beats"]), usable)

    def test_empty_storyboard_falls_back_to_ai_planning(self):
        """An empty list is treated the same as not providing one at all."""
        with patch("os.environ.get", return_value=None):
            plan = asyncio.run(demo_planner.plan_demo(
                _context(), 60, has_credentials=False, storyboard=[]))
        self.assertTrue(len(plan["beats"]) >= 1)

    def test_needs_login_requires_both_auth_and_credentials(self):
        storyboard = [{"route": "/", "interaction_steps": []}]
        plan_no_creds = asyncio.run(demo_planner.plan_demo(
            _context(has_auth=True), 60, has_credentials=False, storyboard=storyboard))
        plan_with_creds = asyncio.run(demo_planner.plan_demo(
            _context(has_auth=True), 60, has_credentials=True, storyboard=storyboard))
        self.assertFalse(plan_no_creds["needs_login"])
        self.assertTrue(plan_with_creds["needs_login"])


if __name__ == "__main__":
    unittest.main()

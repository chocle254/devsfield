"""Checks that a storyboard scroll step's target is actually used.

Before this fix, action="scroll" ignored `target` entirely and always did a
fixed 450px nudge — headings aren't in the interactive-controls scan, so
matching a "target" against a heading's text never had anywhere to go.
`_ground_planned_step` now carries the raw target text through as
`scroll_target` for `_perform_action` to look up with get_by_text() against
the whole page (not just interactive controls). This file only covers the
pure grounding step; the actual page.get_by_text()/scroll_into_view_if_needed
call in _perform_action needs a live/mocked page and isn't re-verified here.
"""
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pipeline import app_browser  # noqa: E402


class ScrollTargetGroundingTests(unittest.TestCase):
    def test_no_target_keeps_the_original_generic_nudge(self):
        grounded = app_browser._ground_planned_step({"action": "scroll"}, [])
        self.assertIsNone(grounded["scroll_target"])
        self.assertEqual(grounded["reason"], "Reveal the next learned section.")

    def test_target_text_is_carried_through_for_lookup(self):
        grounded = app_browser._ground_planned_step(
            {"action": "scroll", "target": "Storyboard"}, [])
        self.assertEqual(grounded["scroll_target"], "Storyboard")
        self.assertEqual(grounded["reason"], "Scroll to Storyboard.")

    def test_whitespace_only_target_falls_back_to_generic(self):
        grounded = app_browser._ground_planned_step(
            {"action": "scroll", "target": "   "}, [])
        self.assertIsNone(grounded["scroll_target"])
        self.assertEqual(grounded["reason"], "Reveal the next learned section.")

    def test_scroll_target_does_not_require_any_controls(self):
        """Headings/paragraphs never appear in the interactive-controls scan,
        so grounding a scroll step must not depend on the controls list at
        all (unlike click/type/select/toggle/press)."""
        grounded = app_browser._ground_planned_step(
            {"action": "scroll", "target": "Storyboard"}, controls=[])
        self.assertIsNotNone(grounded)


if __name__ == "__main__":
    unittest.main()

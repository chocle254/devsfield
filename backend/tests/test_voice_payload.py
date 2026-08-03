"""Regression test for the GMICloud TTS payload bug.

genblaze-gmicloud (as of 0.3.5) sends the narration text under the key
"prompt", but GMICloud's own TTS API requires "text" — every submission
failed with "invalid payload parameters: text (Required parameter is
missing)" regardless of which candidate model was tried, because it's one
bug hitting all three. voice_generator.py patches
GMICloudAudioProvider.prepare_payload on import to rename prompt->text for
audio steps; this test pins that behavior so a future genblaze-gmicloud
upgrade (or an accidental edit) can't silently reintroduce the bug.
"""
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from genblaze_core.models.enums import Modality  # noqa: E402
from genblaze_core.models.step import Step  # noqa: E402
from genblaze_gmicloud import GMICloudAudioProvider  # noqa: E402

# Importing voice_generator applies the prepare_payload monkeypatch as a
# side effect of module load.
from pipeline import voice_generator  # noqa: E402,F401


class VoicePayloadTests(unittest.TestCase):
    def setUp(self):
        self.provider = GMICloudAudioProvider(api_key="test-key-not-real")

    def _step(self, model: str) -> Step:
        return Step(
            step_id="s1",
            provider="gmicloud-audio",
            model=model,
            modality=Modality.AUDIO,
            prompt="Hello, this is a narration test.",
            params={"voice_id": "male-qn-qingse"},
        )

    def test_payload_sends_text_not_prompt(self):
        for model, voice_id in [(m, v[g]) for m, v in voice_generator._CANDIDATES
                                 for g in ("male", "female")]:
            with self.subTest(model=model, voice_id=voice_id):
                step = Step(
                    step_id="s1", provider="gmicloud-audio", model=model,
                    modality=Modality.AUDIO,
                    prompt="Hello, this is a narration test.",
                    params={"voice_id": voice_id},
                )
                payload = self.provider.prepare_payload(step)
                self.assertIn("text", payload)
                self.assertNotIn("prompt", payload)
                self.assertEqual(payload["text"], "Hello, this is a narration test.")
                self.assertEqual(payload["voice_id"], voice_id)

    def test_non_audio_steps_are_left_alone(self):
        """The patch is scoped to AUDIO steps only — it must not rename
        `prompt` for any other modality that happens to share the class."""
        step = Step(
            step_id="s1", provider="gmicloud-audio", model="minimax-tts-speech-01-turbo",
            modality=Modality.IMAGE, prompt="a red bicycle",
        )
        payload = self.provider.prepare_payload(step)
        self.assertIn("prompt", payload)
        self.assertNotIn("text", payload)


if __name__ == "__main__":
    unittest.main()

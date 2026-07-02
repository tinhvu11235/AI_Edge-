import unittest

from edge_assistant.config import TtsConfig
from edge_assistant.tts import MockTTS, TextNormalizer


class TextNormalizerTest(unittest.TestCase):
    def test_code_switching_rules(self):
        normalized = TextNormalizer().normalize(
            "He thong kiem tra BMS, loi Overcurrent tren nguon 24V"
        )
        self.assertIn("bi em et", normalized)
        self.assertIn("au vo co ran", normalized)
        self.assertIn("hai muoi bon von", normalized)

    def test_phrase_and_percent_rules(self):
        normalized = TextNormalizer().normalize("Ma loi CAN bus communication timeout, pin 15%")
        self.assertIn("can bot", normalized)
        self.assertIn("com mu ni cay shon", normalized)
        self.assertIn("thai ao", normalized)
        self.assertIn("muoi lam phan tram", normalized)

    def test_urgent_prosody_is_passed_to_tts_adapter(self):
        tts = MockTTS(TtsConfig(urgent_speed=1.2, urgent_pitch=1.1, urgent_energy=1.15))
        result = tts.synthesize("Ma loi CAN bus communication timeout", urgent=True)
        self.assertEqual(result.prosody.speed, 1.2)
        self.assertEqual(result.prosody.pitch, 1.1)
        self.assertEqual(result.prosody.energy, 1.15)
        self.assertEqual(result.prosody.style_id, "alert")


if __name__ == "__main__":
    unittest.main()

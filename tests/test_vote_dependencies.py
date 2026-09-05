"""Regression coverage for issue #5; never opens a browser or uses credentials."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "KarutaBot"))
import vote


class VoteDependencyTests(unittest.TestCase):
    def check_missing_dependency(self, frozen):
        messages = []
        with patch.object(sys, "frozen", frozen, create=True), patch.object(
            vote, "_create_driver",
            side_effect=ModuleNotFoundError(
                "No module named 'selenium.webdriver.chrome.options'"
            ),
        ) as create_driver, patch.object(vote.time, "sleep") as sleep:
            self.assertFalse(vote.auto_vote("unused", ui_log=messages.append))
        create_driver.assert_called_once()
        sleep.assert_not_called()
        return "\n".join(messages)

    def test_frozen_missing_module_requires_new_build_without_retry(self):
        output = self.check_missing_dependency(True)
        self.assertIn("packaged build is incomplete", output)
        self.assertNotIn("pip install", output)

    def test_source_missing_module_has_install_instruction_without_retry(self):
        output = self.check_missing_dependency(False)
        self.assertIn("pip install selenium", output)
        self.assertNotIn("packaged build is incomplete", output)


if __name__ == "__main__":
    unittest.main()

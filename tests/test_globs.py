import unittest
from agentforge.core.guardrails import matches_any_glob

class TestGlobs(unittest.TestCase):
    def test_matches(self):
        self.assertTrue(matches_any_glob(".github/workflows/ci.yml", [".github/workflows/**"]))
        self.assertTrue(matches_any_glob("scripts/build.sh", ["scripts/**"]))
        self.assertFalse(matches_any_glob("src/main.py", ["scripts/**"]))

if __name__ == "__main__":
    unittest.main()

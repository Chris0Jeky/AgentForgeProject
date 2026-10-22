import unittest
from agentforge.core.guardrails import matches_any_glob

class TestGlobs(unittest.TestCase):
    def test_matches(self):
        self.assertTrue(matches_any_glob(".github/workflows/ci.yml", [".github/workflows/**"]))
        self.assertTrue(matches_any_glob("scripts/build.sh", ["scripts/**"]))
        self.assertFalse(matches_any_glob("src/main.py", ["scripts/**"]))

class TestGlobPathFormats(unittest.TestCase):
    def test_native_windows_paths_keep_separator_normalization(self):
        self.assertTrue(matches_any_glob("docs\\allowed.txt", ["docs/allowed.txt"]))

    def test_git_paths_keep_backslashes_literal(self):
        self.assertFalse(matches_any_glob("docs\\allowed.txt", ["docs/allowed.txt"], git_path=True))
        self.assertTrue(matches_any_glob("docs\\allowed.txt", ["docs\\allowed.txt"], git_path=True))

if __name__ == "__main__":
    unittest.main()

import unittest
from agentforge.core.guardrails import sanitize_id

class TestSanitize(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(sanitize_id("a1"), "a1")
        self.assertEqual(sanitize_id("Issue 123"), "Issue-123")
        self.assertEqual(sanitize_id("  weird///name  "), "weird-name")

if __name__ == "__main__":
    unittest.main()

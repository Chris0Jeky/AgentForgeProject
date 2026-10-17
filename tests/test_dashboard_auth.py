from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agentforge.core.config import Policy, RepoConfig
from agentforge.core.server import serve_status
from server_test_support import dashboard, request, TOKEN


class TestDashboardAuth(unittest.TestCase):
    def test_actions_require_independent_token_and_local_origin(self):
        with dashboard(actions=True) as (_, _, port), patch(
            "agentforge.core.server.spawn_workspace", return_value=SimpleNamespace(agent="test")
        ) as spawn:
            status, html = request(port, "GET", "/")
            self.assertEqual(status, 200)
            self.assertNotIn(TOKEN, html)
            self.assertIn('outEl.textContent += fmtEvent(ev) + "\\n";', html)
            self.assertIn('outEl.textContent += msg.data + "\\n";', html)
            for auth in (None, "Bearer incorrect"):
                headers = {"Authorization": auth} if auth else {}
                self.assertEqual(request(port, "POST", "/api/workspaces/spawn", headers=headers)[0], 401)
            auth = {"Authorization": "Bearer " + TOKEN}
            for method in ("GET", "POST"):
                for extra in ({"Host": "rebound.example"}, {"Origin": "https://evil.example"}, {"Origin": "null"}):
                    status, _ = request(port, method, "/", headers={**auth, **extra})
                    self.assertEqual(status, 403)
            spawn.assert_not_called()
            status, _ = request(port, "POST", "/api/workspaces/spawn", headers={
                **auth, "Origin": f"http://127.0.0.1:{port}"
            }, body='{"agent":"test","task":"test"}')
            self.assertEqual(status, 200)
            spawn.assert_called_once()

    def test_actions_refuse_non_loopback_bind_before_startup(self):
        with patch("agentforge.core.server.ThreadingHTTPServer") as server:
            for host in ("0.0.0.0", "192.0.2.1", "rebound.example"):
                with self.subTest(host=host), self.assertRaises(ValueError):
                    serve_status(Path("."), RepoConfig(), Policy(), Path("state.json"), host=host, enable_actions=True)
            server.assert_not_called()

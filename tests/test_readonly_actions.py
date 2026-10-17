from contextlib import ExitStack
import unittest
from unittest.mock import patch

from server_test_support import dashboard, request, TOKEN


class TestReadonlyActions(unittest.TestCase):
    def test_default_serve_refuses_every_post_without_side_effects(self):
        paths = (
            "/api/workspaces/spawn", "/api/locks/acquire", "/api/locks/release",
            "/api/workflow/run", "/api/workflow/run_async", "/api/bootstrap/run_async",
            "/api/mcp/sync", "/api/mcp/profile/add", "/api/mcp/profile/remove",
            "/api/mcp/gateway/start", "/api/mcp/gateway/stop",
        )
        functions = (
            "spawn_workspace", "acquire_lock", "release_lock", "run_workflow", "run_bootstrap",
            "create_run", "docker_sync_profile", "docker_profile_server_add",
            "docker_profile_server_remove", "ensure_gateway_running", "stop_gateway",
        )
        with dashboard(cli=True) as (_, _, port), ExitStack() as stack:
            mocks = [stack.enter_context(patch("agentforge.core.server." + name)) for name in functions]
            for path in paths:
                with self.subTest(path=path):
                    self.assertEqual(request(port, "POST", path, body='{"agent":"test","task":"test","group":"test","server":"test","name":"test"}')[0], 403)
            for mock in mocks:
                mock.assert_not_called()

    def test_actions_validate_body_before_reading_or_dispatch(self):
        with dashboard(actions=True) as (_, _, port), patch("agentforge.core.server.spawn_workspace") as spawn:
            auth = {"Authorization": "Bearer " + TOKEN}
            for length, expected in (("-1", 400), ("invalid", 400), ("1048577", 413)):
                with self.subTest(length=length):
                    self.assertEqual(request(port, "POST", "/api/workspaces/spawn", headers={
                        **auth, "Content-Length": length
                    })[0], expected)
            for body in ("[1]", "not json"):
                self.assertEqual(request(port, "POST", "/api/workspaces/spawn", headers=auth, body=body)[0], 400)
            self.assertEqual(request(port, "POST", "/api/workspaces/spawn", headers={
                **auth, "Transfer-Encoding": "chunked"
            })[0], 400)
            spawn.assert_not_called()

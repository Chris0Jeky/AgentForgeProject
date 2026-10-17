from contextlib import ExitStack
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agentforge.core.mcp import ensure_gateway_running, McpConfig, _gateway_processes
from server_test_support import dashboard, request, TOKEN


class TestGatewaySecrets(unittest.TestCase):
    maxDiff = 500

    def test_public_routes_redact_gateway_secrets_and_preserve_private_record(self):
        secret = "gateway-secret-canary"
        record = {
            "key": "test", "profile": "test", "transport": "sse", "pid": 123,
            "url": f"http://user:{secret}@127.0.0.1:9360/?token={secret}#{secret}",
            "auth_token": secret, "future_secret": secret,
            "operation_id": "test-operation", "command": ["docker", "mcp", "gateway", "run"],
            "state": "running",
        }
        routes = (
            "/", "/api/status", "/api/workflows", "/api/queue/issues", "/api/bootstrap/plan",
            "/api/mcp/config", "/api/mcp/version", "/api/mcp/catalog", "/api/mcp/profile",
            "/api/mcp/gateway/list", "/api/runs", "/api/run/status?run_id=missing",
            "/api/run/stream?run_id=missing",
        )
        for actions in (False, True):
            with self.subTest(actions=actions), dashboard(actions=actions) as (root, cfg, port), ExitStack() as stack:
                store = root / cfg.state_dir / "mcp_gateways.json"
                store.parent.mkdir(parents=True)
                store.write_text(json.dumps({"test": record}), encoding="utf-8")
                stack.enter_context(patch.dict(_gateway_processes, {
                    (str(store.resolve()), record["operation_id"]):
                        (SimpleNamespace(pid=123, poll=lambda: None), None, dict(record))
                }))
                stack.enter_context(patch("agentforge.core.mcp._gateway_ready", return_value=True))
                stack.enter_context(patch("agentforge.core.mcp.docker_mcp_available", return_value=True))
                for name, value in (
                    ("docker_mcp_available", False), ("docker_mcp_version", "test"),
                    ("docker_catalog_server_ls", []), ("docker_profile_list", []),
                    ("docker_profile_server_ls", []), ("list_issues", []), ("build_plan_from_queue", []),
                    ("load_workflows", {}),
                ):
                    stack.enter_context(patch("agentforge.core.server." + name, return_value=value))
                for route in routes:
                    with self.subTest(route=route):
                        status, response = request(port, "GET", route)
                        self.assertIn(status, (200, 404))
                        self.assertNotIn(secret, response)
                        self.assertNotIn('"auth_token"', response)
                        self.assertNotIn('"future_secret"', response)
                status, response = request(port, "GET", "/api/mcp/gateway/list")
                public = json.loads(response)["gateways"][0]
                self.assertEqual(public, {**{k: record[k] for k in ("key", "profile", "transport", "pid")},
                                          "url": "http://127.0.0.1:9360", "state": "running"})
                if actions:
                    status, response = request(port, "POST", "/api/mcp/gateway/start", headers={
                        "Authorization": "Bearer " + TOKEN
                    }, body='{"key":"test"}')
                    self.assertEqual(status, 200)
                    self.assertNotIn(secret, response)
                    self.assertEqual(json.loads(response)["gateway"], {k: v for k, v in public.items() if k != "state"})
                private = ensure_gateway_running(root, cfg, McpConfig(), key="test")
                self.assertEqual(private["auth_token"], secret)
                self.assertEqual(json.loads(store.read_text(encoding="utf-8"))["test"], record)

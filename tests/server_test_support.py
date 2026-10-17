from contextlib import contextmanager, ExitStack
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from unittest.mock import patch

from agentforge.core.config import Policy, RepoConfig
from agentforge.core.server import serve_status


TOKEN = "dashboard-secret-canary"


@contextmanager
def dashboard(*, actions=False, cli=False):
    with TemporaryDirectory() as tmp, ExitStack() as stack:
        root = Path(tmp)
        cfg = RepoConfig()
        ready = threading.Event()
        servers = []

        def make_server(address, handler):
            srv = ThreadingHTTPServer(address, handler)
            servers.append(srv)
            ready.set()
            return srv

        stack.enter_context(patch("agentforge.core.server.ThreadingHTTPServer", side_effect=make_server))
        stack.enter_context(patch("builtins.print"))
        st_file = root / cfg.state_dir / "state.json"
        if cli:
            from agentforge.cli import build_parser
            args = build_parser().parse_args(["serve", "--port", "0"])
            stack.enter_context(patch("agentforge.cli.find_repo_root", return_value=root))
            stack.enter_context(patch("agentforge.cli.load_repo_config", return_value=(cfg, Policy())))
            stack.enter_context(patch("agentforge.cli.state_paths", return_value=(st_file, None)))
            target = lambda: args.func(args)
        else:
            target = lambda: serve_status(root, cfg, Policy(), st_file, port=0, enable_actions=actions, token=TOKEN)
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        assert ready.wait(3), "dashboard did not start"
        try:
            yield root, cfg, servers[0].server_port
        finally:
            servers[0].shutdown()
            thread.join(3)
            servers[0].server_close()
            assert not thread.is_alive(), "dashboard did not stop"


def request(port, method, path, *, headers=None, body=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        return response.status, response.read().decode("utf-8")
    finally:
        conn.close()

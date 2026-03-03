from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from urllib.request import urlopen

from agentforge.core.config import Policy, RepoConfig
from agentforge.core.server import serve_status


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_ui_js_escapes_newline_literals(tmp_path: Path) -> None:
    cfg = RepoConfig()
    pol = Policy()
    st_file = tmp_path / cfg.state_dir / "state.json"
    st_file.parent.mkdir(parents=True, exist_ok=True)

    port = _free_port()
    th = threading.Thread(
        target=serve_status,
        kwargs=dict(
            root=tmp_path,
            cfg=cfg,
            pol=pol,
            st_file=st_file,
            host="127.0.0.1",
            port=port,
            enable_actions=True,
            token="t",
        ),
        daemon=True,
    )
    th.start()

    html = ""
    for _ in range(20):
        try:
            with urlopen(f"http://127.0.0.1:{port}/", timeout=1.5) as r:
                html = r.read().decode("utf-8", errors="replace")
            break
        except Exception:
            time.sleep(0.1)

    assert html, "UI HTML was not served"
    assert 'outEl.textContent += fmtEvent(ev) + "\\n";' in html
    assert 'outEl.textContent += msg.data + "\\n";' in html

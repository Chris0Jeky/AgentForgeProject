import shutil
from pathlib import Path

from agentforge.core import workspace
from agentforge.core.config import Policy, RepoConfig


class Interrupted(BaseException):
    """Simulate a process stopping without an exception rollback."""


class FakeGit:
    def __init__(self):
        self.branches = set()
        self.worktrees = {}
        self.commands = []
        self.fail_remove = False
        self.interrupt_add = False
        self.interrupt_branch = False

    def out(self, cmd, *, cwd, encoding=None):
        if cmd == ["git", "remote"]:
            return ""
        if cmd == ["git", "worktree", "list", "--porcelain", "-z"]:
            return "\0\0".join(f"worktree {p}\0HEAD deadbeef\0branch refs/heads/{br}" for p, br in self.worktrees.items())
        if cmd[:3] == ["git", "for-each-ref", "--format=%(refname)"]:
            return "\n".join("refs/heads/" + br for br in self.branches if "refs/heads/" + br == cmd[3])
        raise AssertionError(cmd)

    def run(self, cmd, *, cwd):
        self.commands.append(cmd)
        if cmd[1:3] == ["worktree", "add"]:
            if cmd[3] == "-b":
                br, path = cmd[4], Path(cmd[5])
                assert br not in self.branches
                self.branches.add(br)
                if self.interrupt_branch:
                    self.interrupt_branch = False
                    raise Interrupted()
            else:
                path, br = Path(cmd[3]), cmd[4]
                assert br in self.branches
            path.mkdir()
            self.worktrees[path.resolve()] = br
            if self.interrupt_add:
                self.interrupt_add = False
                raise Interrupted()
        elif cmd[1:3] == ["worktree", "remove"]:
            if self.fail_remove:
                raise RuntimeError("git removal failed")
            path = Path(cmd[-1]).resolve()
            assert path in self.worktrees
            shutil.rmtree(path)
            del self.worktrees[path]
        elif cmd[1:3] == ["branch", "-D"]:
            self.branches.remove(cmd[3])
        elif cmd[1] == "rev-parse" or cmd[1:3] == ["worktree", "repair"]:
            pass
        else:
            raise AssertionError(cmd)
        return 0, "", ""


def setup_workspace(tmp_path, monkeypatch):
    cfg = RepoConfig(port_start=8081, port_end=8081)
    state = tmp_path / "state.json"
    git = FakeGit()
    monkeypatch.setattr(workspace, "run", git.run)
    monkeypatch.setattr(workspace, "out", git.out)
    return cfg, Policy(), state, git

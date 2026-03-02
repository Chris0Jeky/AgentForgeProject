from agentforge.core.daemon import COMMAND_RE, _branch_to_agent_task


def test_branch_to_agent_task_parse() -> None:
    assert _branch_to_agent_task("af/a1/issue-123") == ("a1", "issue-123")
    assert _branch_to_agent_task("af/a2/fix/sub-path") == ("a2", "fix/sub-path")
    assert _branch_to_agent_task("feature/my-branch") is None
    assert _branch_to_agent_task("af/only-agent") is None


def test_command_regex_matches_expected_format() -> None:
    m = COMMAND_RE.match("/agentforge fix apply the requested update")
    assert m is not None
    assert m.group("cmd").lower() == "fix"
    assert "requested update" in m.group("rest")

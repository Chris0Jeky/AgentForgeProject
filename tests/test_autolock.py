from agentforge.core.locks import LockGroups, LockGroupSpec, select_lock_group_for_issue


def _groups():
    return LockGroups(
        groups={
            "repo": LockGroupSpec(name="repo", globs=["**"], labels=[], keywords=[], workflow="default", priority=0, default=True),
            "frontend": LockGroupSpec(name="frontend", globs=["web/**"], labels=["area:frontend", "ui"], keywords=["ui", "web"], workflow="frontend", priority=50, default=False),
            "docs": LockGroupSpec(name="docs", globs=["docs/**"], labels=["docs"], keywords=["readme", "docs"], workflow="docs", priority=10, default=False),
        }
    )


def test_select_by_label():
    g = _groups()
    spec = select_lock_group_for_issue(g, issue_labels=["area:frontend"], issue_title="anything")
    assert spec is not None
    assert spec.name == "frontend"
    assert spec.workflow == "frontend"


def test_select_by_keyword_when_no_label():
    g = _groups()
    spec = select_lock_group_for_issue(g, issue_labels=[], issue_title="Update README docs for install")
    assert spec is not None
    assert spec.name == "docs"


def test_select_default_when_no_match():
    g = _groups()
    spec = select_lock_group_for_issue(g, issue_labels=["bug"], issue_title="misc")
    assert spec is not None
    assert spec.name == "repo"


def test_strategy_labels_only_falls_back_to_default():
    g = _groups()
    spec = select_lock_group_for_issue(g, issue_labels=[], issue_title="Update README docs", strategy="labels")
    assert spec is not None
    assert spec.name == "repo"

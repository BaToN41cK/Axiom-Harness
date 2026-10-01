"""W4.13: pagination + delta primitives for trajectory, files, and diffs."""

from __future__ import annotations

import pytest

from axiom.core.paging import paginate, paginate_diff, paginate_lines
from axiom.core.project_index import list_project_files
from axiom.core.trajectory import Trajectory


def test_paginate_window_and_totals():
    page = paginate(list(range(10)), offset=0, limit=3)
    assert page.items == [0, 1, 2]
    assert page.total == 10
    assert page.offset == 0
    assert page.limit == 3
    assert page.has_more is True


def test_paginate_middle_and_last_page():
    assert paginate(list(range(10)), offset=3, limit=3).items == [3, 4, 5]
    last = paginate(list(range(10)), offset=9, limit=3)
    assert last.items == [9]
    assert last.has_more is False


def test_paginate_clamps_offset_past_end():
    page = paginate(list(range(5)), offset=99, limit=10)
    assert page.items == []
    assert page.offset == 5
    assert page.has_more is False


def test_paginate_rejects_bad_bounds():
    with pytest.raises(ValueError):
        paginate([], offset=-1)
    with pytest.raises(ValueError):
        paginate([], limit=0)


def test_page_to_json_identity_and_transform():
    page = paginate([{"n": 1}], offset=0, limit=5)
    assert page.to_json() == {
        "items": [{"n": 1}],
        "total": 1,
        "offset": 0,
        "limit": 5,
        "has_more": False,
    }
    assert paginate([1, 2], limit=5).to_json(item_to_dict=lambda n: n * 10)["items"] == [10, 20]


def test_paginate_lines_and_diff():
    page = paginate_lines("a\nb\nc\nd\ne", offset=1, limit=2)
    assert page.items == ["b", "c"]
    assert page.total == 5
    assert page.has_more is True
    diff = paginate_diff("@@ -1,2 +1,2 @@\n-x\n+y", offset=0, limit=1)
    assert diff.items == ["@@ -1,2 +1,2 @@"]
    assert diff.has_more is True


def test_trajectory_page_and_since():
    traj = Trajectory(run_id="run123")
    for i in range(5):
        traj.append("step", f"step {i}")
    page = traj.page(offset=1, limit=2)
    assert page["run_id"] == "run123"
    assert page["total"] == 5
    assert page["offset"] == 1
    assert page["limit"] == 2
    assert page["has_more"] is True
    assert [e["summary"] for e in page["events"]] == ["step 1", "step 2"]
    delta = traj.since(3)
    assert [e["seq"] for e in delta] == [4, 5]
    assert [e["summary"] for e in delta] == ["step 3", "step 4"]
    assert traj.since(99) == []


def test_list_project_files_paginated_and_relative(tmp_path):
    root = tmp_path / "proj"
    (root / "sub").mkdir(parents=True)
    for name in ("a.py", "b.py", "c.txt", "d.py"):
        (root / name).write_text("x", encoding="utf-8")
    (root / "sub" / "e.py").write_text("x", encoding="utf-8")
    page = list_project_files(root, offset=1, limit=2)
    assert page["total"] == 5
    assert len(page["items"]) == 2
    assert page["has_more"] is True
    # sorted, relative posix paths only — never an absolute path
    assert page["items"] == sorted(page["items"])
    assert all(not p.startswith(str(root)) for p in page["items"])
    assert "sub/e.py" in list_project_files(root, offset=0, limit=50)["items"]

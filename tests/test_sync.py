"""sync.py가 common.json대로 플러그인 레포의 사본을 공통 레포와 맞추는지 검사한다."""

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))

import sync  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


@pytest.fixture
def common(tmp_path, monkeypatch):
    """v1 태그를 단 가짜 공통 레포. 태그 뒤에 작업 중인 변경이 하나 있다."""
    root = str(tmp_path / "common")
    write(f"{root}/shared/kit/a.py", "A = 1\n")
    write(f"{root}/shared/kit/b.py", "B = 1\n")
    write(f"{root}/skills/demo/SKILL.md", '---\nname: demo\nmetadata:\n  version: "4.0.0"\n---\n본문 v1\n')
    write(f"{root}/shared/other.md", "다른 플러그인만 쓴다\n")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-qm", "init")
    git(root, "tag", "v1")
    write(f"{root}/shared/kit/a.py", "A = 2  # 아직 태그 전\n")
    monkeypatch.setattr(sync, "COMMON", root)
    return root


@pytest.fixture
def plugin(tmp_path):
    root = str(tmp_path / "plugin")
    write(f"{root}/common.json", json.dumps({
        "version": "v1",
        "targets": [{"root": "plugins/p", "include": ["shared/kit", "skills/demo"]}],
    }))
    write(f"{root}/plugins/p/shared/kit/a.py", "A = 0  # 손으로 고친 사본\n")
    write(f"{root}/plugins/p/skills/demo/SKILL.md", '---\nname: demo\nmetadata:\n  version: "3.7.1"\n---\n본문 v0\n')
    write(f"{root}/plugins/p/shared/own.py", "플러그인 고유 파일\n")
    return root


def test_check_lists_differing_and_missing_copies(plugin, common, capsys):
    assert sync.main(["--repo", plugin, "--check"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert sorted(out) == ["differs: plugins/p/shared/kit/a.py",
                           "differs: plugins/p/skills/demo/SKILL.md",
                           "missing: plugins/p/shared/kit/b.py"]


def test_sync_copies_tagged_content_only_for_included_paths(plugin, common):
    assert sync.main(["--repo", plugin]) == 0
    p = f"{plugin}/plugins/p"
    assert read(f"{p}/shared/kit/a.py") == "A = 1\n"   # 작업 중인 변경이 아니라 v1 태그 내용
    assert read(f"{p}/shared/kit/b.py") == "B = 1\n"
    assert not os.path.exists(f"{p}/shared/other.md")   # include에 없는 경로는 가져오지 않는다
    assert read(f"{p}/shared/own.py") == "플러그인 고유 파일\n"   # 공통 레포에 없는 파일은 건드리지 않는다
    assert sync.main(["--repo", plugin, "--check"]) == 0


def test_dev_uses_working_tree(plugin, common):
    assert sync.main(["--repo", plugin, "--dev"]) == 0
    assert read(f"{plugin}/plugins/p/shared/kit/a.py") == "A = 2  # 아직 태그 전\n"


def test_unknown_tag_stops_with_message(plugin, common):
    cfg = json.loads(read(f"{plugin}/common.json"))
    cfg["version"] = "v9"
    write(f"{plugin}/common.json", json.dumps(cfg))
    with pytest.raises(SystemExit, match="v9"):
        sync.main(["--repo", plugin])


def test_copy_removed_from_common_is_reported_and_deleted(plugin, common, capsys):
    # 공통 레포에서 지우거나 이름을 바꾼 파일의 옛 사본이 include 폴더에 남으면 안 된다
    write(f"{plugin}/plugins/p/shared/kit/old_name.py", "옛 사본\n")
    sync.main(["--repo", plugin])
    assert not os.path.exists(f"{plugin}/plugins/p/shared/kit/old_name.py")
    assert read(f"{plugin}/plugins/p/shared/own.py") == "플러그인 고유 파일\n"   # include 밖은 그대로

    write(f"{plugin}/plugins/p/shared/kit/old_name.py", "옛 사본\n")
    capsys.readouterr()
    assert sync.main(["--repo", plugin, "--check"]) == 1
    assert capsys.readouterr().out.splitlines() == ["extra: plugins/p/shared/kit/old_name.py"]


def test_bundle_copies_inside_included_skill_are_not_extra(plugin, common):
    # bundle_skills.py가 스킬 폴더 안에 만드는 사본(공통 레포에 없는 폴더)은 공통 레포가 관리하지 않는다
    sync.main(["--repo", plugin])
    bundled = f"{plugin}/plugins/p/skills/demo/shared/assets/kit.py"
    write(bundled, "bundle 사본\n")
    assert sync.main(["--repo", plugin, "--check"]) == 0
    sync.main(["--repo", plugin])
    assert read(bundled) == "bundle 사본\n"

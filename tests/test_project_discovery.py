from pathlib import Path

from aidycai.application.project_discovery import discover_git_projects


def test_discover_git_repositories_in_selected_folder(tmp_path: Path):
    first = tmp_path / "AIDYC"
    second = tmp_path / "AidyCWeb"
    (first / ".git").mkdir(parents=True)
    second.mkdir()
    (second / ".git").write_text("gitdir: ../.git/worktrees/web\n", encoding="utf-8")
    (tmp_path / "ordinary-folder").mkdir()
    found = discover_git_projects(tmp_path)

    assert found == [first.resolve(), second.resolve()]


def test_discover_selected_folder_when_it_is_a_repository(tmp_path: Path):
    (tmp_path / ".git").mkdir()

    assert discover_git_projects(tmp_path) == [tmp_path.resolve()]


def test_discover_nonexistent_folder_returns_empty(tmp_path: Path):
    assert discover_git_projects(tmp_path / "missing") == []

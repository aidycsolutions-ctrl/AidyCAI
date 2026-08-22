from pathlib import Path
from unittest.mock import patch

from aidycai.infrastructure.git_service import GitService
from aidycai.services.github_actions import GitHubActionsService, WorkflowNotFoundError
from aidycai.services.project_runner import ProjectRunner


def test_project_runner_rejects_empty_command(tmp_path):
    runner = ProjectRunner()
    try:
        runner.start_project(" ", tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError("empty command must be rejected")


def test_project_runner_uses_shell_false(tmp_path):
    runner = ProjectRunner()
    with patch("aidycai.services.project_runner.subprocess.Popen") as popen:
        process = popen.return_value
        process.poll.return_value = 0
        runner.start_project("python app.py", tmp_path)
        kwargs = popen.call_args.kwargs
        assert kwargs["shell"] is False
        assert kwargs["cwd"] == str(tmp_path)


def test_git_publish_does_not_stash_clean_repo(tmp_path):
    service = GitService(tmp_path)
    calls = []

    def fake(*args, check=True):
        calls.append(args)
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        if args == ("branch", "--show-current"):
            R.stdout = "main"
        return R()

    service.run = fake
    service.status_porcelain = lambda: ""
    service.publish_main("test")
    assert ("stash", "push", "--include-untracked", "-m", "AIDYCAI temporary publish stash") not in calls
    assert ("push", "origin", "main") in calls


def test_github_actions_checks_workflow_before_dispatch():
    service = GitHubActionsService("owner", "repo", token="x")
    with patch.object(service, "_request", side_effect=[
        (200, {"workflows": [{"id": 7, "path": ".github/workflows/build_exe.yml"}]}),
        (204, None),
    ]) as request:
        assert service.trigger_build_exe() is True
        assert request.call_args_list[1].args[0] == "actions/workflows/7/dispatches"


def test_github_actions_reports_missing_workflow():
    service = GitHubActionsService("owner", "repo", token="x")
    with patch.object(service, "_request", return_value=(200, {"workflows": []})):
        try:
            service.trigger_build_exe()
        except WorkflowNotFoundError:
            pass
        else:
            raise AssertionError("missing workflow must be explicit")

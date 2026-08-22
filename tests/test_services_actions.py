from pathlib import Path
from unittest.mock import patch

from aidycai.infrastructure.git_service import GitService
from aidycai.infrastructure.ssh_service import SSHService
from aidycai.services.github_actions import GitHubActionsService


def test_git_reload_is_ff_only(tmp_path):
    service = GitService(tmp_path)
    with patch.object(service, "has_changes", return_value=False), patch.object(service, "run", side_effect=["", "ok"] ) as run:
        assert service.reload("main") == "ok"
    assert run.call_args_list[0].args[0] == ["fetch", "origin", "main"]
    assert run.call_args_list[1].args[0] == ["pull", "--ff-only", "origin", "main"]


def test_ssh_deploy_contains_no_shell_interpolation_from_local_command():
    service = SSHService()
    with patch.object(service, "run", return_value="ok") as run:
        assert service.deploy(user="u", host="h", remote_path="/srv/app", branch="main", script="scripts/deploy.sh") == "ok"
    command = run.call_args.args[2]
    assert "git pull --ff-only origin 'main'" in command
    assert "bash 'scripts/deploy.sh'" in command


def test_github_dispatch_sends_workflow_input():
    service = GitHubActionsService("owner", "repo", token="token")
    with patch.object(service, "_request", return_value=(204, {})) as request:
        assert service.dispatch("main.yml", "main", {"version": "v25.1"})
    payload = request.call_args.args[2]
    assert payload == {"ref": "main", "inputs": {"version": "v25.1"}}

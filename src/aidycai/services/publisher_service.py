from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aidycai.application.project_actions import ProjectActions
from aidycai.infrastructure.git_service import GitService
from aidycai.infrastructure.ssh_service import SSHService


@dataclass
class PublishResult:
    committed: bool
    branch: str
    deployed: bool = False


class PublisherService:
    def __init__(self, repo_path: str | Path, actions: ProjectActions) -> None:
        self.repo_path = Path(repo_path)
        self.actions = actions
        self.git = GitService(repo_path)
        self.ssh = SSHService()

    def publish(self, message: str, *, deploy: bool = False) -> PublishResult:
        result = self.git.publish(message, self.actions.branch)
        did_deploy = False
        if deploy:
            if not self.actions.can_deploy:
                raise RuntimeError("El proyecto no tiene una configuración de deploy completa.")
            self.ssh.deploy(
                user=self.actions.deploy_user or "",
                host=self.actions.deploy_host or "",
                remote_path=self.actions.deploy_path or "",
                branch=self.actions.branch,
                script=self.actions.deploy_script,
            )
            did_deploy = True
        return PublishResult(bool(result["committed"]), str(result["branch"]), did_deploy)

    def deploy_only(self) -> str:
        if not self.actions.can_deploy:
            raise RuntimeError("El proyecto no tiene una configuración de deploy completa.")
        return self.ssh.deploy(
            user=self.actions.deploy_user or "",
            host=self.actions.deploy_host or "",
            remote_path=self.actions.deploy_path or "",
            branch=self.actions.branch,
            script=self.actions.deploy_script,
        )

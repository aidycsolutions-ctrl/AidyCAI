from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProjectActions:
    command: str | None = None
    venv: str | None = "auto"
    open_browser: bool = False
    url: str | None = None
    browser_delay: float = 1.5
    branch: str = "main"
    github_owner: str | None = None
    github_repo: str | None = None
    publish: bool = True
    deploy: bool = False
    deploy_user: str | None = None
    deploy_host: str | None = None
    deploy_path: str | None = None
    deploy_script: str = "scripts/deploy-pythonanywhere.sh"
    build_workflow: str | None = None
    build_input_name: str = "version"
    extra_env: dict[str, str] = field(default_factory=dict)

    @property
    def can_execute(self) -> bool:
        return bool(self.command)

    @property
    def can_publish(self) -> bool:
        return self.publish and bool(self.github_owner and self.github_repo)

    @property
    def can_deploy(self) -> bool:
        return self.deploy and bool(self.deploy_user and self.deploy_host and self.deploy_path)

    @property
    def can_build(self) -> bool:
        return bool(self.github_owner and self.github_repo and self.build_workflow)

    @classmethod
    def from_settings(cls, settings: dict[str, str]) -> "ProjectActions":
        import json
        raw = settings.get("actions")
        if not raw:
            return cls()
        data = json.loads(raw)
        allowed = {name: data[name] for name in cls.__dataclass_fields__ if name in data}
        return cls(**allowed)


def serialize_actions(actions: ProjectActions) -> str:
    import json
    return json.dumps({
        name: getattr(actions, name)
        for name in actions.__dataclass_fields__
        if getattr(actions, name) is not None
    }, ensure_ascii=False, sort_keys=True)

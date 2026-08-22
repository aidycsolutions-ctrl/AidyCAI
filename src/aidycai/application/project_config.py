from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    path: Path
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
    extra_excludes: tuple[str, ...] = ()


def config_path() -> Path:
    # Editable configuration lives beside pyproject.toml in the source checkout.
    return Path(__file__).resolve().parents[3] / "config" / "projects.json"


def _expand_path(value: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(value))
    return Path(expanded).resolve()


def load_project_configs() -> list[ProjectConfig]:
    path = config_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    result: list[ProjectConfig] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("name") or not item.get("path"):
            continue
        result.append(ProjectConfig(
            name=str(item["name"]), path=_expand_path(str(item["path"])),
            command=item.get("command"), venv=item.get("venv", "auto"),
            open_browser=bool(item.get("open_browser", False)), url=item.get("url"),
            browser_delay=float(item.get("browser_delay", 1.5)), branch=str(item.get("branch", "main")),
            github_owner=item.get("github_owner"), github_repo=item.get("github_repo"),
            publish=bool(item.get("publish", True)), deploy=bool(item.get("deploy", False)),
            deploy_user=item.get("deploy_user"), deploy_host=item.get("deploy_host"),
            deploy_path=item.get("deploy_path"), deploy_script=str(item.get("deploy_script", "scripts/deploy-pythonanywhere.sh")),
            build_workflow=item.get("build_workflow"), build_input_name=str(item.get("build_input_name", "version")),
            extra_env={str(k): str(v) for k, v in dict(item.get("extra_env", {})).items()},
            extra_excludes=tuple(str(x) for x in item.get("extra_excludes", [])),
        ))
    return result


def get_project_config(name: str) -> ProjectConfig | None:
    lowered = name.strip().lower()
    return next((item for item in load_project_configs() if item.name.lower() == lowered), None)

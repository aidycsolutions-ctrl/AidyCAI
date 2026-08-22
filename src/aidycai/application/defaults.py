from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from aidycai.application.project_config import load_project_configs
from aidycai.application.project_actions import ProjectActions


def _win_user_path(relative: str) -> Path:
    if os.name == "nt":
        return Path(os.environ.get("USERPROFILE", Path.home())) / relative
    return Path(r"C:\Users\USUARIO") / relative


@dataclass(frozen=True)
class DefaultProject:
    name: str
    path: Path
    extra_excludes: tuple[str, ...] = ()
    actions: ProjectActions = ProjectActions()


def _from_json() -> tuple[DefaultProject, ...]:
    result = []
    for spec in load_project_configs():
        result.append(DefaultProject(
            name=spec.name,
            path=spec.path,
            extra_excludes=spec.extra_excludes,
            actions=ProjectActions(
                command=spec.command, venv=spec.venv, open_browser=spec.open_browser,
                url=spec.url, browser_delay=spec.browser_delay, branch=spec.branch,
                github_owner=spec.github_owner, github_repo=spec.github_repo, publish=spec.publish,
                deploy=spec.deploy, deploy_user=spec.deploy_user, deploy_host=spec.deploy_host,
                deploy_path=spec.deploy_path, deploy_script=spec.deploy_script,
                build_workflow=spec.build_workflow, build_input_name=spec.build_input_name,
                extra_env=spec.extra_env,
            ),
        ))
    return tuple(result)


DEFAULT_PROJECTS: tuple[DefaultProject, ...] = _from_json()

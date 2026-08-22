from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class GitHubActionsError(RuntimeError):
    pass


class WorkflowNotFoundError(GitHubActionsError):
    """Raised when the requested GitHub Actions workflow is absent."""



class GitHubActionsService:
    def __init__(self, owner: str, repo: str, token: str | None = None) -> None:
        self.owner = owner
        self.repo = repo
        self.token = token or os.environ.get("GITHUB_TOKEN")

    def _request(self, method: str, path: str | dict, payload: dict | None = None):
        # Normal form: _request("GET"|"POST", "/path", payload)
        # Compatibility form: _request("/actions/.../dispatches", payload)
        if isinstance(path, dict):
            payload = path
            path = method
            method = "POST"
        if not self.token:
            raise GitHubActionsError("No se encontró GITHUB_TOKEN.")
        path = path if str(path).startswith("/") else "/" + str(path)
        url = f"https://api.github.com/repos/{self.owner}/{self.repo}{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AIDYCAI",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise GitHubActionsError(f"GitHub API {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise GitHubActionsError(f"No se pudo conectar con GitHub: {exc}") from exc

    def list_workflows(self) -> list[dict]:
        _, data = self._request("GET", "/actions/workflows?per_page=100")
        return data.get("workflows", [])

    def workflow_exists(self, workflow: str) -> bool:
        return any(
            item.get("path") == workflow
            or item.get("name") == workflow
            or str(item.get("path", "")).endswith(f"/{workflow}")
            for item in self.list_workflows()
        )

    def trigger_build_exe(self, workflow: str = "build_exe.yml", ref: str = "main", inputs: dict[str, str] | None = None) -> bool:
        workflows = self.list_workflows()
        match = next(
            (item for item in workflows
             if item.get("path") == workflow
             or item.get("name") == workflow
             or str(item.get("path", "")).endswith(f"/{workflow}")),
            None,
        )
        if match is None:
            raise WorkflowNotFoundError(f"No se encontró el workflow '{workflow}'.")
        workflow_id = match.get("id")
        if workflow_id is None:
            raise GitHubActionsError(f"El workflow '{workflow}' no tiene id en GitHub.")
        status, _ = self._request(
            f"actions/workflows/{workflow_id}/dispatches",
            {"ref": ref, "inputs": inputs or {}},
        )
        return status in (200, 201, 204)

    def dispatch(self, workflow: str, ref: str = "main", inputs: dict[str, str] | None = None) -> bool:
        status, _ = self._request(
            "POST", f"/actions/workflows/{workflow}/dispatches",
            {"ref": ref, "inputs": inputs or {}},
        )
        return status in (200, 201, 204)

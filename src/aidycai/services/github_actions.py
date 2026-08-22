from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class GitHubActionsError(RuntimeError):
    pass


class GitHubActionsService:
    def __init__(self, owner: str, repo: str, token: str | None = None) -> None:
        self.owner = owner
        self.repo = repo
        self.token = token or os.environ.get("GITHUB_TOKEN")

    def _request(self, method: str, path: str, payload: dict | None = None):
        if not self.token:
            raise GitHubActionsError("No se encontró GITHUB_TOKEN.")
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
        return any(item.get("path") == workflow or item.get("name") == workflow for item in self.list_workflows())

    def dispatch(self, workflow: str, ref: str = "main", inputs: dict[str, str] | None = None) -> bool:
        status, _ = self._request(
            "POST", f"/actions/workflows/{workflow}/dispatches",
            {"ref": ref, "inputs": inputs or {}},
        )
        return status in (200, 201, 204)

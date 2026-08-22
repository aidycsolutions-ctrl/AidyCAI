from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


class GitService:
    def __init__(self, repo_path: str | Path) -> None:
        self.repo_path = Path(repo_path)

    def run(self, args, *rest: str, check: bool = True) -> str:
        command = [args, *rest] if rest else list(args)
        result = subprocess.run(
            ["git", *command], cwd=self.repo_path, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
        output = (result.stdout or "")
        if result.returncode != 0 and check:
            detail = (result.stderr or output).strip()
            raise GitError(detail or f"git terminó con código {result.returncode}")
        return output

    def status_porcelain(self) -> str:
        return self.run(["status", "--porcelain"])

    def current_branch(self) -> str:
        return self.run(["rev-parse", "--abbrev-ref", "HEAD"]).strip()

    def remote_url(self) -> str:
        return self.run(["remote", "get-url", "origin"]).strip()

    def has_changes(self) -> bool:
        return bool(self.status_porcelain().strip())

    def publish(self, message: str, branch: str = "main") -> dict[str, str | bool]:
        if not message.strip():
            raise GitError("El mensaje de commit no puede estar vacío.")
        current = self.current_branch()
        if current != branch:
            raise GitError(
                f"La rama actual es '{current}', pero la configuración solicita '{branch}'. "
                "Cambia de rama manualmente antes de publicar para evitar operaciones destructivas."
            )
        status_before = self.status_porcelain()
        self.run(["fetch", "origin", branch])
        local = self.run(["rev-parse", "HEAD"]).strip()
        remote = self.run(["rev-parse", f"origin/{branch}"]).strip()
        base = self.run(["merge-base", "HEAD", f"origin/{branch}"]).strip()
        if local != remote and base == remote:
            # Local has commits that are not remote yet: publishing is safe.
            pass
        elif local != remote and base == local:
            if status_before.strip():
                raise GitError("GitHub tiene commits nuevos y hay cambios locales. Usa Recargar antes de publicar.")
            self.run(["merge", "--ff-only", f"origin/{branch}"])
        elif local != remote:
            raise GitError("La rama local y GitHub han divergido. Resuelve la divergencia manualmente antes de publicar.")
        committed = False
        if status_before.strip():
            self.run(["add", "-A"])
            staged = self.run(["diff", "--cached", "--name-only"])
            if staged.strip():
                self.run(["commit", "-m", message])
                committed = True
        self.run(["push", "-u", "origin", branch])
        return {"committed": committed, "branch": branch, "status_before": status_before}

    def publish_main(self, message: str) -> dict[str, str | bool]:
        """Backward-compatible main-branch publisher for older integrations."""
        if not message.strip():
            raise GitError("El mensaje de commit no puede estar vacío.")
        branch_result = self.run("branch", "--show-current")
        current = branch_result.stdout.strip() if hasattr(branch_result, "stdout") else str(branch_result).strip()
        if current and current != "main":
            raise GitError(f"La rama actual es '{current}', no 'main'.")
        status = self.status_porcelain()
        self.run("fetch", "origin", "main")
        if status.strip():
            self.run("add", ".")
            self.run("commit", "-m", message)
        self.run("push", "origin", "main")
        return {"committed": bool(status.strip()), "branch": "main", "status_before": status}

    def reload(self, branch: str = "main") -> str:
        if self.has_changes():
            raise GitError("No se puede recargar con cambios locales sin publicar. No se realizó ninguna operación destructiva.")
        self.run(["fetch", "origin", branch])
        return self.run(["pull", "--ff-only", "origin", branch])

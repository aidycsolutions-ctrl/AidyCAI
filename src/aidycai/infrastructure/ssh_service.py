from __future__ import annotations

import subprocess
from pathlib import Path


class SSHError(RuntimeError):
    pass


class SSHService:
    def run(self, user: str, host: str, remote_command: str) -> str:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new", f"{user}@{host}", remote_command],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            raise SSHError((result.stderr or result.stdout).strip() or "SSH falló")
        return result.stdout or ""

    def deploy(self, *, user: str, host: str, remote_path: str, branch: str, script: str) -> str:
        safe_path = remote_path.replace("'", "'\\''")
        safe_branch = branch.replace("'", "'\\''")
        safe_script = script.replace("'", "'\\''")
        command = (
            "set -e; "
            f"cd '{safe_path}'; "
            "git fetch origin; "
            f"git checkout '{safe_branch}'; "
            f"git pull --ff-only origin '{safe_branch}'; "
            f"if [ -f '{safe_script}' ]; then BRANCH='{safe_branch}' bash '{safe_script}'; fi"
        )
        return self.run(user, host, command)

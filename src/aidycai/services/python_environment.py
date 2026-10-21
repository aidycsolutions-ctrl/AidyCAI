from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from aidycai.infrastructure.paths import get_data_dir


@dataclass(frozen=True)
class PreparedPythonEnvironment:
    path: Path
    created: bool
    dependencies_installed: bool
    dependency_source: str | None


class PythonEnvironmentError(RuntimeError):
    pass


class PythonEnvironmentManager:
    """Create isolated project environments under AIDYCAI's local data folder."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = (data_dir or get_data_dir()).resolve()

    def prepare(self, project_path: str | Path, project_id: str) -> PreparedPythonEnvironment:
        root = Path(project_path).expanduser().resolve()
        if not root.is_dir():
            raise PythonEnvironmentError(f"No existe la carpeta del proyecto: {root}")

        env_root = (self.data_dir / "environments").resolve()
        env_root.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(char if char.isalnum() or char in "-_" else "-" for char in project_id).strip("-")
        if not safe_id:
            raise PythonEnvironmentError("El proyecto no tiene un identificador válido para su entorno.")
        env_path = (env_root / safe_id).resolve()
        if not env_path.is_relative_to(env_root):
            raise PythonEnvironmentError("La ruta del entorno sale de la carpeta local de AIDYCAI.")

        dependencies, fingerprint, source, requirements_file = self._dependencies(root)
        python_path = self.python_path(env_path)
        marker_path = env_path / ".aidycai-environment.json"
        marker = self._read_marker(marker_path)
        created = not python_path.is_file()
        dependencies_changed = marker.get("fingerprint") != fingerprint
        rebuild = created or dependencies_changed

        if rebuild:
            if env_path.exists():
                shutil.rmtree(env_path)
            self._run([sys.executable, "-m", "venv", str(env_path)], root, "No se pudo crear el entorno virtual")
            python_path = self.python_path(env_path)
            if not python_path.is_file():
                raise PythonEnvironmentError(f"Python no creó el ejecutable esperado: {python_path}")

            if requirements_file is not None:
                self._run(
                    [str(python_path), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements_file)],
                    root,
                    "No se pudieron instalar las dependencias de requirements.txt",
                )
            elif dependencies:
                self._run(
                    [str(python_path), "-m", "pip", "install", "--disable-pip-version-check", *dependencies],
                    root,
                    "No se pudieron instalar las dependencias de pyproject.toml",
                )
            marker_path.write_text(
                json.dumps({"fingerprint": fingerprint, "source": source}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return PreparedPythonEnvironment(
            path=env_path,
            created=rebuild,
            dependencies_installed=bool(rebuild and (requirements_file or dependencies)),
            dependency_source=source,
        )

    @staticmethod
    def python_path(env_path: Path) -> Path:
        if os.name == "nt":
            return env_path / "Scripts" / "python.exe"
        return env_path / "bin" / "python"

    @staticmethod
    def _read_marker(path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _dependencies(root: Path) -> tuple[list[str], str, str | None, Path | None]:
        requirements = root / "requirements.txt"
        if requirements.is_file():
            content = requirements.read_bytes()
            digest = hashlib.sha256(b"requirements.txt\0" + content).hexdigest()
            return [], digest, "requirements.txt", requirements

        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                raise PythonEnvironmentError(f"No se pudo leer pyproject.toml: {exc}") from exc
            project = data.get("project", {})
            raw_dependencies = project.get("dependencies", []) if isinstance(project, dict) else []
            if not isinstance(raw_dependencies, list) or not all(isinstance(item, str) for item in raw_dependencies):
                raise PythonEnvironmentError("project.dependencies en pyproject.toml debe ser una lista de dependencias.")
            dependencies = list(raw_dependencies)
            material = pyproject.read_bytes() if dependencies else b""
            digest = hashlib.sha256(b"pyproject.toml\0" + material).hexdigest()
            return dependencies, digest, "pyproject.toml" if dependencies else None, None

        digest = hashlib.sha256(b"no-python-dependencies").hexdigest()
        return [], digest, None, None

    @staticmethod
    def _run(command: list[str], cwd: Path, failure: str) -> None:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as exc:
            raise PythonEnvironmentError(f"{failure}: {exc}") from exc
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            if len(details) > 2400:
                details = details[-2400:]
            raise PythonEnvironmentError(f"{failure}.\n{details}".rstrip())

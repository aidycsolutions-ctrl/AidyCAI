from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
import time
import urllib.request
import socket
import webbrowser
from pathlib import Path
from collections.abc import Callable


class ProjectRunner:
    """Run/stop a project and, for web projects, open its local URL."""

    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.executable: Path | None = None

    @staticmethod
    def resolve_python(cwd: str | Path, venv: str | Path | None = "auto") -> Path:
        root = Path(cwd).expanduser().resolve()
        if venv is None or not str(venv).strip():
            return Path(sys.executable)
        raw = str(venv).strip()
        if raw.lower() == "auto":
            env_dirs = [root / "venv", root / ".venv"]
        else:
            value = Path(raw).expanduser()
            env_dirs = [value if value.is_absolute() else root / value]
        candidates = [candidate for env_dir in env_dirs for candidate in (
            env_dir / "Scripts" / "python.exe", env_dir / "Scripts" / "python",
            env_dir / "bin" / "python", env_dir / "bin" / "python3")]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        if raw.lower() == "auto":
            # ``auto`` means: use the project's venv when present, otherwise
            # fall back to the interpreter running AIDYCAI. This keeps generic
            # projects runnable while still preferring their isolated env.
            return Path(sys.executable)
        raise FileNotFoundError(
            "No se encontró el Python del entorno virtual. Rutas comprobadas: "
            + ", ".join(str(d) for d in env_dirs)
        )

    def start_project(self, command: str, cwd: str | Path | None = None, *,
                      venv: str | Path | None = "auto", on_output: Callable[[str], None] | None = None,
                      env: dict[str, str] | None = None, open_browser: bool = False,
                      url: str | None = None, browser_delay: float = 1.5) -> None:
        with self._lock:
            if self.process and self.process.poll() is None:
                raise RuntimeError("El proceso ya está en ejecución.")
            if cwd is None:
                raise ValueError("El proyecto debe tener una ruta de trabajo (cwd).")
            args = shlex.split(command, posix=(os.name != "nt"))
            if not args:
                raise ValueError("El comando de ejecución está vacío.")
            if args[0].lower() in {"python", "python3", "py", "python.exe", "python3.exe"}:
                python_exe = self.resolve_python(cwd, venv)
                args[0] = str(python_exe)
            else:
                python_exe = self.resolve_python(cwd, venv) if venv else Path(sys.executable)

            merged_env = os.environ.copy()
            if env:
                merged_env.update(env)
            if venv:
                root = Path(cwd).expanduser().resolve()
                raw = str(venv).strip()
                if raw.lower() == "auto":
                    candidates = [root / "venv", root / ".venv"]
                    env_dir = next((d for d in candidates if (d / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")).is_file()), candidates[0])
                else:
                    env_dir = Path(raw).expanduser()
                    if not env_dir.is_absolute():
                        env_dir = root / env_dir
                scripts_dir = env_dir / ("Scripts" if os.name == "nt" else "bin")
                merged_env["VIRTUAL_ENV"] = str(env_dir)
                merged_env["PATH"] = str(scripts_dir) + os.pathsep + merged_env.get("PATH", "")

            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            self.executable = python_exe
            self.process = subprocess.Popen(
                args, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                shell=False, env=merged_env, creationflags=creationflags,
            )
            process = self.process

        def reader() -> None:
            if process.stdout:
                for line in process.stdout:
                    if on_output:
                        on_output(line.rstrip("\r\n"))
            process.wait()

        self.thread = threading.Thread(target=reader, daemon=True, name="aidycai-project-runner")
        self.thread.start()
        if open_browser and url:
            threading.Thread(target=self._wait_and_open_browser, args=(url, browser_delay, process), daemon=True).start()

    @staticmethod
    def _wait_and_open_browser(url: str, delay: float, process: subprocess.Popen[str]) -> None:
        # Abrimos solamente cuando el servidor ya acepta conexiones. Si la app tarda
        # más de lo esperado, hacemos un último intento de abrir la URL para que el
        # usuario vea el error real en el navegador en vez de que AIDYCAI parezca no hacer nada.
        time.sleep(max(0.0, delay))
        deadline = time.monotonic() + 30.0
        opened = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return
            try:
                parsed = urllib.request.urlparse(url)
                host = parsed.hostname or "127.0.0.1"
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                with socket.create_connection((host, port), timeout=0.8):
                    webbrowser.open(url, new=2)
                    opened = True
                    return
            except OSError:
                time.sleep(0.5)
            except Exception:
                time.sleep(0.5)
        if not opened and process.poll() is None:
            webbrowser.open(url, new=2)

    def stop_project(self, timeout: float = 5.0) -> None:
        with self._lock:
            process = self.process
        if not process:
            return
        if process.poll() is not None:
            with self._lock:
                if self.process is process:
                    self.process = None
            return
        pid = process.pid
        try:
            if os.name == "nt":
                # taskkill /T alcanza también al Flask/Werkzeug reloader y a procesos
                # hijos. CREATE_NO_WINDOW evita que detener genere una consola adicional.
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, text=True, check=False,
                    creationflags=creationflags,
                )
                if result.returncode != 0 and process.poll() is None:
                    process.terminate()
            else:
                try:
                    os.killpg(os.getpgid(pid), 15)
                except (ProcessLookupError, PermissionError, OSError):
                    process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        capture_output=True, text=True, check=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                else:
                    process.kill()
                process.wait(timeout=3)
        finally:
            with self._lock:
                if self.process is process:
                    self.process = None
                    self.executable = None

    def is_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)

from unittest.mock import patch

from aidycai.services.project_runner import ProjectRunner


def test_resolve_python_prefers_project_venv(tmp_path):
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    python = venv / "python"
    python.write_text("", encoding="utf-8")
    assert ProjectRunner.resolve_python(tmp_path) == python


def test_start_project_uses_venv_python(tmp_path):
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    python = venv / "python"
    python.write_text("", encoding="utf-8")
    runner = ProjectRunner()
    with patch("aidycai.services.project_runner.subprocess.Popen") as popen:
        proc = popen.return_value
        proc.poll.return_value = None
        proc.stdout = []
        runner.start_project("python app.py", tmp_path, venv=".venv")
        args = popen.call_args.args[0]
        assert args[0] == str(python)
        kwargs = popen.call_args.kwargs
        assert kwargs["env"]["VIRTUAL_ENV"] == str(tmp_path / ".venv")
        assert kwargs["env"]["PATH"].startswith(str(venv))
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8:replace"


def test_start_project_preserves_explicit_python_io_encoding(tmp_path):
    runner = ProjectRunner()
    with patch("aidycai.services.project_runner.subprocess.Popen") as popen:
        popen.return_value.poll.return_value = 0
        runner.start_project(
            "python app.py", tmp_path, env={"PYTHONIOENCODING": "latin-1"}
        )
        assert popen.call_args.kwargs["env"]["PYTHONIOENCODING"] == "latin-1"


def test_auto_resolves_dotvenv_then_venv(tmp_path):
    venv = tmp_path / "venv" / "Scripts"
    venv.mkdir(parents=True)
    python = venv / "python.exe"
    python.write_text("", encoding="utf-8")
    assert ProjectRunner.resolve_python(tmp_path, "auto") == python


def test_missing_venv_fails_before_start(tmp_path):
    runner = ProjectRunner()
    with patch("aidycai.services.project_runner.subprocess.Popen") as popen:
        try:
            runner.start_project("python app.py", tmp_path, venv=".venv")
        except FileNotFoundError as exc:
            assert ".venv" in str(exc)
        else:
            raise AssertionError("Se esperaba error si no existe el venv")
        popen.assert_not_called()


def test_stop_project_kills_windows_process_tree():
    runner = ProjectRunner()
    class Proc:
        pid = 1234
        def poll(self): return None
        def wait(self, timeout=None): return 0
        def terminate(self): pass
    runner.process = Proc()
    with patch("aidycai.services.project_runner.os.name", "nt"), patch("aidycai.services.project_runner.subprocess.run") as run:
        runner.stop_project()
        assert run.call_args.args[0] == ["taskkill", "/PID", "1234", "/T", "/F"]


def test_browser_wait_opens_when_local_server_is_ready():
    with patch("aidycai.services.project_runner.time.sleep"), \
         patch("aidycai.services.project_runner.socket.create_connection") as connect, \
         patch("aidycai.services.project_runner.webbrowser.open") as browser:
        class Proc:
            def poll(self): return None
        ProjectRunner._wait_and_open_browser("http://127.0.0.1:5000", 0, Proc())
        assert connect.called
        browser.assert_called_once_with("http://127.0.0.1:5000", new=2)

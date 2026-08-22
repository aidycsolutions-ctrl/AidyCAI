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


def test_stop_project_windows_does_not_wait_forever():
    runner = ProjectRunner()
    class Proc:
        pid = 9876
        def __init__(self):
            self.calls = 0
        def poll(self):
            self.calls += 1
            return None
        def wait(self, timeout=None):
            raise TimeoutError()
        def kill(self):
            pass
        def terminate(self):
            pass
    proc = Proc()
    runner.process = proc
    with patch("aidycai.services.project_runner.os.name", "nt"),          patch("aidycai.services.project_runner.subprocess.run") as run,          patch("aidycai.services.project_runner.time.sleep"):
        runner.stop_project(timeout=0.5)
        assert run.call_args.args[0] == ["taskkill", "/PID", "9876", "/T", "/F"]
        assert runner.process is None


def test_is_running_is_thread_safe():
    runner = ProjectRunner()
    class Proc:
        def poll(self): return None
    runner.process = Proc()
    assert runner.is_running() is True
    runner.process = None
    assert runner.is_running() is False

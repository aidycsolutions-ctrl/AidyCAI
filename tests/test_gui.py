from pathlib import Path

from aidycai.gui.app import bundle_summary, format_bytes


def test_format_bytes():
    assert format_bytes(0) == "0 B"
    assert format_bytes(1024) == "1.0 KB"


def test_bundle_summary_mentions_project_and_task():
    # Use a tiny duck-typed bundle to keep the test independent of Tk.
    class Stats:
        candidate_files = 2
        candidate_symbols = 3
        selected_files = 1
        selected_lines = 10
        selected_chars = 100
        estimated_tokens = 25
        reduction_ratio = 0.5

    class Fragment:
        line_start = 10
        line_end = 20
        compressed = False

    class File:
        role = "PRIMARY"
        path = "example.py"
        score = 1.0
        reasons = ["exact symbol match"]
        fragments = [Fragment()]

    class Bundle:
        project_name = "AIDYC"
        task = "¿Dónde se calcula el total?"
        statistics = Stats()
        files = [File()]

    text = bundle_summary(Bundle())
    assert "AIDYC" in text
    assert "¿Dónde se calcula el total?" in text
    assert "example.py" in text


def test_render_diagnosis_mentions_priority_files():
    from aidycai.application.diagnostics import render_diagnosis

    class Stats:
        candidate_files = 4
        selected_files = 2
        selected_chars = 1000
        estimated_tokens = 250

    class Fragment:
        line_start = 10
        line_end = 20
        symbol_name = "Frame.agregar_retiros"

    class File:
        def __init__(self, path, role):
            self.path = path
            self.role = role
            self.reasons = ["symbol text match"]
            self.fragments = [Fragment()]

    class Bundle:
        project_name = "AIDYC"
        task = "¿Por qué no se imprimen los retiros?"
        statistics = Stats()
        files = [File("retirosefectivo.py", "PRIMARY"), File("Retiros.py", "SECONDARY")]
        relations = []
        symbols = []

    text = render_diagnosis(Bundle())
    assert "retirosefectivo.py" in text
    assert "Retiros.py" in text
    assert "Frame.agregar_retiros" in text


def test_background_operation_releases_gui_lock_and_allows_second_run():
    import threading
    import time
    from aidycai.gui.app import AIDYCAIWindow

    class Root:
        def __init__(self):
            self.scheduled = []

        def after(self, _delay, callback):
            self.scheduled.append(callback)

    window = object.__new__(AIDYCAIWindow)
    window.root = Root()
    window.busy = False
    window._operation_id = 0
    window._active_operation_id = None
    import queue
    window._background_events = queue.Queue()
    window.statuses = []
    window.logs = []
    window.progress = []
    window._set_status = lambda text: window.statuses.append(text)
    window._set_progress = lambda *args: window.progress.append(args)
    window._log = lambda message: window.logs.append(message)

    first_done = threading.Event()
    window._run_background(lambda: (time.sleep(0.02), first_done.set(), "first")[-1], lambda result: None, "Primera")
    assert window.busy is True
    assert first_done.wait(1)

    window._poll_background_events()
    assert window.busy is False
    assert window._active_operation_id is None

    second_done = threading.Event()
    window._run_background(lambda: (second_done.set(), "second")[-1], lambda result: None, "Segunda")
    assert window.busy is True
    assert second_done.wait(1)

    window._poll_background_events()
    assert window.busy is False
    assert window.statuses[-1] == "Listo"


def test_background_failure_releases_gui_lock_and_recovers():
    import queue
    from aidycai.gui.app import AIDYCAIWindow

    class Root:
        def __init__(self):
            self.scheduled = []

        def after(self, _delay, callback):
            self.scheduled.append(callback)

    window = object.__new__(AIDYCAIWindow)
    window.root = Root()
    window.busy = False
    window._operation_id = 0
    window._active_operation_id = None
    window._background_events = queue.Queue()
    window.statuses = []
    window.logs = []
    window.progress = []
    window._set_status = lambda text: window.statuses.append(text)
    window._set_progress = lambda *args: window.progress.append(args)
    window._log = lambda message: window.logs.append(message)
    window.progress_label = type("Label", (), {"configure": lambda self, **kwargs: None})()
    window.progress_bar = type("Bar", (), {"set": lambda self, value: None})()

    def fail():
        raise RuntimeError("index failure")

    window._run_background(fail, lambda result: None, "Fallando")
    assert window.busy is True
    window._poll_background_events()

    assert window.busy is False
    assert window._active_operation_id is None
    assert any("index failure" in message for message in window.logs)


def test_human_answer_prefers_directed_flow_over_technical_summary():
    from aidycai.application.diagnostics import render_human_answer

    class Stats:
        selected_files = 2
        selected_lines = 30

    class Analysis:
        flow_requested = True

    class File:
        def __init__(self, path):
            self.path = path
            self.role = "PRIMARY"

    class Bundle:
        statistics = Stats()
        analysis = Analysis()
        files = [File("retirosefectivo.py"), File("imprimir.py")]
        metadata = {
            "flow_path": ["imprimir_ultimos_retiros", "imprimir_ticket_retiro"],
            "terminal_edges": [["imprimir_ticket_retiro", "win32print.WritePrinter"]],
        }

    answer = render_human_answer(Bundle())
    assert "Seguí el flujo" in answer
    assert "win32print.WritePrinter" in answer
    assert "ContextBundle" not in answer

from pathlib import Path

from aidycai.application.bootstrap import open_app
from aidycai.domain.context_models import ContextConfig


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _project(root: Path, writers: int = 1, caller: bool = False) -> Path:
    project = root / "sql_causal"
    _write(project / "read.py", "def verretiros():\n    return Vista()\n")
    _write(project / "vista.py", '''class Vista:
    def __init__(self):
        self.cargar_datos()

    def cargar_datos(self):
        return obtener_valores_ultimo_turno()

def obtener_valores_ultimo_turno():
    return db.execute("SELECT Valor, detalle FROM Retiros_Caja WHERE turno = ?", (turno,))
''')
    for i in range(writers):
        name = "guardar_retiro" if i == 0 else f"guardar_retiro_{i}"
        text = f'''def {name}(turno, valor):
    return db.execute("INSERT INTO Retiros_Caja (turno, Valor) VALUES (?, ?)", (turno, valor))
'''
        if caller and i == 0:
            text += "\ndef determinar_turno():\n    return guardar_retiro(turno_actual, 10)\n"
        _write(project / f"writer_{i}.py", text)
    return project


def _build(tmp_path, name, project, config=None):
    with open_app(seed=False) as app:
        app.registry.add(name, project)
        app.index_service().index_project(name)
        engine = app.context_engine()
        if config is not None:
            engine.config = config
        return engine.build(name, "¿Por qué no aparecen los retiros históricos?")


def test_reader_to_unique_writer(tmp_path):
    bundle = _build(tmp_path, "SqlUnique", _project(tmp_path))
    assert "guardar_retiro" in bundle.metadata["flow_path"]
    assert any("SQL" in e.reason and "guardar_retiro" in e.reason for e in bundle.evidence)



def test_multi_call_init_selects_unique_sql_branch(tmp_path):
    project = _project(tmp_path)
    vista = project / "vista.py"
    text = vista.read_text(encoding="utf-8")
    text = text.replace(
        "    def __init__(self):\n        self.cargar_datos()",
        "    def __init__(self):\n        self.configure()\n        self._crear_widgets()\n        self.cargar_datos()\n\n    def configure(self):\n        return None\n\n    def _crear_widgets(self):\n        return None",
    )
    vista.write_text(text, encoding="utf-8")
    bundle = _build(tmp_path, "SqlMultiCallInit", project)
    path = bundle.metadata["flow_path"]
    assert path.index("Vista.cargar_datos") < path.index("obtener_valores_ultimo_turno")
    assert "guardar_retiro" in path
    assert "configure" not in path
    assert "_crear_widgets" not in path

def test_reader_to_ambiguous_writer(tmp_path):
    bundle = _build(tmp_path, "SqlAmbiguous", _project(tmp_path, writers=2))
    assert "guardar_retiro" not in bundle.metadata["flow_path"]
    assert any("escritores ambiguos" in x.lower() for x in bundle.metadata["flow_unresolved"])


def test_reader_without_writer(tmp_path):
    bundle = _build(tmp_path, "SqlMissing", _project(tmp_path, writers=0))
    assert any("no hay escritor indexado resoluble" in x for x in bundle.metadata["flow_unresolved"])


def test_continues_to_turno_origin_symbol(tmp_path):
    bundle = _build(tmp_path, "SqlTurno", _project(tmp_path, caller=True))
    path = bundle.metadata["flow_path"]
    assert path.index("obtener_valores_ultimo_turno") < path.index("guardar_retiro")
    assert "determinar_turno" in path


def test_causal_depth_limit(tmp_path):
    bundle = _build(tmp_path, "SqlDepth", _project(tmp_path), ContextConfig(causal_expansion_depth=0, causal_expansion_max_symbols=1))
    assert "guardar_retiro" not in bundle.metadata["flow_path"]
    assert any("limitada" in x for x in bundle.metadata["flow_unresolved"])


def test_causal_symbol_limit(tmp_path):
    bundle = _build(tmp_path, "SqlSymbols", _project(tmp_path), ContextConfig(causal_expansion_depth=4, causal_expansion_max_symbols=0))
    assert "guardar_retiro" not in bundle.metadata["flow_path"]
    assert any("limitada" in x for x in bundle.metadata["flow_unresolved"])


def test_no_fts_side_search(tmp_path):
    project = _project(tmp_path, writers=0)
    _write(project / "noise.py", "# INSERT INTO Retiros_Caja\ndef ruido():\n    return 1\n")
    bundle = _build(tmp_path, "SqlNoFts", project)
    assert "ruido" not in bundle.metadata["flow_path"]
    assert any("no hay escritor indexado resoluble" in x for x in bundle.metadata["flow_unresolved"])


def test_old_bundle_without_sql_operations_migrates(tmp_path):
    from aidycai.infrastructure.index_database import connect_index

    db_path = tmp_path / "legacy.sqlite"
    connection = connect_index(db_path)
    connection.execute("DROP TABLE sql_operations")
    connection.execute("DELETE FROM schema_migrations WHERE version = 2")
    connection.commit()
    connection.close()
    connection = connect_index(db_path)
    assert connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()[-1][0] == 2
    assert connection.execute("SELECT COUNT(*) FROM sql_operations").fetchone()[0] == 0
    connection.close()


def test_v16_1_ai_handoff_remains_compatible(tmp_path):
    from aidycai.application.ai_handoff import build_ai_handoff

    bundle = _build(tmp_path, "SqlHandoff", _project(tmp_path))
    handoff = build_ai_handoff(bundle).to_dict()
    assert handoff["protocol"] == "aidycai-ai-handoff-v1"
    assert "evidence" in handoff
    assert "flow" in handoff
    assert "guardar_retiro" in handoff["flow"]["path"]

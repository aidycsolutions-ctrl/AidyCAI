def test_project_action_controls_have_dedicated_ui_row():
    from pathlib import Path
    source = Path("src/aidycai/gui/app.py").read_text(encoding="utf-8")
    assert 'self.project_actions_frame.grid(row=3' in source
    assert 'actions.grid(row=4' in source
    assert not 'actions.grid(row=3, column=0' in source

from aidycai.application.defaults import DEFAULT_PROJECTS
from aidycai.application.project_actions import ProjectActions


def test_default_project_capabilities():
    by_name = {item.name: item.actions for item in DEFAULT_PROJECTS}
    assert by_name["AIDYC"].can_execute
    assert by_name["AIDYC"].can_publish
    assert not by_name["AIDYC"].can_deploy
    assert by_name["AIDYC"].can_build
    assert by_name["AIDYC"].build_workflow == "main.yml"
    assert by_name["AIDYCWeb"].can_execute
    assert by_name["AIDYCWeb"].can_deploy
    assert by_name["deunacolombia"].deploy_path == "/home/angeljoc/deunacolombia"


def test_action_settings_roundtrip():
    import json
    from aidycai.application.project_actions import serialize_actions
    original = ProjectActions(command="python app.py", github_owner="o", github_repo="r", build_workflow="main.yml")
    restored = ProjectActions.from_settings({"actions": serialize_actions(original)})
    assert restored == original

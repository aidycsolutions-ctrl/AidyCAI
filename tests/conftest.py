from __future__ import annotations

import pytest

from aidycai.infrastructure.paths import ENV_DATA_DIR, ENV_SKIP_SEED


@pytest.fixture(autouse=True)
def isolate_aidycai_data(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "aidycai-data"))
    monkeypatch.setenv(ENV_SKIP_SEED, "1")
    return tmp_path / "aidycai-data"

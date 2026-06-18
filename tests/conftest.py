import json
from pathlib import Path

import pytest

import mini_agent

CONFIGS_DIR = Path(mini_agent.__file__).parent / "configs"


def _usecase_names() -> list[str]:
    return sorted(
        path.name
        for path in CONFIGS_DIR.iterdir()
        if path.is_dir() and (path / "state_machine_config.json").exists()
    )


@pytest.fixture(params=_usecase_names())
def usecase_config(request) -> dict:
    config_path = CONFIGS_DIR / request.param / "state_machine_config.json"
    with config_path.open() as config_file:
        return json.load(config_file)["stateMachine"]

import json
from pathlib import Path

import pytest

import mini_agent


@pytest.fixture(scope="session")
def default_config() -> dict:
    """The parsed default state-machine config shipped with the package."""
    config_path = (
        Path(mini_agent.__file__).parent
        / "configs"
        / "default"
        / "state_machine_config.json"
    )
    with config_path.open() as config_file:
        return json.load(config_file)["stateMachine"]

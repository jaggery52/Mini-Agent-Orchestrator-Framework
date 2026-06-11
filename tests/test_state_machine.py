"""Graph-integrity checks for the default state-machine config.

These run without any network or LLM calls: they only validate that the JSON
graph is internally consistent and that every referenced state function /
condition function actually resolves on the engine's handler classes.
"""

from mini_agent.states.custom_conditions import CustomConditions
from mini_agent.states.custom_states import CustomStates

# Terminal sentinel: the run loop halts when it reaches this; it is not a state.
TERMINAL_STATE = "EndFinal"


def _next_state_targets(next_state_config) -> list[str]:
    """Return every state name a transition can route to."""
    if isinstance(next_state_config, str):
        return [next_state_config]
    return [transition["nextState"] for transition in next_state_config]


def test_start_state_present(default_config):
    assert "Start" in default_config


def test_every_transition_target_exists(default_config):
    valid_states = set(default_config) | {TERMINAL_STATE}
    for state_name, state in default_config.items():
        for target in _next_state_targets(state["nextState"]):
            assert target in valid_states, (
                f"State '{state_name}' transitions to unknown state '{target}'"
            )


def test_every_state_function_resolves(default_config):
    states = CustomStates()
    for state_name, state in default_config.items():
        function_name = state["function"]
        assert callable(getattr(states, function_name, None)), (
            f"State '{state_name}' references unknown function '{function_name}'"
        )


def test_every_condition_function_resolves(default_config):
    conditions = CustomConditions()
    for state_name, state in default_config.items():
        next_state_config = state["nextState"]
        if isinstance(next_state_config, str):
            continue
        for transition in next_state_config:
            condition = transition["conditionFunction"]
            if isinstance(condition, bool):
                continue
            assert callable(getattr(conditions, condition, None)), (
                f"State '{state_name}' references unknown condition '{condition}'"
            )

import copy
import json
import logging
import pathlib
from typing import Any, Dict, List

from mini_agent.engine.state_memory import StateMemory
from mini_agent.session import get_session
from mini_agent.states.custom_conditions import CustomConditions
from mini_agent.states.custom_states import CustomStates


class StateMachine:

    def __init__(self, config_name: str):
        # Package root: src/mini_agent/engine/state_machine.py -> parents[1] == mini_agent/
        self.configs_path = pathlib.Path(__file__).resolve().parents[1] / "configs"
        self.config_name = config_name
        self.__read_base_config(config_name)
        self.current_state_name = "Start"
        self.current_state: Dict[str, Any] = self.state_machine[self.current_state_name]
        logging.info(f"[StateMachine] Initialized with config: {config_name}")

    def __read_base_config(self, config_name: str) -> None:
        session = get_session()

        if session is not None and session.config_source == "user_config":
            self.state_machine = session.flow_config["stateMachine"]
            logging.debug("[StateMachine] Loaded config from WS user_config")
        else:
            config_json_path = self.configs_path / config_name / "state_machine_config.json"
            with open(config_json_path) as config_file:
                raw_config = json.load(config_file)
                self.state_machine = raw_config["stateMachine"]
            logging.debug(f"[StateMachine] Loaded config from {config_json_path}")

        self.conditions = CustomConditions()
        self.states = CustomStates()

        StateMemory.setVariable("agent_model",   session.agent_model)
        StateMemory.setVariable("agent_api_key", session.openai_api_key)
        StateMemory.setVariable("tavily_api_key", session.tavily_api_key)
        logging.debug("[StateMachine] Session config seeded from WS handshake")

    def __parse_function_args(self, arguments: List[Any]) -> List[Any]:
        args = copy.deepcopy(arguments)
        for index, arg in enumerate(args):
            if isinstance(arg, str):
                if arg.startswith("${"):
                    variable_name = arg[2:-1]
                    args[index] = StateMemory.getVariable(variable_name)

            elif isinstance(arg, list):
                for sub_index, sub_arg in enumerate(arg):
                    if isinstance(sub_arg, str) and sub_arg.startswith("${"):
                        variable_name = sub_arg[2:-1]
                        arg[sub_index] = StateMemory.getVariable(variable_name)

            elif isinstance(arg, dict):
                for key, value in arg.items():
                    if isinstance(value, str) and value.startswith("${"):
                        variable_name = value[2:-1]
                        arg[key] = StateMemory.getVariable(variable_name)

        return args

    def __execute_state(self) -> None:
        self.current_state = self.state_machine[self.current_state_name]
        function_name = self.current_state["function"]
        raw_args = self.current_state.get("args", [])
        parsed_args = self.__parse_function_args(raw_args)

        logging.info(f"[StateMachine] --- {self.current_state_name} ({function_name})")

        state_method = getattr(self.states, function_name)
        state_method(*parsed_args)

    def __define_next_state(self) -> None:
        next_state_config = self.current_state["nextState"]

        if isinstance(next_state_config, str):
            self.current_state_name = next_state_config
            logging.info(f"[StateMachine] Next: {self.current_state_name}")
            return

        for condition_transition in next_state_config:
            condition_function_name = condition_transition["conditionFunction"]

            if isinstance(condition_function_name, bool):
                if condition_function_name:
                    self.current_state_name = condition_transition["nextState"]
                    logging.info(f"[StateMachine] Next: {self.current_state_name} (default)")
                    break
                continue

            condition_function = getattr(self.conditions, condition_function_name)
            condition_args = condition_transition.get("args", [])
            parsed_condition_args = self.__parse_function_args(condition_args)

            logging.debug(
                f"[StateMachine] Evaluating condition '{condition_function_name}' "
                f"with args {parsed_condition_args}"
            )

            if condition_function(*parsed_condition_args):
                self.current_state_name = condition_transition["nextState"]
                logging.info(f"[StateMachine] Next: {self.current_state_name}")
                break

    def __step(self) -> None:
        if self.current_state_name not in self.state_machine:
            raise RuntimeError(
                f"[StateMachine] Invalid state: '{self.current_state_name}' not found in config"
            )
        self.__execute_state()
        self.__define_next_state()

    def run(self) -> None:
        logging.info("[StateMachine] ==================== Session started ====================")
        while self.current_state_name != "EndFinal":
            session = get_session()
            if session and session.should_stop:
                logging.warning("[StateMachine] Session stopped by client — halting loop")
                break
            self.__step()
        logging.info("[StateMachine] ==================== Session complete ====================")

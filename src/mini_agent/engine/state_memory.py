import copy
import logging
from contextvars import ContextVar
from typing import Any, Dict, Union

_memory_context: ContextVar[Dict[str, Any]] = ContextVar("state_memory", default=None)
BRAIN_CONTEXT_WINDOW = 5


class StateMemory:

    _INITIAL_MEMORY: Dict[str, Any] = {
        "state_memory": {
            "updated_by_the_planner": {
                "high_level_goal": "",
                "planned_TODO": [],
            },
            "updated_by_the_brain": {
                "decision_taken": [{}],
                "tool_to_use": [{}],
                "tool_parameters": [{}],
                "TODO_updates": [{}],
            },
            "updated_by_tools": {
                "internet_search": [],
                "RAG_search": [],
                "ready_for_answer": [],
                "collect_human_input": [],
                "end": [],
            },
            "variables": {
                "agent_decision": {"dataType": "string", "value": ""},
                "current_step": {"dataType": "string", "value": "step 1"},
                "agent_setup_prompt": {"dataType": "string", "value": ""},
                "user_query": {"dataType": "string", "value": ""},
                "knowledge_base_topics": {"dataType": "string", "value": ""},
                "conversation_history": {"dataType": "list", "value": []},
                "system_events": {"dataType": "list", "value": []},
                "tokenCount": {"dataType": "list", "value": []},
                "answer_delivered":  {"dataType": "boolean", "value": False},
                "agent_model":    {"dataType": "string", "value": ""},
                "agent_api_key":  {"dataType": "string", "value": ""},
                "tavily_api_key": {"dataType": "string", "value": ""},
            },
        }
    }

    @classmethod
    def _get_memory(cls) -> Dict[str, Any]:
        memory = _memory_context.get(None)
        if memory is None:
            memory = copy.deepcopy(cls._INITIAL_MEMORY)
            _memory_context.set(memory)
        return memory

    @classmethod
    def reset(cls) -> None:
        _memory_context.set(copy.deepcopy(cls._INITIAL_MEMORY))
        logging.debug("[StateMemory] Reset to initial state")

    @classmethod
    def getVariable(cls, variable_name: str) -> Any:
        variables = cls._get_memory()["state_memory"]["variables"]
        if variable_name not in variables:
            logging.error(f"[StateMemory] Variable '{variable_name}' does not exist")
            raise RuntimeError(f"Variable '{variable_name}' does not exist")
        return variables[variable_name]["value"]

    @classmethod
    def setVariable(cls, variable_name: str, variable_value: Any) -> None:
        variables = cls._get_memory()["state_memory"]["variables"]
        if variable_name not in variables:
            logging.error(f"[StateMemory] Variable '{variable_name}' does not exist")
            raise RuntimeError(f"Variable '{variable_name}' does not exist")
        variables[variable_name]["value"] = variable_value

    @classmethod
    def updateVariable(cls, variable_name: str, update_value: Union[Dict, Any]) -> None:
        variables = cls._get_memory()["state_memory"]["variables"]
        if variable_name not in variables:
            logging.error(f"[StateMemory] Variable '{variable_name}' does not exist")
            raise RuntimeError(f"Variable '{variable_name}' does not exist")

        variable = variables[variable_name]
        current_value = variable["value"]
        data_type = variable["dataType"]

        if data_type == "list":
            if not isinstance(update_value, list):
                raise RuntimeError(f"updateVariable: update_value must be a list for '{variable_name}'")
            current_value.extend(update_value)
        elif data_type == "dict":
            if not isinstance(update_value, dict):
                raise RuntimeError(f"updateVariable: update_value must be a dict for '{variable_name}'")
            current_value.update(update_value)
        else:
            raise RuntimeError(f"updateVariable: dataType '{data_type}' is not updatable for '{variable_name}'")

        variables[variable_name]["value"] = current_value

    @classmethod
    def updatePlannerOutput(cls, high_level_goal: str, planned_TODO: list) -> None:
        planner = cls._get_memory()["state_memory"]["updated_by_the_planner"]
        planner["high_level_goal"] = high_level_goal
        planner["planned_TODO"] = planned_TODO
        logging.debug("[StateMemory] Planner output recorded")

    @classmethod
    def updateBrainOutput(
        cls,
        step: str,
        decision_taken: str,
        tool_to_use: str,
        tool_parameters: Any,
    ) -> None:
        brain = cls._get_memory()["state_memory"]["updated_by_the_brain"]

        brain["decision_taken"][0][step] = decision_taken
        brain["tool_to_use"][0][step] = tool_to_use
        brain["tool_parameters"][0][step] = tool_parameters

        logging.debug(f"[StateMemory] Brain output recorded for {step}")

    @classmethod
    def updateBrainTODO(cls, step: str, TODO_updates: list) -> None:
        brain = cls._get_memory()["state_memory"]["updated_by_the_brain"]
        brain["TODO_updates"][0][step] = TODO_updates
        logging.debug(f"[StateMemory] TODO_updates recorded for {step}")

    @classmethod
    def updateToolOutput(cls, tool_name: str, output: Any) -> None:
        updated_by_tools = cls._get_memory()["state_memory"]["updated_by_tools"]
        if tool_name not in updated_by_tools:
            logging.warning(f"[StateMemory] Unknown tool '{tool_name}' — adding dynamically")
            updated_by_tools[tool_name] = []
        updated_by_tools[tool_name].append(output)
        logging.debug(f"[StateMemory] Tool output updated: {tool_name}")

    @classmethod
    def incrementStep(cls) -> None:
        current = cls.getVariable("current_step")
        number_str = current.replace("step ", "").strip()
        try:
            next_number = int(number_str) + 1
        except ValueError:
            next_number = 2
        cls.setVariable("current_step", f"step {next_number}")

    @classmethod
    def _step_sort_key(cls, step_str: str) -> int:
        try:
            return int(step_str.replace("step ", "").strip())
        except ValueError:
            return 0

    @classmethod
    def _trim_brain_outputs(cls, brain_outputs: Dict[str, Any]) -> Dict[str, Any]:
        trimmed_brain_outputs = {}

        for output_key, output_value in brain_outputs.items():
            if not (
                isinstance(output_value, list)
                and output_value
                and isinstance(output_value[0], dict)
            ):
                trimmed_brain_outputs[output_key] = copy.deepcopy(output_value)
                continue

            latest_steps = sorted(
                output_value[0].items(),
                key=lambda item: cls._step_sort_key(item[0]),
            )[-BRAIN_CONTEXT_WINDOW:]
            trimmed_brain_outputs[output_key] = [dict(latest_steps)]

        return trimmed_brain_outputs

    @classmethod
    def _trim_tool_outputs(cls, tool_outputs: Dict[str, Any]) -> Dict[str, Any]:
        trimmed_tool_outputs = {}

        for tool_name, outputs in tool_outputs.items():
            if isinstance(outputs, list):
                trimmed_tool_outputs[tool_name] = copy.deepcopy(outputs[-BRAIN_CONTEXT_WINDOW:])
            else:
                trimmed_tool_outputs[tool_name] = copy.deepcopy(outputs)

        return trimmed_tool_outputs

    @classmethod
    def getBrainContext(cls) -> Dict[str, Any]:
        memory = cls._get_memory()["state_memory"]
        return {
            "user_query": cls.getVariable("user_query"),
            "current_step": cls.getVariable("current_step"),
            "answer_delivered": cls.getVariable("answer_delivered"),
            "conversation_history": copy.deepcopy(
                cls.getVariable("conversation_history")[-BRAIN_CONTEXT_WINDOW:]
            ),
            "system_events": copy.deepcopy(
                cls.getVariable("system_events")[-BRAIN_CONTEXT_WINDOW:]
            ),
            "updated_by_the_planner": copy.deepcopy(memory["updated_by_the_planner"]),
            "updated_by_the_brain": cls._trim_brain_outputs(memory["updated_by_the_brain"]),
            "updated_by_tools": cls._trim_tool_outputs(memory["updated_by_tools"]),
        }

    @classmethod
    def recordToHistory(cls, entry: Dict[str, Any]) -> None:
        step = cls.getVariable("current_step")
        entry_with_step = {"step": step, **entry}
        cls.updateVariable("conversation_history", [entry_with_step])
        logging.debug(f"[StateMemory] History entry recorded: {entry_with_step}")

    @classmethod
    def recordSystemEvent(cls, event: str, reason: str, **details: Any) -> None:
        step = cls.getVariable("current_step")
        event_entry = {
            "step": step,
            "actor": "system",
            "event": event,
            "reason": reason,
            **details,
        }
        cls.updateVariable("system_events", [event_entry])
        logging.debug(f"[StateMemory] System event recorded: {event_entry}")

    @classmethod
    def getTokenCount(cls) -> list:
        return cls.getVariable("tokenCount")

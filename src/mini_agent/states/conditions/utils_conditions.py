import logging


class UtilsConditions:

    def check_global_variable(self, condition_dict: dict) -> bool:
        actual_decision = condition_dict.get("read_agent_decision", "")
        expected_tool = condition_dict.get("tool_to_use", "")
        result = actual_decision == expected_tool

        logging.debug(
            f"[check_global_variable] '{actual_decision}' == '{expected_tool}' → {result}"
        )
        return result

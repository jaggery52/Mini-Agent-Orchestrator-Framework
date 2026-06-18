import logging

from mini_agent.engine.state_memory import StateMemory
from mini_agent.session import get_session


class LifeCycleStates:

    def start(self, args_dict: dict) -> None:
        agent_setup_prompt_flag = args_dict.get("agent_setup_prompt_flag", "false").lower()
        if agent_setup_prompt_flag == "true":
            agent_setup_prompt = args_dict.get("agent_setup_prompt", "")
            StateMemory.setVariable("agent_setup_prompt", agent_setup_prompt)
            logging.info(
                f"[START] Agent setup prompt loaded "
                f"({len(agent_setup_prompt.split())} words — "
                f"will be prefix-cached by OpenAI after first brain call)"
            )

        knowledge_base_topics = args_dict.get("knowledge_base_topics", "")
        StateMemory.setVariable("knowledge_base_topics", knowledge_base_topics)
        if knowledge_base_topics:
            logging.info(f"[START] Knowledge base: {knowledge_base_topics[:120]}")

        logging.info("[START] Session initialised — waiting for user input")

    def end(self, status: str) -> None:
        token_count = StateMemory.getTokenCount()
        step = StateMemory.getVariable("current_step")

        total_tokens = sum(
            entry.get("total_tokens", 0) for entry in token_count
        ) if token_count else 0
        cached_tokens = sum(
            entry.get("cached_tokens", 0) for entry in token_count
        ) if token_count else 0

        session = get_session()

        end_message_list = StateMemory._get_memory()["state_memory"]["updated_by_tools"].get("end", [])
        end_message = end_message_list[-1] if end_message_list else ""
        if end_message:
            session.send_sync({"type": "final_response", "content": end_message})

        session.send_sync({"type": "session_end", "status": status})

        logging.info(f"[END] Session complete — status: {status} | steps: {step} | tokens: {total_tokens} (cached: {cached_tokens})")

    def condition_check(self) -> None:
        logging.debug("[CONDITION_CHECK] Routing hub reached — evaluating conditions")

    def collect_human_input(self) -> None:
        follow_up_list = StateMemory._get_memory()["state_memory"]["updated_by_tools"].get("collect_human_input", [])
        follow_up_question = follow_up_list[-1] if follow_up_list else ""

        session = get_session()
        if follow_up_question:
            session.send_sync({"type": "follow_up_question", "content": follow_up_question})
        user_input = session.wait_for_input()

        if not user_input:
            user_input = "Please continue."

        StateMemory.setVariable("user_query", user_input)
        StateMemory.setVariable("answer_delivered", False)
        StateMemory.updateToolOutput("collect_human_input", user_input)
        StateMemory.recordToHistory({"actor": "user", "content": user_input})
        logging.info(f"[COLLECT_INPUT]  User input received: \"{user_input[:120]}\"")

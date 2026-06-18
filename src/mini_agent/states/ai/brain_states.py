import logging

from mini_agent.engine.state_memory import StateMemory
from mini_agent.models.brain_output import TODOUpdate
from mini_agent.session import get_session
from mini_agent.states.ai.llm.the_brain import TheBrain

_DECISION_LABELS = {
    "internet_search":     "I need to search the web for more information.",
    "RAG_search":          "I need to retrieve information from the knowledge base.",
    "collect_human_input": "I need to ask the user a clarifying question.",
    "ready_for_answer":    "I have enough information to answer the user's question.",
    "fallback_agent":      "I need to ask a contextual follow-up question.",
    "the_planner":         "I need to revise the plan.",
    "end":                 "The session should end.",
}


class BrainStates:
    def the_brain(self, args_dict: dict) -> None:
        api_key = args_dict.get("agent_api") or StateMemory.getVariable("agent_api_key")
        model   = args_dict.get("agent_model") or StateMemory.getVariable("agent_model")
        analyze_instructions_prompt = args_dict.get("analyze_instructions_prompt", "")
        available_tools = args_dict.get("available_tools", {})
        knowledge_base_topics = args_dict.get("knowledge_base_topics", "")

        agent_setup_prompt = StateMemory.getVariable("agent_setup_prompt")
        current_step = StateMemory.getVariable("current_step")
        brain_context = StateMemory.getBrainContext()

        logging.info(f"[BRAIN] {current_step} — calling LLM for decision")

        brain = TheBrain(
            api_key=api_key,
            model=model,
            analyze_instructions_prompt=analyze_instructions_prompt,
            available_tools=available_tools,
            agent_setup_prompt=agent_setup_prompt,
            knowledge_base_topics=knowledge_base_topics,
        )

        brain_output = brain.decide(brain_context)

        StateMemory.updateBrainOutput(
            step=current_step,
            decision_taken=brain_output.decision_taken,
            tool_to_use=brain_output.tool_to_use,
            tool_parameters=brain_output.tool_parameters.model_dump(exclude_none=True),
        )

        if brain_output.TODO_updates:
            StateMemory.updateBrainTODO(
                step=current_step,
                TODO_updates=[todo_update.model_dump() for todo_update in brain_output.TODO_updates],
            )

        effective_tool = brain_output.tool_to_use
        if (
            StateMemory.getVariable("answer_delivered") is True
            and brain_output.tool_to_use == "ready_for_answer"
        ):
            effective_tool = "fallback_agent"
            StateMemory.recordSystemEvent(
                event="routing_override",
                reason="answer_already_delivered",
                original_decision=brain_output.tool_to_use,
                effective_decision=effective_tool,
                summary=(
                    "The previous answer was already delivered, so a repeated "
                    "ready_for_answer decision was routed to fallback_agent "
                    "to ask a follow-up instead of regenerating the answer."
                ),
            )
            logging.warning(
                "[BRAIN] %s - answer already delivered; overriding "
                "ready_for_answer loop to fallback_agent",
                current_step,
            )

            planned_todo = StateMemory._get_memory()["state_memory"]["updated_by_the_planner"]["planned_TODO"]
            brain_output.TODO_updates = [
                TODOUpdate(
                    title=item.get("title", ""),
                    description="Answer already delivered — task complete.",
                    status="done",
                )
                for item in planned_todo
            ]
            StateMemory.updateBrainTODO(
                step=current_step,
                TODO_updates=[t.model_dump() for t in brain_output.TODO_updates],
            )

        StateMemory.setVariable("agent_decision", effective_tool)

        session = get_session()
        if session:
            session.send_sync({
                "type": "agent_thinking",
                "source": "brain",
                "step": current_step,
                "thought": brain_output.decision_taken,
                "decision": _DECISION_LABELS.get(effective_tool, effective_tool),
                "tool": effective_tool,
                "todo_updates": [
                    todo_update.model_dump() for todo_update in brain_output.TODO_updates
                ] if brain_output.TODO_updates else [],
            })

        tool_params = brain_output.tool_parameters

        if effective_tool == "ready_for_answer" and tool_params.response_instructions:
            StateMemory.updateToolOutput("ready_for_answer", tool_params.response_instructions)

        if effective_tool == "collect_human_input" and tool_params.follow_up_question:
            StateMemory.updateToolOutput("collect_human_input", tool_params.follow_up_question)

        if effective_tool == "end" and tool_params.end_message:
            StateMemory.updateToolOutput("end", tool_params.end_message)

        StateMemory.incrementStep()

        StateMemory.recordToHistory({
            "actor": "brain",
            "decision": brain_output.tool_to_use,
            "effective_decision": effective_tool,
            "reasoning": brain_output.decision_taken,
            "parameters": brain_output.tool_parameters.model_dump(exclude_none=True),
        })

        logging.info(f"[BRAIN] {current_step} — Decision: {brain_output.tool_to_use}")
        if effective_tool != brain_output.tool_to_use:
            logging.info(f"[BRAIN] {current_step} — Routed decision: {effective_tool}")
        logging.info(f"[BRAIN] {current_step} — Reasoning: {brain_output.decision_taken}")

        if brain_output.TODO_updates:
            logging.info("[BRAIN] TODO progress:")
            for todo_item in brain_output.TODO_updates:
                logging.info(f"[BRAIN]   [{todo_item.status}] {todo_item.title}")

import json
import logging
from typing import Any, Dict, Optional

from openai import OpenAI

from mini_agent.models.planner_output import PlannerOutput

MAX_RETRIES = 3

SYSTEM_PROMPT = (
    "You are the Planner. Your job is to convert a user goal into an ordered list of tool calls "
    "that the Brain will execute one by one.\n\n"
    "Each step in the plan is a single tool call. The available tools are:\n"
    "  - RAG_search: search the local knowledge base (use this first for domain-specific questions)\n"
    "  - internet_search: fetch live information from the web\n"
    "  - collect_human_input: ask the user one specific clarifying question\n"
    "  - ready_for_answer: compile everything and deliver the final answer (always the last step)\n"
    "  - the_planner: revise the plan mid-execution (use only in replan scenarios)\n"
    "  - end: refuse the request immediately when it is harmful, illegal, or unethical\n\n"
    "Rules:\n"
    "0. HARMFUL/ILLEGAL CHECK (HIGHEST PRIORITY): Before creating any plan, check the user goal. "
    "If the request involves illegal activity, doing something 'without permission' or 'without authorization', "
    "bypassing legal requirements, harmful or unethical content — create a single-step plan: "
    "tool='end', description explaining why the request is refused. Do not add any other steps.\n"
    "1. Every step must specify the exact tool AND the specific query or action for that tool.\n"
    "   Bad:  title='Research topic', tool=RAG_search, description='Find information about it'\n"
    "   Good: title='RAG Search', tool=RAG_search, description='Search for \"mini-agent state machine architecture and tool design\"'\n"
    "2. Use 3-5 steps maximum. Do not add steps that are obviously unnecessary.\n"
    "3. Use the condition field for optional steps — steps the Brain should skip if the condition is not met.\n"
    "   Example: condition='only if RAG results were empty or did not answer the question'\n"
    "4. Unless refusing a harmful request (single step with tool='end'), the last step must always be ready_for_answer.\n"
    "5. Only include RAG_search if the knowledge base contents (provided in the user message) are "
    "relevant to the user's goal. If the KB does not cover the topic, skip RAG_search entirely and "
    "use internet_search instead.\n"
    "   Order when RAG is relevant: collect_human_input → RAG_search → internet_search (if needed) → ready_for_answer.\n"
    "   Order when RAG is not relevant: collect_human_input → internet_search → ready_for_answer.\n"
    "6. On re-plan: preserve completed steps, revise remaining steps based on replan_instructions."
)


class ThePlanner:
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def plan(
        self,
        user_goal: str,
        knowledge_base_topics: str = "",
        replan_instructions: Optional[str] = None,
        existing_plan: Optional[Dict[str, Any]] = None,
    ) -> PlannerOutput:
        kb_line = f"Knowledge base contents: {knowledge_base_topics}" if knowledge_base_topics else "Knowledge base contents: none"

        if replan_instructions and existing_plan:
            user_message = (
                f"User goal: {user_goal}\n"
                f"{kb_line}\n\n"
                f"Existing plan:\n{json.dumps(existing_plan, indent=2)}\n\n"
                f"Replan instructions from the Brain:\n{replan_instructions}\n\n"
                "Revise the plan accordingly."
            )
        else:
            user_message = f"User goal: {user_goal}\n{kb_line}\n\nGenerate the execution plan."

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        last_error: Exception = RuntimeError("Planner call failed — unknown error")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.client.beta.chat.completions.parse(
                    model=self.model,
                    messages=messages,
                    response_format=PlannerOutput,
                )
                return response.choices[0].message.parsed
            except Exception as error:
                last_error = error
                logging.warning(f"[ThePlanner] Attempt {attempt}/{MAX_RETRIES} failed: {error}")

        raise RuntimeError(f"[ThePlanner] All {MAX_RETRIES} attempts failed. Last error: {last_error}")

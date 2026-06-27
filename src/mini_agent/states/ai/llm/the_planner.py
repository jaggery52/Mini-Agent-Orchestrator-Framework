import json
import logging
from typing import Any, Dict, Optional

from openai import OpenAI

from mini_agent.models.planner_output import PlannerOutput
from mini_agent.states.utils import render_tools

MAX_RETRIES = 3


def _build_system_prompt(available_tools: Dict[str, str], knowledge_base_topics: str = "") -> str:
    tools_block = render_tools(
        available_tools,
        include_internal=True,
        knowledge_base_topics=knowledge_base_topics,
    )
    return (
        "You are the Planner. Your job is to convert a user goal into an ordered list of tool calls "
        "that the Brain will execute one by one.\n\n"
        "Each step in the plan is a single tool call. You may ONLY use the tools listed below — never "
        "reference a tool that is not in this list. Each tool shows 'How it works (system)', the fixed "
        "mechanics of the tool, and 'When to use (your guidance)', the operator's instructions for this "
        "agent:\n"
        f"{tools_block}\n\n"
        "Rules:\n"
        "0. HARMFUL/ILLEGAL CHECK (HIGHEST PRIORITY): Before creating any plan, check the user goal. "
        "If the request involves illegal activity, doing something 'without permission' or 'without authorization', "
        "bypassing legal requirements, harmful or unethical content — create a single-step plan with the 'end' "
        "tool and a description explaining why the request is refused. Do not add any other steps.\n"
        "1. Every step must specify the exact tool AND the specific query or action for that tool.\n"
        "   Bad:  title='Research topic', tool=RAG_search, description='Find information about it'\n"
        "   Good: title='RAG Search', tool=RAG_search, description='Search for \"mini-agent state machine architecture and tool design\"'\n"
        "2. Use 3-5 steps maximum. Do not add steps that are obviously unnecessary.\n"
        "3. Use the condition field for optional steps — steps the Brain should skip if the condition is not met.\n"
        "   Example: condition='only if RAG results were empty or did not answer the question'\n"
        "4. Unless refusing a harmful request, the final step must be ready_for_answer.\n"
        "5. Only include RAG_search if the knowledge base contents (provided in the user message) are "
        "relevant to the user's goal. If the KB does not cover the topic and internet_search is available, "
        "use internet_search instead.\n"
        "6. On re-plan: preserve completed steps, revise remaining steps based on replan_instructions."
    )


class ThePlanner:
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def plan(
        self,
        user_goal: str,
        available_tools: Dict[str, str],
        knowledge_base_topics: str = "",
        replan_instructions: Optional[str] = None,
        existing_plan: Optional[Dict[str, Any]] = None,
    ) -> PlannerOutput:
        system_prompt = _build_system_prompt(available_tools, knowledge_base_topics)

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
            {"role": "system", "content": system_prompt},
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

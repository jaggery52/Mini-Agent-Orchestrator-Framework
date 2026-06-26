import json
import logging
from typing import Any, Dict

from openai import OpenAI

from mini_agent.models.brain_output import BrainOutput
from mini_agent.states.utils import render_tools

MAX_RETRIES = 3


class TheBrain:
    def __init__(
        self,
        api_key: str,
        model: str,
        analyze_instructions_prompt: str,
        available_tools: Dict[str, str],
        agent_setup_prompt: str,
        knowledge_base_topics: str = "",
    ):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.system_prompt = self._build_system_prompt(
            agent_setup_prompt=agent_setup_prompt,
            analyze_instructions=analyze_instructions_prompt,
            available_tools=available_tools,
            knowledge_base_topics=knowledge_base_topics,
        )

    def _build_system_prompt(
            self,
            agent_setup_prompt: str,
            analyze_instructions: str,
            available_tools: Dict[str, str],
            knowledge_base_topics: str = "",
        ) -> str:

        tools_block = render_tools(
            available_tools,
            include_internal=True,
            knowledge_base_topics=knowledge_base_topics,
        )

        return (
            f"{agent_setup_prompt}\n\n"
            "---\n\n"
            f"## Decision Instructions\n\n"
            f"{analyze_instructions}\n\n"
            "---\n\n"
            "## Available Tools\n\n"
            "You must choose exactly one of the following tools:\n"
            f"{tools_block}\n\n"
            "---\n\n"
            "## Output Format\n\n"
            "Respond with a JSON object matching the BrainOutput schema:\n"
            "{\n"
            '  "tool_to_use": "<one of the tool names above>",\n'
            '  "tool_parameters": {\n'
            '    "query": "<search query if applicable, else null>",\n'
            '    "response_instructions": "<instructions for response generator if tool is ready_for_answer, else null>",\n'
            '    "follow_up_question": "<question to ask user if tool is collect_human_input, else null>",\n'
            '    "replan_instructions": "<instructions for the planner if tool is the_planner, else null>",\n'
            '    "end_message": "<farewell or refusal message if tool is end, else null>"\n'
            "  },\n"
            '  "decision_taken": "<detailed reasoning for your decision>"\n'
            "}\n\n"
            "Important rules:\n"
            "Most important: If user's question is harmful/illegal/unethical, "
            "and even if the_planner already planned a TODO, ignore all the TODO and set them not relevant, "
            "and refuse to answer and end the session immediately with tool_to_use 'end'.\n"
            "- Populate only the tool_parameters fields relevant to the chosen tool.\n"
            "- decision_taken must summarise what you know so far and why you chose this tool.\n"
            "- updated_by_tools values are ordered lists (oldest → newest). An empty list means "
            "  the tool has not been called yet. Multiple entries mean the tool was called more "
            "  than once — analyse ALL entries when reasoning, not just the last one.\n"
            "- system_events contains deterministic framework/runtime events, not user messages "
            "  and not tool results. Entries with actor='system' are reliable operational facts "
            "  about routing, guards, and state transitions. Use them to avoid repeating blocked "
            "  behavior, but do not mention internal routing, guard, or override details in any "
            "  user-facing response.\n"
            "- If you previously ran a tool (internet_search, RAG_search), summarise those "
            "  results in decision_taken before deciding whether to run another tool or answer.\n"
            "- Keep looping through tools until you have enough information to produce a "
            "  complete, accurate answer — then use ready_for_answer.\n"
            "- When tool_to_use is 'end', populate end_message with a short, final message. "
            "  For a user farewell: say goodbye only. "
            "  For a harmful/illegal/unethical request: briefly state why you cannot help. "
            "  Never include follow-up invitations (e.g. 'feel free to ask', 'let me know') — "
            "  the session is ending and there will be no further interaction."
            "\n\n"
        )

    def decide(self, brain_context: Dict[str, Any]) -> BrainOutput:
        user_message = (
            "Current agent state:\n\n"
            + json.dumps(brain_context, indent=2, ensure_ascii=False)
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]

        last_error: Exception = RuntimeError("Brain call failed — unknown error")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.client.beta.chat.completions.parse(
                    model=self.model,
                    messages=messages,
                    response_format=BrainOutput,
                )

                brain_output: BrainOutput = response.choices[0].message.parsed

                usage = response.usage
                cached_tokens = 0
                if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                    cached_tokens = getattr(usage.prompt_tokens_details, "cached_tokens", 0)

                logging.info(
                    f"[TheBrain] Tokens — prompt: {usage.prompt_tokens}, "
                    f"cached: {cached_tokens}, "
                    f"completion: {usage.completion_tokens}, "
                    f"total: {usage.total_tokens}"
                )

                if cached_tokens > 0:
                    logging.info(
                        f"[TheBrain] Prompt cache HIT — {cached_tokens} tokens served from cache"
                    )

                from mini_agent.engine.state_memory import StateMemory
                StateMemory.updateVariable("tokenCount", [{
                    "prompt_tokens": usage.prompt_tokens,
                    "cached_tokens": cached_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                }])

                return brain_output

            except Exception as error:
                last_error = error
                logging.warning(
                    f"[TheBrain] Attempt {attempt}/{MAX_RETRIES} failed: {error}"
                )

        raise RuntimeError(
            f"[TheBrain] All {MAX_RETRIES} attempts failed. Last error: {last_error}"
        )

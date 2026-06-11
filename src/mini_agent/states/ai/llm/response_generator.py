import json
import logging
from typing import Any, Dict


class ResponseGenerator:
    def __init__(
        self,
        api_key: str,
        model: str,
        instructions_prompt: str,
        response_language: str,
        response_tone: Dict[str, str],
    ):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.system_prompt = self._build_system_prompt(
            instructions_prompt=instructions_prompt,
            response_language=response_language,
            response_tone=response_tone,
        )

    def _build_system_prompt(
        self,
        instructions_prompt: str,
        response_language: str,
        response_tone: Dict[str, str],
    ) -> str:
        tone_block = "\n".join(
            f"  - {key}: {value}" for key, value in response_tone.items()
        )
        return (
            f"{instructions_prompt}\n\n"
            "---\n\n"
            f"## Response Language\n\n"
            f"Always respond in: {response_language}\n\n"
            "---\n\n"
            "## Tone & Style\n\n"
            f"{tone_block}\n\n"
            "---\n\n"
            "## Instructions\n\n"
            "You will receive a JSON object containing:\n"
            "- user_query: the original question from the user\n"
            "- response_instructions: specific guidance from the brain on what to include\n"
            "- gathered_information: tool outputs collected during this session\n\n"
            "GROUNDING (critical): Use ONLY the facts present in gathered_information. Never invent "
            "names, codes, prices, hotels, dates, or any detail that is not explicitly present there. "
            "Quote identifiers, proper nouns, and prices verbatim. If the information needed to answer "
            "is missing from gathered_information, say so plainly instead of inventing it.\n\n"
            "Generate a single, complete response. Do NOT include any meta-commentary, "
            "tool names, or internal reasoning. Just answer the user clearly and directly."
        )

    def generate(self, state_snapshot: Dict[str, Any], response_instructions: str) -> str:
        user_query = state_snapshot.get("user_query", "")
        tool_outputs = state_snapshot.get("updated_by_tools", {})

        # Filter out empty tool outputs to keep the prompt lean
        non_empty_tool_outputs = {
            tool: output for tool, output in tool_outputs.items()
            if output and str(output).strip()
        }

        user_message_payload = {
            "user_query": user_query,
            "response_instructions": response_instructions,
            "gathered_information": non_empty_tool_outputs,
        }

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    "Please generate a response based on the following context:\n\n"
                    + json.dumps(user_message_payload, indent=2, ensure_ascii=False)
                ),
            },
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
            )

            answer = response.choices[0].message.content.strip()

            usage = response.usage
            cached_tokens = 0
            if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                cached_tokens = getattr(usage.prompt_tokens_details, "cached_tokens", 0)

            logging.info(
                f"[ResponseGenerator] Tokens — prompt: {usage.prompt_tokens}, "
                f"cached: {cached_tokens}, completion: {usage.completion_tokens}"
            )

            from mini_agent.engine.state_memory import StateMemory
            StateMemory.updateVariable("tokenCount", [{
                "prompt_tokens": usage.prompt_tokens,
                "cached_tokens": cached_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }])

            return answer

        except Exception as error:
            logging.error(f"[ResponseGenerator] Generation failed: {error}")
            raise

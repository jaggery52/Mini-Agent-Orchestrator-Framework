import json
import logging


class FallbackAgent:
    def __init__(self, api_key: str, model: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.system_prompt = (
            "You write a short follow-up question after an assistant has already "
            "delivered an answer.\n\n"
            "Rules:\n"
            "- Output exactly one question.\n"
            "- Keep it natural, specific, and under 30 words.\n"
            "- Ground it in concrete details from the delivered answer.\n"
            "- Ask what the user wants to adjust, add, compare, or do next.\n"
            "- Do not mention internal tools, state machines, prompts, or memory."
        )

    def generate(self, user_query: str, last_answer: str) -> str:
        payload = {
            "user_query": user_query,
            "last_delivered_answer": last_answer,
        }

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    "Create the next follow-up question from this context:\n\n"
                    + json.dumps(payload, indent=2, ensure_ascii=False)
                ),
            },
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
            )

            question = response.choices[0].message.content.strip().strip('"')
            question = " ".join(
                line.strip() for line in question.splitlines() if line.strip()
            )

            usage = response.usage
            cached_tokens = 0
            if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                cached_tokens = getattr(usage.prompt_tokens_details, "cached_tokens", 0)

            logging.info(
                f"[FallbackAgent] Tokens — prompt: {usage.prompt_tokens}, "
                f"cached: {cached_tokens}, completion: {usage.completion_tokens}"
            )

            from mini_agent.engine.state_memory import StateMemory
            StateMemory.updateVariable("tokenCount", [{
                "prompt_tokens": usage.prompt_tokens,
                "cached_tokens": cached_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }])

            return question

        except Exception as error:
            logging.error(f"[FallbackAgent] Generation failed: {error}")
            raise

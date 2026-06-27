from typing import Dict
from mini_agent.states.tool_registry import TOOL_REGISTRY

def render_tools(available_tools: Dict[str, str], *, include_internal: bool = False, knowledge_base_topics: str = "", ) -> str:
    lines = []
    for name, user_desc in available_tools.items():
        guidance = user_desc
        if name == "RAG_search" and knowledge_base_topics:
            guidance = (
                f"{user_desc} — {knowledge_base_topics}. "
                "ONLY use this tool for questions about these specific topics."
            )
            if "internet_search" in available_tools:
                guidance += " For all other subjects use internet_search instead."

        if include_internal:
            lines.append(f"  - {name}:")
            internal = TOOL_REGISTRY.get(name)
            if internal:
                lines.append(f"      How it works (system): {internal}")
            lines.append(f"      When to use (your guidance): {guidance}")
        else:
            lines.append(f"  - {name}: {guidance}")

    return "\n".join(lines)

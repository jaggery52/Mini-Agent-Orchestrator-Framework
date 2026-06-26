"""Shared helpers for state handlers and the LLM wrappers they drive.

This is the home for cross-cutting state utilities — import what you need from
here rather than duplicating logic in individual state modules.
"""

from typing import Dict

from mini_agent.states.tool_registry import TOOL_REGISTRY


def render_tools(
    available_tools: Dict[str, str],
    *,
    include_internal: bool = False,
    knowledge_base_topics: str = "",
) -> str:
    """Render an AI block's tool list for its system prompt.

    ``available_tools`` is the user's ``{tool_name: description}`` map for this
    block (the user's *why/when* guidance). When ``include_internal`` is set,
    each tool is also annotated with its framework ``TOOL_REGISTRY`` line (the
    *how it works* mechanics), clearly distinguished from the user's guidance.

    ``RAG_search`` gets dynamic, per-session scoping from ``knowledge_base_topics``
    (which is only known at connect time, not at flow-design time). The fallback
    to ``internet_search`` is only mentioned when that tool is itself available.
    """
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

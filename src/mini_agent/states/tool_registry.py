"""Framework-owned registry of how each internal tool actually works.

These are the *system* descriptions — the mechanics of every built-in tool the
agent can route to (names mirror the ``BrainOutput`` / ``PlannerOutput`` Literal).
They are paired with the user's own per-block ``available_tools`` descriptions
(which say *why/when* to use a tool) when rendering an AI block's prompt — see
``mini_agent.states.utils.render_tools``.
"""

TOOL_REGISTRY: dict[str, str] = {
    "internet_search": (
        "Runs a live web search (Tavily) for a given query and returns summarized "
        "results — current, time-sensitive information not in the knowledge base."
    ),
    "RAG_search": (
        "Embeds the query and retrieves the most relevant chunks from the "
        "per-session vector knowledge base built from the user's uploaded documents."
    ),
    "collect_human_input": (
        "Pauses execution to ask the user a single question, then resumes with "
        "their reply available to the agent."
    ),
    "ready_for_answer": (
        "Hands off to the response generator to compose and deliver the final "
        "answer from everything gathered so far — the terminal step of a plan."
    ),
    "the_planner": (
        "Re-runs the planner to revise the remaining plan based on "
        "replan_instructions when the brief changes mid-execution."
    ),
    "end": (
        "Ends the session immediately with a short end_message; no further tools "
        "run (used for farewells or refusing harmful/illegal requests)."
    ),
}

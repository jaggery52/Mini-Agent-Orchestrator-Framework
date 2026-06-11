from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class TODOItem(BaseModel):
    title: str = Field(description="Short label for this step (e.g. 'RAG Search', 'Internet Search')")
    tool: Literal[
        "internet_search",
        "RAG_search",
        "collect_human_input",
        "ready_for_answer",
        "the_planner",
        "end",
    ] = Field(description="The exact tool the Brain should call for this step")
    description: str = Field(
        description="Specific query, question, or action for this tool call — be concrete, not generic"
    )
    condition: Optional[str] = Field(
        default=None,
        description="If set, this step is conditional — execute only when this condition is true (e.g. 'only if RAG results were empty or insufficient')"
    )


class PlannerOutput(BaseModel):
    high_level_goal: str = Field(description="One-sentence summary of the overall goal")
    planned_TODO: List[TODOItem] = Field(
        description="Ordered list of 3-5 tool-execution steps the Brain should follow to achieve the goal"
    )

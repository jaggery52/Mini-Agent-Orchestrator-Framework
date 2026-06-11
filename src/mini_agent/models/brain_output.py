from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ToolParameters(BaseModel):
    query: Optional[str] = Field(
        default=None,
        description="Search query for internet_search or RAG_search tools"
    )
    response_instructions: Optional[str] = Field(
        default=None,
        description="Instructions for the response_generator when tool_to_use is ready_for_answer"
    )
    follow_up_question: Optional[str] = Field(
        default=None,
        description="Follow-up question to ask the user when tool_to_use is collect_human_input"
    )
    replan_instructions: Optional[str] = Field(
        default=None,
        description="Instructions for the planner when tool_to_use is the_planner — describe what changed and what to revise"
    )
    end_message: Optional[str] = Field(
        default=None,
        description="Message to send to the user when tool_to_use is end — a polite farewell or a brief refusal explaining why the request cannot be handled"
    )


class TODOUpdate(BaseModel):
    title: str = Field(description="Task title matching a planned_TODO item")
    description: str = Field(description="Brief note on progress or outcome")
    status: Literal["done", "in progress", "not done", "not relevant"] = Field(
        description="Current status of this task"
    )


class BrainOutput(BaseModel):
    tool_to_use: Literal[
        "internet_search",
        "RAG_search",
        "collect_human_input",
        "ready_for_answer",
        "the_planner",
        "end",
    ] = Field(
        description="The tool the brain chose to use next."
    )
    tool_parameters: ToolParameters = Field(
        description="Parameters for the selected tool"
    )
    decision_taken: str = Field(
        description=(
            "Clear explanation of the reasoning behind this decision: "
            "what information was used, what was concluded, and why this tool was chosen."
        )
    )
    TODO_updates: Optional[List[TODOUpdate]] = Field(
        default=None,
        description=(
            "Updated status for each TODO item from the plan. "
            "Include all items from planned_TODO with their current status."
        )
    )

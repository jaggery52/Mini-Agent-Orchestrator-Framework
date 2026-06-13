from mini_agent.states.ai.brain_states import BrainStates
from mini_agent.states.ai.tool_states import ToolStates
from mini_agent.states.lifecycle_states import LifeCycleStates


class CustomStates(LifeCycleStates, BrainStates, ToolStates):
    pass

import logging

from mini_agent.engine.state_memory import StateMemory
from mini_agent.session import get_session
from mini_agent.states.ai.llm.fallback_agent import FallbackAgent
from mini_agent.states.ai.llm.response_generator import ResponseGenerator
from mini_agent.states.ai.llm.the_planner import ThePlanner
from mini_agent.states.ai.search.internet_search import InternetSearch
from mini_agent.states.ai.search.rag_search import RagSearch


class ToolStates:

    def the_planner(self, args_dict: dict) -> None:
        api_key = args_dict.get("api_key") or StateMemory.getVariable("agent_api_key")
        model   = args_dict.get("model")   or StateMemory.getVariable("agent_model")
        knowledge_base_topics = args_dict.get("knowledge_base_topics", "")

        user_goal = StateMemory.getVariable("user_query")
        existing_plan = StateMemory._get_memory()["state_memory"]["updated_by_the_planner"]
        replan_instructions = self._get_latest_brain_param("replan_instructions")

        is_replan = bool(replan_instructions and existing_plan.get("planned_TODO"))

        if is_replan:
            logging.info("[PLANNER] Re-planning requested by Brain")
            logging.info(f"[PLANNER] Replan instructions: {replan_instructions}")
        else:
            logging.info("[PLANNER] Generating initial plan")
            logging.info(f"[PLANNER] Goal: {user_goal}")

        planner = ThePlanner(api_key=api_key, model=model)
        result = planner.plan(
            user_goal=user_goal,
            knowledge_base_topics=knowledge_base_topics,
            replan_instructions=replan_instructions if is_replan else None,
            existing_plan=existing_plan if is_replan else None,
        )

        StateMemory.updatePlannerOutput(
            high_level_goal=result.high_level_goal,
            planned_TODO=[item.model_dump() for item in result.planned_TODO],
        )

        logging.info(f"[PLANNER] Goal: {result.high_level_goal}")
        logging.info(f"[PLANNER] Plan ({len(result.planned_TODO)} tasks):")
        for task_number, todo_item in enumerate(result.planned_TODO, 1):
            logging.info(f"[PLANNER]   {task_number}. {todo_item.title} — {todo_item.description}")

        session = get_session()
        if session:
            session.send_sync({
                "type": "agent_thinking",
                "source": "planner",
                "goal": result.high_level_goal,
                "plan": [{"title": t.title, "description": t.description} for t in result.planned_TODO],
            })

    def internet_search(self, args_dict: dict) -> None:
        api_key = args_dict.get("api_key") or StateMemory.getVariable("tavily_api_key")

        query = self._get_latest_brain_param("query")
        if not query:
            query = StateMemory.getVariable("user_query")
            logging.warning("[INTERNET_SEARCH] No query in brain params — falling back to user_query")

        session = get_session()
        if session:
            session.send_sync({"type": "agent_thinking", "source": "tool", "message": "Searching the web for information..."})

        search_depth = args_dict.get("search_depth", "basic")
        logging.info(f"[INTERNET_SEARCH] Searching: \"{query}\" (depth: {search_depth})")
        searcher = InternetSearch(api_key=api_key, search_depth=search_depth)
        search_results = searcher.search(query)

        StateMemory.updateToolOutput("internet_search", search_results)
        StateMemory.recordToHistory({
            "actor": "tool",
            "tool": "internet_search",
            "query": query,
            "summary": search_results[:200] + "..." if len(search_results) > 200 else search_results,
        })
        logging.info(f"[INTERNET_SEARCH]  Done ({len(search_results)} chars)")

    def RAG_search(self, args_dict: dict) -> None:
        api_key         = args_dict.get("api_key")        or StateMemory.getVariable("embedding_api_key")
        embedding_model = args_dict.get("embedding_model") or StateMemory.getVariable("embedding_model")

        query = self._get_latest_brain_param("query")
        if not query:
            query = StateMemory.getVariable("user_query")
            logging.warning("[RAG_SEARCH] No query in brain params — falling back to user_query")

        session = get_session()
        if session:
            session.send_sync({"type": "agent_thinking", "source": "tool", "message": "Extracting data from knowledge base..."})

        logging.info(f"[RAG_SEARCH] Searching knowledge base: \"{query}\"")
        rag = RagSearch(openai_api_key=api_key, embedding_model=embedding_model)
        rag.initialise()
        search_results = rag.search(query)

        StateMemory.updateToolOutput("RAG_search", search_results)
        StateMemory.recordToHistory({
            "actor": "tool",
            "tool": "RAG_search",
            "query": query,
            "summary": search_results[:200] + "..." if len(search_results) > 200 else search_results,
        })
        logging.info(f"[RAG_SEARCH]  Done ({len(search_results)} chars)")

    def response_generator(self, args_dict: dict) -> None:
        api_key = args_dict.get("api_key") or StateMemory.getVariable("agent_api_key")
        model   = args_dict.get("model")   or StateMemory.getVariable("agent_model")
        response_language = args_dict.get("response_language", "English")
        instructions_prompt = args_dict.get("instructions_prompt", "You are a helpful assistant.")
        response_tone = args_dict.get("response_tone", {})

        session = get_session()
        if session:
            session.send_sync({"type": "agent_thinking", "source": "tool", "message": "Preparing user's answer..."})

        logging.info("[RESPONSE_GENERATOR] Generating final answer for user")

        ready_for_answer_list = StateMemory._get_memory()["state_memory"]["updated_by_tools"].get(
            "ready_for_answer", []
        )
        response_instructions = ready_for_answer_list[-1] if ready_for_answer_list else ""

        brain_context = StateMemory.getBrainContext()

        generator = ResponseGenerator(
            api_key=api_key,
            model=model,
            instructions_prompt=instructions_prompt,
            response_language=response_language,
            response_tone=response_tone,
        )

        answer = generator.generate(
            state_snapshot=brain_context,
            response_instructions=response_instructions,
        )

        session.send_sync({"type": "final_response", "content": answer})
        StateMemory.setVariable("answer_delivered", True)

        StateMemory.updateToolOutput("ready_for_answer", answer)
        StateMemory.recordToHistory({
            "actor": "agent",
            "answered_query": StateMemory.getVariable("user_query"),
            "answered": True,
            "content": answer[:200] + "..." if len(answer) > 200 else answer,
        })
        logging.info(f"[RESPONSE_GENERATOR] Final response ({len(answer)} chars):\n{answer}")
        logging.info("[RESPONSE_GENERATOR]  Response delivered to user")

    def fallback_agent(self, args_dict: dict) -> None:
        api_key = args_dict.get("api_key") or StateMemory.getVariable("agent_api_key")
        model   = args_dict.get("model")   or StateMemory.getVariable("agent_model")

        ready_for_answer_list = StateMemory._get_memory()["state_memory"]["updated_by_tools"].get(
            "ready_for_answer", []
        )
        last_answer = ready_for_answer_list[-1] if ready_for_answer_list else ""
        user_query = StateMemory.getVariable("user_query")

        if not last_answer:
            logging.warning("[FALLBACK_AGENT] No delivered answer found; generating generic follow-up")

        session = get_session()
        if session:
            session.send_sync({
                "type": "agent_thinking",
                "source": "tool",
                "message": "Preparing a follow-up question...",
            })

        logging.info("[FALLBACK_AGENT] Generating contextual follow-up question")
        fallback = FallbackAgent(api_key=api_key, model=model)
        question = fallback.generate(user_query=user_query, last_answer=last_answer)

        StateMemory.updateToolOutput("collect_human_input", question)
        StateMemory.recordToHistory({
            "actor": "tool",
            "tool": "fallback_agent",
            "summary": question,
        })
        logging.info(f"[FALLBACK_AGENT] Follow-up question: {question}")

    def _get_latest_brain_param(self, param_key: str) -> str:
        brain_params = StateMemory._get_memory()["state_memory"]["updated_by_the_brain"]["tool_parameters"]
        if not brain_params or not brain_params[0]:
            return ""

        step_keys = list(brain_params[0].keys())
        if not step_keys:
            return ""

        def step_sort_key(step_str: str) -> int:
            try:
                return int(step_str.replace("step ", "").strip())
            except ValueError:
                return 0

        latest_step_key = max(step_keys, key=step_sort_key)
        params_for_step = brain_params[0][latest_step_key]

        if isinstance(params_for_step, dict):
            return params_for_step.get(param_key, "")
        return ""

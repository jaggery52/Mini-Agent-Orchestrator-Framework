import logging
from typing import Any, Dict, List


class InternetSearch:
    MAX_CONTENT_CHARS_PER_RESULT = 1500
    MAX_RESULTS_TO_SUMMARISE = 4

    def __init__(self, api_key: str = "", search_depth: str = "basic"):
        self.tavily_api_key = api_key
        self.search_depth = search_depth
        self._tavily_client = None

        if api_key:
            try:
                from tavily import TavilyClient
                self._tavily_client = TavilyClient(api_key=api_key)
                logging.debug("[InternetSearch] Tavily client initialised")
            except ImportError:
                logging.warning("[InternetSearch] tavily-python not installed — will use DuckDuckGo fallback")
            except Exception as error:
                logging.warning(f"[InternetSearch] Tavily init failed: {error} — will use DuckDuckGo fallback")


    def search(self, query: str, max_results: int = 5) -> str:
        logging.info(f"[INTERNET_SEARCH] Query: '{query}'")

        results: List[Dict[str, Any]] = []

        if self._tavily_client:
            results = self._search_tavily(query, max_results)

        if not results:
            results = self._search_duckduckgo(query, max_results)

        if not results:
            logging.warning("[INTERNET_SEARCH] No results from any provider")
            return f"No search results found for: '{query}'"

        summary = self._format_results(query, results)
        logging.info(f"[INTERNET_SEARCH] Retrieved {len(results)} results — {len(summary)} chars summarised")
        logging.debug(f"[INTERNET_SEARCH] Full result:\n{summary}")
        return summary


    def _search_tavily(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        try:
            response = self._tavily_client.search(
                query=query,
                max_results=max_results,
                search_depth=self.search_depth,
                include_answer=True,
            )
            tavily_answer = response.get("answer", "")
            raw_results = response.get("results", [])
            results = [
                {
                    "title": result.get("title", ""),
                    "content": result.get("content", ""),
                    "url": result.get("url", ""),
                }
                for result in raw_results
            ]
            if tavily_answer:
                logging.info(f"[INTERNET_SEARCH] Tavily direct answer: {tavily_answer}")
                results.insert(0, {
                    "title": "Direct Answer",
                    "content": tavily_answer,
                    "url": "",
                })
            return results
        except Exception as error:
            logging.warning(f"[InternetSearch] Tavily search failed: {error}")
            return []

    def _search_duckduckgo(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                raw_results = list(ddgs.text(query, max_results=max_results, timelimit="d"))
            return [
                {
                    "title": result.get("title", ""),
                    "content": result.get("body", ""),
                    "url": result.get("href", ""),
                }
                for result in raw_results
            ]
        except ImportError:
            logging.warning("[InternetSearch] duckduckgo-search not installed")
            return []
        except Exception as error:
            logging.warning(f"[InternetSearch] DuckDuckGo search failed: {error}")
            return []


    def _format_results(self, query: str, results: List[Dict[str, Any]]) -> str:
        top_results = results[: self.MAX_RESULTS_TO_SUMMARISE]
        parts = [f"Search results for: '{query}'\n"]

        for index, result in enumerate(top_results, start=1):
            title = result.get("title", "Untitled")
            content = result.get("content", "").strip()
            url = result.get("url", "")

            truncated_content = (
                content[: self.MAX_CONTENT_CHARS_PER_RESULT] + "..."
                if len(content) > self.MAX_CONTENT_CHARS_PER_RESULT
                else content
            )

            url_line = f"URL: {url}\n" if url else ""
            parts.append(
                f"[{index}] {title}\n"
                f"{url_line}"
                f"{truncated_content}\n"
            )

        return "\n".join(parts)

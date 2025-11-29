from typing import List, Dict, Optional
from fastapi import WebSocket
import asyncio
import logging
from pydantic import BaseModel

from flashresearch.flash_research_runtime import FlashResearchRuntime
from gpt_researcher.llm_provider.generic.base import ReasoningEfforts
from gpt_researcher.utils.llm import create_chat_completion
from gpt_researcher.utils.enum import Tone

from utils import Config

logger = logging.getLogger(__name__)


class ResearchQuery(BaseModel):
    query: str
    researchGoal: str


class BreadthPlanningDecision(BaseModel):
    """Structured decision for breadth planning (number of subqueries)"""
    num_subqueries: int
    subqueries: List[ResearchQuery]  # List of generated subqueries
    reasoning: str


class AgenticPlanner:
    """Agent-based task planner that dynamically determines research breadth and depth"""

    def __init__(self, config: Config, user_query: str):
        self.config = config
        self.user_query = user_query
        self.existing_queries: List[str] = []
        self._existing_queries_lock = asyncio.Lock()

    async def get_existing_queries_snapshot(self) -> List[str]:
        async with self._existing_queries_lock:
            return list(self.existing_queries)

    async def add_existing_queries(self, queries: List[str]):
        async with self._existing_queries_lock:
            for q in queries:
                if q not in self.existing_queries:
                    self.existing_queries.append(q)

    async def plan_breadth(self, query: str, max_breadth: int) -> int:
        """Determine the number of subqueries (breadth) for the current level"""

        existing_queries = await self.get_existing_queries_snapshot()
        
        messages = [
            {"role": "system", "content": f"""You are an expert researcher generating search queries. Your task is to generate determine the OPTIMAL number of clear, non-overlapping search queries. 
EFFICIENCY IS CRITICAL: More subqueries do not necessarily lead to better research. Minimize waste and redundancy. Broad topics need more subqueries, narrow topics need fewer. 

SUBQUERY REQUIREMENTS:
- Do not exceed {max_breadth+2} subqueries
- Keep each subquery short and concise 
- Make each subquery targets a DISTINCT aspect
- Prefer fewer subqueries if coverage is sufficient
- Ensure subqueries are relevant to the high-level research goal: {self.user_query}
- Avoid overlap with existing queries:
{"\n".join(existing_queries) if existing_queries else "None"}
"""},
            {"role": "user", "content": f"""Research query: {query}
Return the minimum set of clear, non-overlapping subqueries that cover the goal. """}
        ]
        
        response = await create_chat_completion(
            messages=messages,
            llm_provider=self.config.strategic_llm_provider,
            model=self.config.strategic_llm_model,
            # NOTE: temperature set to 0 for reproducibility
            temperature=0.0,
            reasoning_effort=ReasoningEfforts.Medium.value,
            seed=42,
            response_format=BreadthPlanningDecision  # Use structured output
        )
        
        if isinstance(response, str):
            response = BreadthPlanningDecision.model_validate_json(response)
            # Make sure the number of subqueries is within the allowed range
            response.subqueries = response.subqueries[:max_breadth+2]
        return response


class FlashResearch(FlashResearchRuntime):
    """Enhanced FlashResearchRuntime with adaptive planning"""

    def __init__(
        self,
        query: str,
        config_path: str,
        depth: int = 1, # Depth of the research, starts at 1
        headers: Optional[Dict] = None,
        websocket: Optional[WebSocket] = None,
        tone: Tone = Tone.Objective,
        logs_dir: str = "research_progress.json",  # New parameter for logging
        progress_callback: Optional[callable] = None,  # New parameter for progress updates
        # Runtime-specific parameters
        max_task_execution_time: float = 300.0,
    ):
        super().__init__(
            query=query,
            config_path=config_path,
            depth=depth,
            headers=headers,
            websocket=websocket,
            tone=tone,
            logs_dir=logs_dir,
            progress_callback=progress_callback,
            max_task_execution_time=max_task_execution_time
        )

        self.task_planner = AgenticPlanner(config=self.config, user_query=query)

    async def generate_serp_queries(self, query: str, max_breadth: int) -> List[Dict[str, str]]:
        """Generate serp queries using the agentic planner"""

        response = await self.task_planner.plan_breadth(
            query=query,
            max_breadth=max_breadth
        )
        logger.debug(f"[FlashResearch] Task planner determined breadth: {len(response.subqueries)}")
        # With structured output, response is already parsed
        queries = [{"query": q.query, "researchGoal": q.researchGoal} for q in response.subqueries]

        try:
            await self.task_planner.add_existing_queries([q["query"] for q in queries])
        except Exception:
            logger.error(f"[FlashResearch] Failed to add existing queries to task planner: {str(e)}")
        
        return queries
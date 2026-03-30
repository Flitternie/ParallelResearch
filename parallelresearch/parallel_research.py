from typing import List, Dict, Optional
from fastapi import WebSocket
import asyncio
import logging
from pydantic import BaseModel

from parallelresearch.parallel_research_runtime import ParallelResearchRuntime
from gpt_researcher.llm_provider.generic.base import ReasoningEfforts
from gpt_researcher.utils.llm import create_chat_completion
from gpt_researcher.utils.enum import Tone

from utils import Config

logger = logging.getLogger(__name__)


class ResearchQuery(BaseModel):
    query: str
    researchGoal: str
    information_gain: float  # Expected information gain in [0, 1]
    complexity: int          # Estimated complexity in {1, ..., 5}


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
        
        accumulated_findings = "\n".join(existing_queries) if existing_queries else "None"

        messages = [
            {"role": "system", "content": f"""You are an expert researcher generating search queries. Your task is to propose a group of clear, non-overlapping search queries and predict the information gain and complexity of each query.

SUBQUERY REQUIREMENTS:
- Generate exactly {max_breadth} subqueries
- Keep queries clear and concise
- Make each subquery target a DISTINCT aspect
- Avoid near-duplicates and trivial variants
- Ensure queries are relevant to the high-level research goal: {self.user_query}
- Exclude overlap with existing research findings:
{accumulated_findings}

INFORMATION GAIN SCORING GUIDE:
- HIGH (0.7-1.0): Covers a clearly unexplored aspect; addresses a knowledge gap not present in accumulated findings
- MEDIUM (0.4-0.7): Partially overlapping with findings but adds meaningful new detail or a different perspective
- LOW (0.0-0.4): Largely redundant with existing findings; tangential to the research goal

COMPLEXITY SCORING GUIDE:
- 1-2: Narrow factual lookup; single authoritative source likely sufficient
- 3: Moderate synthesis; requires a few sources with some reasoning
- 4-5: Broad or contested topic; requires multi-source synthesis and reconciliation
"""},
            {"role": "user", "content": f"""Research query: {query}

Propose {max_breadth} clear, non-overlapping subqueries. For each subquery provide:
- query: <subquery string>
- researchGoal: <what specific aspect or information this query aims to uncover>
- information_gain: <float in [0, 1]>
- complexity: <integer in {{1, ..., 5}}>"""}
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
            # Filter out subqueries whose complexity cost exceeds their predicted information gain.
            # lambda=0.15 calibrates so that: complexity-5 queries require HIGH gain (>=0.75),
            # complexity-3 require MEDIUM gain (>=0.45), and complexity-1 tolerate LOW gain (>=0.15).
            _lambda = 0.15
            response.subqueries = [
                q for q in response.subqueries
                if q.information_gain >= _lambda * q.complexity
            ]
            response.subqueries = response.subqueries[:max_breadth]
        return response


class ParallelResearch(ParallelResearchRuntime):
    """Enhanced ParallelResearchRuntime with adaptive planning"""

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

    async def generate_serp_queries(self, query: str, num_queries: int) -> List[Dict[str, str]]:
        """Generate serp queries using the agentic planner"""

        response = await self.task_planner.plan_breadth(
            query=query,
            max_breadth=num_queries
        )
        logger.debug(f"[ParallelResearch] Task planner determined breadth: {len(response.subqueries)}")
        # With structured output, response is already parsed
        queries = [{"query": q.query, "researchGoal": q.researchGoal} for q in response.subqueries]

        try:
            await self.task_planner.add_existing_queries([q["query"] for q in queries])
        except Exception:
            logger.error(f"[ParallelResearch] Failed to add existing queries to task planner: {str(e)}")
        
        return queries
from typing import List, Dict, Any, Optional, Set
from fastapi import WebSocket
import asyncio
import logging
from datetime import datetime, timedelta
import traceback
from pydantic import BaseModel

from modified_parallel_deep_research import ParallelizedDeepResearch, AsyncTaskManager, AsyncQueryTask, TaskState, AsyncProgress
from modified_agent import GPTResearcher
from gpt_researcher.llm_provider.generic.base import ReasoningEfforts
from gpt_researcher.utils.llm import create_chat_completion
from gpt_researcher.utils.enum import ReportType, ReportSource, Tone

from build_vector_db import load_vector_db
from utils import Config, ResearchLogger, ResearchProgress, trim_context_to_word_limit

logger = logging.getLogger(__name__)


# Pydantic models for structured output
class ResearchQuery(BaseModel):
    query: str
    researchGoal: str


class BreadthPlanningDecision(BaseModel):
    """Structured decision for breadth planning (number of subqueries)"""
    num_subqueries: int
    subqueries: List[ResearchQuery]  # List of generated subqueries
    reasoning: str


class DepthPlanningDecision(BaseModel):
    """Structured decision for depth planning (whether to continue deeper)"""
    should_continue_depth: bool
    reasoning: str


class AgenticPlanner:
    """Agent-based task planner that dynamically determines research breadth and depth"""
    
    def __init__(self, config: Config, user_query: str = None):
        self.config = config
        self.user_query = user_query
        self.research_start_time = datetime.now()
    
    def _get_research_duration(self) -> str:
        """Get current research duration for efficiency prompts"""
        elapsed = datetime.now() - self.research_start_time
        minutes = int(elapsed.total_seconds() / 60)
        seconds = int(elapsed.total_seconds() % 60)
        return f"{minutes}m {seconds}s"
        
    async def plan_breadth(self, query: str, depth: int, research_context: Dict[str, Any] = None) -> int:
        """Determine the number of subqueries (breadth) for the current level"""
        
        # Prepare context information
        research_duration = self._get_research_duration()
        context_info = f"Research duration so far: {research_duration}"
        
        if research_context:
            learnings_count = len(research_context.get('learnings', []))
            visited_urls_count = len(research_context.get('visited_urls', []))
            context_info += f"\nCurrent research progress: {learnings_count} learnings, {visited_urls_count} URLs visited."
        
        messages = [
            {"role": "system", "content": f"""You are an expert research planner. Your task is to determine the OPTIMAL number of subqueries AND generate clear, non-overlapping search queries.

EFFICIENCY IS CRITICAL: More subqueries ≠ better research. Minimize waste!

Analyze these factors:
1. QUERY SPECIFICITY: Highly specific queries (names, dates, locations) need 1-2 subqueries. Broad topics may need 3-4.
2. DEPTH PENALTY: At depth ≥2, reduce subqueries significantly (usually 1-2 max)
3. EXISTING CONTEXT: If substantial research already exists, fewer new subqueries needed
4. DIMINISHING RETURNS: More subqueries often lead to redundant information

DECISION MATRIX:
- Depth 1 + Broad topic (e.g., "climate change impacts") → 3-4 subqueries
- Depth 1 + Specific topic (e.g., "Tesla Model 3 sales 2023") → 1-2 subqueries  
- Depth ≥2 + Any topic → 1-2 subqueries (focus on specific gaps)
- Rich existing context → Reduce by 1-2 subqueries
- >5min research time → Be very conservative (prefer 1-2 subqueries)

SUBQUERY REQUIREMENTS:
- Make each query focus on a DISTINCT aspect 
- Avoid overlap between queries
- Keep queries clear and concise 

EXAMPLES:
- "How does photosynthesis work?" (depth=1) → 2 subqueries (mechanisms, factors)
- "SpaceX Falcon Heavy launch schedule" (depth=1) → 1 subquery (very specific)
- Any follow-up at depth=2 → 1 subquery (drill down on specific aspect)

Maximum allowed: {self.config.max_breadth} subqueries. Aim for minimum effective number."""},
            {"role": "user", "content": f"""Original user query: {self.user_query}
Current research query: {query}
Current depth level: {depth}
{context_info}

Based on the decision matrix above, determine the MINIMUM effective number of subqueries needed.
Generate clear, non-overlapping search queries that are optimized for web search engines.
Remember: Speed and efficiency are paramount! Avoid redundancy."""}
        ]
        
        response = await create_chat_completion(
            messages=messages,
            llm_provider=self.config.llm_provider,
            model=self.config.reasoning_model,
            temperature=0.1,
            max_tokens=200,
            reasoning_effort=ReasoningEfforts.High.value,
            seed=42,
            response_format=BreadthPlanningDecision
        )
        
        if isinstance(response, str):
            response = BreadthPlanningDecision.model_validate_json(response)

        assert len(response.subqueries) == response.num_subqueries
        
        # Ensure the number is within reasonable bounds
        response.num_subqueries = max(1, min(self.config.max_breadth, response.num_subqueries))
        
        # Apply time-based efficiency constraints
        elapsed_minutes = (datetime.now() - self.research_start_time).total_seconds() / 60
        if elapsed_minutes > 5 and response.num_subqueries > 2:
            logger.warning(f"[TaskPlanner] Reducing subqueries from {response.num_subqueries} to 2 due to long research time ({elapsed_minutes:.1f}m)")
            response.num_subqueries = 2
            response.reasoning += f" (Time-constrained: {elapsed_minutes:.1f}m elapsed)"
        elif elapsed_minutes > 3 and response.num_subqueries > 3:
            logger.warning(f"[TaskPlanner] Reducing subqueries from {response.num_subqueries} to 3 due to research time ({elapsed_minutes:.1f}m)")
            response.num_subqueries = 3
            response.reasoning += f" (Time-aware: {elapsed_minutes:.1f}m elapsed)"

        logger.info(f"[TaskPlanner] Breadth decision for depth {depth}: {response.num_subqueries} subqueries.")
        logger.debug(f"[TaskPlanner] Breadth reasoning: {response.reasoning}")
        return response
            
    
    async def plan_depth(self, current_depth: int, parent_result: Dict[str, Any], 
                        all_research_context: Dict[str, Any] = None) -> DepthPlanningDecision:
        """Determine whether to continue to the next depth level"""
        
        # Prepare context from parent result
        learnings = parent_result.get('learnings', [])
        follow_ups = parent_result.get('followUpQuestions', [])
        
        parent_context = f"""
        Research Goal: {parent_result.get('researchGoal', 'N/A')}
        
        Learnings Found ({len(learnings)}):
        {chr(10).join([f"- {learning[:100]}..." if len(learning) > 100 else f"- {learning}" for learning in learnings[:3]])}
        {"... (and more)" if len(learnings) > 3 else ""}
        
        Follow-up Questions ({len(follow_ups)}):
        {chr(10).join([f"- {q[:100]}..." if len(q) > 100 else f"- {q}" for q in follow_ups[:5]])}
        {"... (and more)" if len(follow_ups) > 5 else ""}
        """
        
        # Prepare overall research context
        research_duration = self._get_research_duration()
        overall_context = f"Research duration so far: {research_duration}"
        
        if all_research_context:
            total_learnings = len(all_research_context.get('learnings', []))
            total_urls = len(all_research_context.get('visited_urls', []))
            overall_context += f"\nTotal research progress: {total_learnings} learnings, {total_urls} URLs visited."
        
        messages = [
            {"role": "system", "content": """You are an expert research strategist. Your task is to decide whether deeper research is justified.

CRITICAL: Default to STOPPING unless there's a compelling reason to continue. Time is precious!

TIME PRESSURE GUIDELINES:
- <5 minutes: May continue if truly justified
- >5 minutes: Strong bias toward stopping (efficiency matters!)
- >10 minutes: Almost always stop (diminishing returns)

STOP CONDITIONS (choose to stop if ANY apply):
1. SUFFICIENT COVERAGE: Core question already answered with good detail
2. SHALLOW FOLLOW-UPS: Follow-up questions are superficial or tangential  
3. REDUNDANT FINDINGS: New learnings repeat existing knowledge
4. DEPTH FATIGUE: Already at depth ≥2 (rarely worth going deeper)
5. SPECIFIC QUERY: Original query was narrow/specific (e.g. facts, dates, definitions)
6. TIME EFFICIENCY: Research taking too long relative to value gained
7. ADEQUATE PROGRESS: Sufficient learnings and URLs already collected

CONTINUE CONDITIONS (ALL must apply):
1. CLEAR KNOWLEDGE GAPS: Important aspects remain unexplored
2. RICH FOLLOW-UPS: Deep, meaningful follow-up questions emerge
3. COMPLEX TOPIC: Multi-faceted subject requiring layered investigation
4. LOW DEPTH: Currently at depth 1 with genuinely complex topic
5. TIME EFFICIENT: Research duration is still reasonable (~5 minutes)

EXAMPLES:
- "What is machine learning?" → STOP after depth 1 (basic concepts covered)
- "How do neural networks work?" → CONTINUE to depth 2 only if gaps in architecture/training
- "Tesla stock price today" → STOP after depth 1 (factual query)
- "Impact of AI on society" → MAY continue to depth 2 if major domains unexplored

Be ruthlessly selective. Most research should stop at depth 1-2."""},
            {"role": "user", "content": f"""Original user query: {self.user_query}
Current depth: {current_depth}
Maximum allowed depth: {self.config.max_depth}

Parent research result:
{parent_context}

{overall_context}

pply the STOP/CONTINUE criteria above, with special attention to time efficiency.
Should we continue to depth {current_depth + 1}?"""}
        ]
        
        response = await create_chat_completion(
            messages=messages,
            llm_provider=self.config.llm_provider,
            model=self.config.reasoning_model,
            temperature=0.1,
            max_tokens=300,
            reasoning_effort=ReasoningEfforts.High.value,
            seed=42,
            response_format=DepthPlanningDecision
        )
        
        if isinstance(response, str):
            response = DepthPlanningDecision.model_validate_json(response)
        
        # Apply hard constraints
        if current_depth >= self.config.max_depth:
            response.should_continue_depth = False
            response.reasoning += f" (Hard limit: max_depth={self.config.max_depth} reached)"
        
        
        logger.info(f"[TaskPlanner] Depth decision for level {current_depth}: "
                    f"Continue={response.should_continue_depth}")
        logger.debug(f"[TaskPlanner] Depth reasoning: {response.reasoning}")
        
        return response


class FlashResearch(ParallelizedDeepResearch):
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
    ):
        super().__init__(
            query=query,
            config_path=config_path,
            depth=depth,
            headers=headers,
            websocket=websocket,
            tone=tone,
            logs_dir=logs_dir,
            progress_callback=progress_callback
        )
        self.task_planner = AgenticPlanner(config=self.config, user_query=query)


    async def plan_serp_queries(self, query: str, depth: int, context: str) -> List[Dict[str, str]]:
        """Generate SERP queries for research"""

        response = await self.task_planner.plan_breadth(
            query=query, 
            depth=depth, 
            research_context=context
        )

        logger.debug(f"[FlashResearch] Task planner determined breadth: {response.num_subqueries} for depth {depth}")

        # convert response to structured format
        if isinstance(response, str):
            try:
                response = BreadthPlanningDecision.model_validate_json(response)
            except Exception as e:
                logger.error(f"Failed to parse SERP queries response: {str(e)}")
                logger.error(f"Response content: {response}")
                raise ValueError("Failed to parse SERP queries response")

        # With structured output, response is already parsed
        queries = [{"query": q.query, "researchGoal": q.researchGoal} for q in response.subqueries]

        return queries

    async def deep_research(
        self,
        query: str,
        breadth: int,
        depth: int,
        learnings: List[str] = None,
        citations: Dict[str, str] = None,
        visited_urls: Set[str] = None,
        on_progress = None,
        parent_node_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Async-based parallel research using asyncio task management"""
        logger.debug(f"[FlashResearch] async parallel research called with query: {query[:100]}..., breadth: {breadth}, depth: {depth}")
        
        # Initialize async task manager and progress tracker
        task_manager = AsyncTaskManager()
        progress_tracker = AsyncProgress(depth, breadth)
        
        # Add initial data if provided
        if learnings:
            for learning in learnings:
                await task_manager.add_learning(learning)
        if citations:
            for learning, citation in citations.items():
                await task_manager.add_citation(learning, citation)
        if visited_urls:
            await task_manager.add_visited_urls(visited_urls)

        # Log the start of this research level
        current_node_id = self.logger.add_node(
            depth=depth,
            breadth=breadth,
            query=query,
            parent_id=parent_node_id,
            status="started",
            operation="plan",
            start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        # Use task planner to determine optimal breadth for this level
        current_research_context = await task_manager.get_all_data()

        # Generate initial queries (NOTE: Now controlled by AGENT-BASED TASK PLANNER)
        serp_queries = await self.plan_serp_queries(query, depth, current_research_context)
        
        logger.debug(f"[FlashResearch] Generated {len(serp_queries)} initial queries")
        
        # Create and launch initial async tasks
        tasks = []
        for serp_query in serp_queries:
            task_id = await task_manager.create_task_id()
            query_task = AsyncQueryTask(serp_query, depth, breadth, current_node_id, task_id)
            await task_manager.register_task(query_task)
            
            # Create asyncio task
            asyncio_task = asyncio.create_task(
                self._async_research(
                    query_task, task_manager, progress_tracker, on_progress
                )
            )
            query_task.asyncio_task = asyncio_task
            tasks.append(asyncio_task)

        logger.debug(f"[FlashResearch] All initial tasks launched, waiting for completion...")
        
        # Wait for all tasks (including recursive ones) to complete
        await self._wait_for_all_tasks_completion(task_manager)
        
        # Get final results
        final_data = await task_manager.get_all_data()
        
        # Trim context to stay within word limits
        trimmed_context = trim_context_to_word_limit(final_data['context'])
        logger.info(f"Trimmed context from {len(final_data['context'])} items to {len(trimmed_context)} items")
        final_data['context'] = trimmed_context

        # Log completion
        self.logger.update_node(
            node_id=current_node_id,
            status="completed",
            results={
                'learnings': final_data['learnings'],
                'citations': final_data['citations']
            },
            visited_urls=final_data['visited_urls'],
            end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        logger.debug(f"[FlashResearch] async research completed")
        return final_data

    async def _async_research(self, task: AsyncQueryTask, task_manager: AsyncTaskManager,
                               progress_tracker: AsyncProgress, on_progress=None) -> None:
        """Process a single query task asynchronously with semaphore-controlled concurrency"""
        async with self.semaphore:  # Control concurrency
            try:
                task.state = TaskState.RUNNING
                task.start_time = datetime.now()
                
                logger.debug(f"[FlashResearch] Processing async task {task.task_id} at depth {task.depth} for query: {task.serp_query['query']}")
                
                # Update progress
                await progress_tracker.update_progress(current_query=task.serp_query['query'])
                if on_progress:
                    progress_data = await progress_tracker.get_progress_copy()
                    progress = ResearchProgress(progress_data['total_depth'], progress_data['total_breadth'])
                    progress.current_depth = progress_data['current_depth']
                    progress.current_breadth = progress_data['current_breadth']
                    progress.current_query = progress_data['current_query']
                    progress.total_queries = progress_data['total_queries']
                    progress.completed_queries = progress_data['completed_queries']
                    on_progress(progress)

                # Log the start of processing this query
                query_node_id = self.logger.add_node(
                    depth=task.depth,
                    breadth=task.breadth,
                    query=task.serp_query['query'],
                    parent_id=task.parent_node_id,
                    research_goal=task.serp_query['researchGoal'],
                    status="started",
                    operation="research",
                    start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )

                # Initialize researcher and conduct research
                researcher = GPTResearcher(
                    query=task.serp_query['query'],
                    report_type=ReportType.ResearchReport.value,
                    report_source=self.config.report_source,
                    # NOTE: Using the langchain vector store
                    vector_store=load_vector_db("vector_db") if self.config.report_source == ReportSource.LangChainVectorStore.value else None,
                    tone=self.tone,
                    websocket=self.websocket,
                    config_path=self.config_path,
                    headers=self.headers,
                    log_handler=self.logger,
                    enable_enhanced_logging=self.enable_enhanced_logging,
                    parent_node_id=query_node_id
                )

                # Conduct research - this is already async
                await researcher.conduct_research()
                
                # Process results
                context = researcher.context
                visited = set(researcher.visited_urls)
                sources = researcher.research_sources
                
                # Process SERP results
                results = await self.process_serp_result(
                    query=task.serp_query['query'],
                    context=context
                )
                
                # Update progress
                await progress_tracker.update_progress(completed=1)
                
                # Log completion
                self.logger.update_node(
                    node_id=query_node_id,
                    status="completed",
                    results={
                        'learnings': results['learnings'],
                        'citations': results['citations']
                    },
                    visited_urls=visited,
                    end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )

                # Prepare result
                result = {
                    'node_id': query_node_id,
                    'learnings': results['learnings'],
                    'visited_urls': visited,
                    'followUpQuestions': results['followUpQuestions'],
                    'researchGoal': task.serp_query['researchGoal'],
                    'citations': results['citations'],
                    'context': context if context else "",
                    'sources': sources if sources else []
                }
                
                
                # Use task planner to determine if recursive tasks are needed (NOTE: Now controlled by AGENT-BASED TASK PLANNER)
                current_research_context = await task_manager.get_all_data()
                depth_decision = await self.task_planner.plan_depth(
                    current_depth=task.depth,
                    parent_result=result,
                    all_research_context=current_research_context
                )

                # Mark task as completed
                await task_manager.complete_task(task.task_id, result)
                
                if depth_decision.should_continue_depth:
                    logger.debug(f"[FlashResearch] Task planner decided to continue to depth {task.depth + 1}")
                    
                    try:
                        await self._generate_recursive_tasks(
                            result, task.depth, task.breadth, task_manager,
                            progress_tracker, on_progress
                        )
                    except Exception as e:
                        logger.error(f"[FlashResearch] Error generating recursive tasks: {e}")
                else:
                    logger.debug(f"[FlashResearch] Task planner decided to stop at depth {task.depth}. Reasoning: {depth_decision.reasoning}")
                
                logger.debug(f"[FlashResearch] Completed async task {task.task_id}")

            except asyncio.CancelledError:
                logger.info(f"[FlashResearch] Task {task.task_id} was cancelled")
                task.state = TaskState.CANCELLED
                await task_manager.complete_task(task.task_id, error=asyncio.CancelledError("Task cancelled"))
                raise
            except Exception as e:
                logger.error(f"[FlashResearch] Error in async task {task.task_id}: {str(e)}")
                logger.error(f"[FlashResearch] Exception traceback: {traceback.format_exc()}")
                task.state = TaskState.FAILED
                await task_manager.complete_task(task.task_id, error=e)

    async def _generate_recursive_tasks(self, parent_result: Dict[str, Any], current_depth: int, 
                                       current_breadth: int, task_manager: AsyncTaskManager,
                                       progress_tracker: AsyncProgress, on_progress=None):
        """Generate recursive tasks and launch them as async tasks"""
        try:
            # NOTE: Now using AGENT-BASED TASK PLANNER determined breadth
            new_depth = current_depth + 1
            
            # Create next query from parent result
            next_query = f"""
            Previous research goal: {parent_result['researchGoal']}
            Follow-up questions: {' '.join(parent_result['followUpQuestions'])}
            """
            
            # Create planning node for this recursive level
            recursive_planning_node_id = self.logger.add_node(
                depth=new_depth,
                breadth=current_breadth,
                query=next_query,
                parent_id=parent_result['node_id'],
                status="started",
                operation="plan",
                start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            logger.debug(f"[FlashResearch] Created recursive planning node: {recursive_planning_node_id} for depth {new_depth}")
            
            # Generate sub-queries for this recursive level (NOTE: Now controlled by AGENT-BASED TASK PLANNER)
            sub_queries = await self.plan_serp_queries(next_query, new_depth, parent_result)
            
            logger.debug(f"[FlashResearch] Generated {len(sub_queries)} recursive queries for depth {new_depth}")
            
            # Update the planning node with completion
            self.logger.update_node(
                node_id=recursive_planning_node_id,
                status="completed",
                results={"generated_queries": len(sub_queries)},
                end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # Create and launch recursive async tasks immediately
            for serp_query in sub_queries:
                task_id = await task_manager.create_task_id()
                query_task = AsyncQueryTask(serp_query, new_depth, current_breadth, recursive_planning_node_id, task_id)
                await task_manager.register_task(query_task)
                
                # Create and launch asyncio task immediately
                asyncio_task = asyncio.create_task(
                    self._async_research(
                        query_task, task_manager, progress_tracker, on_progress
                    )
                )
                query_task.asyncio_task = asyncio_task
                
                logger.debug(f"[FlashResearch] Launched recursive task {task_id} at depth {new_depth}")
            
            logger.debug(f"[FlashResearch] All recursive tasks launched for depth {new_depth}")
            
        except Exception as e:
            logger.error(f"[FlashResearch] Error in _generate_recursive_tasks: {str(e)}")
            logger.error(f"[FlashResearch] Exception traceback: {traceback.format_exc()}")

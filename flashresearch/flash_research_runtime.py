from typing import List, Dict, Any, Optional, Set
from fastapi import WebSocket
import asyncio
import logging
import time
from datetime import datetime
import traceback
from pydantic import BaseModel

from flashresearch.agent import GPTResearcher
from flashresearch.recursive_deep_research import TaskState, AsyncProgress, RecursiveDeepResearch, NodeResults as BaseNodeResults, AsyncTaskManager as BaseAsyncTaskManager, AsyncQueryTask

from gpt_researcher.llm_provider.generic.base import ReasoningEfforts
from gpt_researcher.utils.llm import create_chat_completion
from gpt_researcher.utils.enum import ReportType, ReportSource, Tone

from utils.vector_db import load_vector_db
from utils import Config, ResearchLogger, ResearchProgress, trim_context_to_word_limit

logger = logging.getLogger(__name__)


class NodeResults(BaseNodeResults):
    """Extended NodeResults with runtime monitoring data"""
    def __init__(self, node_id: int):
        super().__init__(node_id)
        # Runtime monitoring data
        self.goal_satisfied = False
        self.satisfaction_score = 0.0
        self.quality_score = 0.0
        self.termination_reason: Optional[str] = None
        self.execution_time = 0.0


class GoalSatisfactionDecision(BaseModel):
    """Structured decision for research goal satisfaction"""
    is_goal_satisfied: bool
    satisfaction_score: float  # 0.0 to 1.0
    quality_score: float  # Overall quality of current research
    reasoning: str


class AsyncTaskManager(BaseAsyncTaskManager):
    """Extended AsyncTaskManager with runtime monitoring capabilities"""
    def __init__(self, research_logger: ResearchLogger):
        super().__init__()
        self.research_logger = research_logger
        # Runtime monitoring
        self.llm_call_semaphore = asyncio.Semaphore(2)  # Limit concurrent LLM calls
        self.failed_llm_calls = 0
        self.max_failed_calls = 3
        self.llm_circuit_open = False
        self.circuit_reset_time = None
        # Track tasks for cancellation
        self.tasks: Dict[int, asyncio.Task] = {}  # Map node_id to asyncio.Task
        self.child_tasks: Dict[int, List[int]] = {}  # Map parent_node_id to list of child_node_ids
    
    async def register_node(self, node_id: int, parent_node_id: Optional[int] = None):
        """Register a new node using the extended NodeResults class"""
        async with self._lock:
            node_results = NodeResults(node_id)
            node_results.parent_node_id = parent_node_id
            self.node_results[node_id] = node_results

    async def update_runtime_data(self, node_id: int, goal_satisfied: bool = None, 
                                satisfaction_score: float = None, quality_score: float = None,
                                termination_reason: str = None, execution_time: float = None):
        """Update runtime monitoring data for a node"""
        async with self._lock:
            if node_id in self.node_results:
                node = self.node_results[node_id]
                if goal_satisfied is not None:
                    node.goal_satisfied = goal_satisfied
                if satisfaction_score is not None:
                    node.satisfaction_score = satisfaction_score
                if quality_score is not None:
                    node.quality_score = quality_score
                if termination_reason is not None:
                    node.termination_reason = termination_reason
                if execution_time is not None:
                    node.execution_time = execution_time

    async def get_node_results(self, node_id: int) -> Optional[Dict[str, Any]]:
        """Get merged results for a specific node with runtime data"""
        async with self._lock:
            if node_id not in self.node_results:
                return None
            
            node = self.node_results[node_id]
            return {
                'learnings': list(node.learnings),
                'citations': node.citations.copy(),
                'visited_urls': list(node.visited_urls),
                'context': list(node.context),
                'sources': list(node.sources),
                'runtime_data': {
                    'goal_satisfied': node.goal_satisfied,
                    'satisfaction_score': node.satisfaction_score,
                    'quality_score': node.quality_score,
                    'termination_reason': node.termination_reason,
                    'execution_time': node.execution_time
                }
            }

    async def evaluate_goal_satisfaction(self, research_goal: str, context: str, 
                                      learnings: List[str], config) -> GoalSatisfactionDecision:
        """Evaluate if research goal is satisfied (with circuit breaker)"""
        
        # Check circuit breaker
        if self.llm_circuit_open:
            if self.circuit_reset_time and time.time() > self.circuit_reset_time:
                self.llm_circuit_open = False
                self.failed_llm_calls = 0
                self.circuit_reset_time = None
            else:
                return GoalSatisfactionDecision(
                    is_goal_satisfied=False,
                    satisfaction_score=0,
                    quality_score=0,
                    reasoning="Circuit breaker active",
                )
        
        # Use semaphore to limit concurrent LLM calls
        async with self.llm_call_semaphore:
            try:
                return await asyncio.wait_for(
                    self._perform_goal_evaluation(research_goal, context, learnings, config),
                    timeout=30.0
                )
                
            except (asyncio.TimeoutError, Exception) as e:
                self.failed_llm_calls += 1
                if self.failed_llm_calls >= self.max_failed_calls:
                    self.llm_circuit_open = True
                    self.circuit_reset_time = time.time() + 60
                
                return GoalSatisfactionDecision(
                    is_goal_satisfied=False,
                    satisfaction_score=0,
                    quality_score=0,
                    reasoning=f"Evaluation error: {str(e)[:100]}",
                )
    
    async def _perform_goal_evaluation(self, research_goal: str, context: str, 
                                    learnings: List[str], config) -> GoalSatisfactionDecision:
        """Perform LLM-based goal evaluation"""
        
        # Prepare context summary
        context_summary = f"""
        Research Goal: {research_goal}
        
        Current Learnings ({len(learnings)}):
        {chr(10).join([f"- {learning[:150]}..." if len(learning) > 150 else f"- {learning}" for learning in learnings[:5]])}
        {"... (and more)" if len(learnings) > 5 else ""}
        
        Context Preview:
        {context[:1000] if context else "No context available"}
        {"..." if len(context) > 1000 else ""}
        """
        
        messages = [
            {"role": "system", "content": """You are an expert research quality evaluator. Determine if a research goal has been sufficiently satisfied based on current findings.

EVALUATION CRITERIA:
1. GOAL COVERAGE: Does the research adequately address the stated goal?
2. INFORMATION QUALITY: Are the findings comprehensive and reliable?
3. DEPTH SUFFICIENCY: Is there enough detail to answer the research question?
4. SOURCE DIVERSITY: Are findings from multiple credible sources?
5. COMPLETENESS: Are major aspects of the topic covered?

SATISFACTION SCORE:
- HIGH SATISFACTION (0.8-1.0): Goal fully satisfied, comprehensive coverage
- MEDIUM SATISFACTION (0.5-0.8): Goal mostly satisfied, minor gaps acceptable  
- LOW SATISFACTION (0.3-0.5): Goal partially satisfied, significant gaps remain
- INSUFFICIENT (0.0-0.3): Goal not satisfied, major research needed

QUALITY SCORING:
- EXCELLENT (0.8-1.0): Comprehensive, well-sourced, detailed
- GOOD (0.5-0.8): Adequate coverage, some depth
- FAIR (0.3-0.5): Basic coverage, limited depth
- POOR (0.0-0.3): Insufficient information

Be conservative - only mark as satisfied if the research truly addresses the goal comprehensively."""},
            {"role": "user", "content": f"""Evaluate the following research progress:

{context_summary}

Based on the research goal and current findings, determine:
1. Is the research goal satisfied?
2. Satisfaction score (0.0-1.0) of the research goal
3. Quality score (0.0-1.0) of current research
4. Reasoning for your decision

Consider efficiency - if the goal is mostly satisfied, recommend termination to save costs."""}
        ]
        
        response = await create_chat_completion(
            messages=messages,
            llm_provider=config.llm_provider,
            model=config.reasoning_model,
            temperature=0.0,
            max_tokens=400,
            reasoning_effort=ReasoningEfforts.Medium.value,
            seed=42,
            response_format=GoalSatisfactionDecision,
            usage_tag="monitor"
        )
        
        if isinstance(response, str):
            response = GoalSatisfactionDecision.model_validate_json(response)
        
        # Reset failed calls counter on success
        self.failed_llm_calls = max(0, self.failed_llm_calls - 1)
        
        return response

    async def add_child_task(self, parent_node_id: int, child_node_id: int):
        """Add a child node reference for cancellation tracking"""
        async with self._lock:
            if parent_node_id not in self.child_tasks:
                self.child_tasks[parent_node_id] = []
            self.child_tasks[parent_node_id].append(child_node_id)

    async def cancel_all_child_tasks(self, node_id: int):
        """Cancel all child tasks of a node recursively"""
        async with self._lock:
            if node_id in self.child_tasks:
                for child_node_id in self.child_tasks[node_id]:
                    if child_node_id in self.tasks and not self.tasks[child_node_id].done():
                        self.tasks[child_node_id].cancel()
                        self.research_logger.update_node(
                            node_id=child_node_id,
                            status=TaskState.CANCELLED.value,
                            end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        )
                        logger.info(f"[AsyncTaskManager] Cancelled child task {child_node_id} from parent termination {node_id}")
                # Also cancel children of children recursively
                for child_node_id in self.child_tasks[node_id]:
                    await self.cancel_all_child_tasks(child_node_id)
                del self.child_tasks[node_id]

    async def cancel(self, node_id: int):
        """Cancel a node and all its child tasks"""
        async with self._lock:
            if node_id in self.tasks:
                self.tasks[node_id].cancel()  # Remove await - cancel() is not async
            self.research_logger.update_node(
                node_id=node_id,
                status=TaskState.TERMINATED.value, 
                end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            logger.info(f"[AsyncTaskManager] Cancelled node {node_id}")
            if node_id in self.child_tasks:
                await self.cancel_all_child_tasks(node_id)
            logger.info(f"[AsyncTaskManager] Cancelled node {node_id} and all child tasks")

    async def are_all_child_tasks_complete(self, node_id: int) -> bool:
        """Check if all child tasks of a node are complete"""
        async with self._lock:
            if node_id not in self.child_tasks:
                return True
            return all(
                child_node_id not in self.tasks or self.tasks[child_node_id].done() 
                for child_node_id in self.child_tasks[node_id]
            )


class FlashResearchRuntime(RecursiveDeepResearch):
    """Enhanced RecursiveDeepResearch with runtime goal satisfaction monitoring and early termination"""
    
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
            progress_callback=progress_callback
        )
        
        # Runtime parameters
        self.satisfaction_threshold = self.config.runtime_satisfaction_threshold
        self.quality_threshold = self.config.runtime_quality_threshold
        self.max_task_execution_time = max_task_execution_time
        self.enable_early_termination = True  

        self.task_manager = AsyncTaskManager(self.logger)
        self.progress_tracker = AsyncProgress(depth, self.config.max_breadth)

    async def deep_research(
        self,
        query: str,
        breadth: int,
        depth: int,
        learnings: List[str] = None,
        citations: Dict[str, str] = None,
        visited_urls: Set[str] = None,
        on_progress = None,
        parent_node_id: Optional[int] = None,
        is_recursive: bool = False
    ) -> Dict[str, Any]:
        """Recursive async-based parallel research with runtime monitoring and early termination"""
        logger.debug(f"[FlashResearch] runtime research called with query: {query[:100]}..., breadth: {breadth}, depth: {depth}")

        # Log the start of this research level and register node for result tracking
        current_node_id = self.logger.add_node(
            depth=depth,
            breadth=breadth,
            query=query,
            parent_id=parent_node_id,
            status=TaskState.STARTED.value,
            operation="research" if is_recursive else "plan",
            start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        
        # Register node for hierarchical result tracking
        await self.task_manager.register_node(current_node_id, parent_node_id)
        
        # Track this node as a child of its parent for cancellation purposes
        if parent_node_id is not None:
            await self.task_manager.add_child_task(parent_node_id, current_node_id)
        
        # Add initial data if provided (only for root call with root node)
        if not is_recursive:
            if learnings:
                await self.task_manager.add_direct_learnings(current_node_id, learnings)
            if citations:
                await self.task_manager.add_direct_citations(current_node_id, citations)
            if visited_urls:
                await self.task_manager.add_direct_visited_urls(current_node_id, visited_urls)

        # For recursive calls, conduct research directly using proper task management
        if is_recursive:
            # Store current asyncio task for potential cancellation
            current_task = asyncio.current_task()
            if current_task:
                self.task_manager.tasks[current_node_id] = current_task
            
            # Create and register a proper AsyncQueryTask for this recursive call
            task_id = await self.task_manager.create_task_id()
            serp_query = {'query': query, 'researchGoal': f'Research depth {depth}'}
            query_task = AsyncQueryTask(serp_query, depth, breadth, parent_node_id, task_id)
            await self.task_manager.register_task(query_task)

            # Defer launching of recursive children until AFTER semaphore is released to avoid deadlock when concurrency=1
            pending_children = None
            monitor_task = None  # Allow access after semaphore block
            
            async with self.semaphore:  # Control concurrency
                researcher = None
                try:
                    query_task.state = TaskState.RUNNING
                    query_task.start_time = datetime.now()
                    start_time = time.time()
                    
                    logger.debug(f"[FlashResearch] Processing async task {task_id} at depth {depth} for query: {query[:100]}...")
                    
                    # Update progress
                    await self.progress_tracker.update_progress(current_query=query)
                    if on_progress:
                        progress_data = await self.progress_tracker.get_progress_copy()
                        progress = ResearchProgress(progress_data['total_depth'], progress_data['total_breadth'])
                        progress.current_depth = progress_data['current_depth']
                        progress.current_breadth = progress_data['current_breadth']
                        progress.current_query = progress_data['current_query']
                        progress.total_queries = progress_data['total_queries']
                        progress.completed_queries = progress_data['completed_queries']
                        on_progress(progress)

                    # Initialize researcher and conduct research
                    researcher = GPTResearcher(
                        query=query,
                        report_type=ReportType.ResearchReport.value,
                        report_source=self.config.report_source,
                        vector_store=load_vector_db("vector_db") if self.config.report_source == ReportSource.LangChainVectorStore.value else None,
                        tone=self.tone,
                        websocket=self.websocket,
                        config_path=self.config_path,
                        headers=self.headers,
                        log_handler=self.logger,
                        enable_enhanced_logging=self.enable_enhanced_logging,
                        parent_node_id=current_node_id,
                        verbose=self.verbose
                    )

                    # Conduct research (no individual timeout - only global timeout applies)
                    if self.enable_early_termination:
                        # Conduct research with monitoring (monitoring runs in parallel)
                        research_task = asyncio.create_task(researcher.conduct_research())
                        self.task_manager.tasks[current_node_id] = research_task 
                        # Start monitoring task that will run throughout entire node lifecycle
                        monitor_task = asyncio.create_task(
                            self._monitor_research_progress(researcher, query, current_node_id, start_time)
                        )
                        # Wait for research to complete (no timeout)
                        await research_task
                    else:
                        # Conduct research without monitoring
                        await researcher.conduct_research()
                    
                    # Calculate execution time
                    execution_time = time.time() - start_time
                    
                    # Process results
                    context = researcher.context
                    visited = set(researcher.visited_urls)
                    sources = researcher.research_sources
                    
                    # Process SERP results
                    results = await self.process_serp_result(query=query, context=context)
                    
                    # Update progress
                    await self.progress_tracker.update_progress(completed=1)

                    # Prepare result
                    result = {
                        'node_id': current_node_id,
                        'learnings': results['learnings'],
                        'visited_urls': visited,
                        'followUpQuestions': results['followUpQuestions'],
                        'citations': results['citations'],
                        'context': context if context else "",
                        'sources': sources if sources else []
                    }

                    # Immediately log completion with learnings/citations to ensure persistence
                    self.logger.update_node(
                        node_id=current_node_id,
                        status=TaskState.COMPLETED.value,
                        results={
                            'learnings': results['learnings'],
                            'citations': results['citations'],
                        },
                        visited_urls=visited,
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )
                    
                    # Add direct results to task manager with node tracking
                    await self.task_manager.add_direct_learnings(current_node_id, results['learnings'])
                    await self.task_manager.add_direct_citations(current_node_id, results['citations'])
                    await self.task_manager.add_direct_visited_urls(current_node_id, visited)
                    if context:
                        await self.task_manager.add_direct_context(current_node_id, context)
                    if sources:
                        await self.task_manager.add_direct_sources(current_node_id, sources)
                    
                    # Also aggregate into class-level accumulators for outer run() salvage
                    try:
                        async with self._partial_lock:
                            if results.get('learnings'):
                                self.learnings.extend(results['learnings'])
                            if visited:
                                self.visited_urls.update(visited)
                            if results.get('citations'):
                                self.citations.update(results['citations'])
                            if context:
                                self.context.append(context)
                            if sources:
                                self.research_sources.extend(sources)
                    except Exception:
                        pass
                    
                    # Mark task as completed with proper task management
                    await self.task_manager.complete_task(task_id, result)

                    # Update runtime monitoring data
                    await self.task_manager.update_runtime_data(
                        current_node_id, 
                        execution_time=execution_time
                    )

                    # If not at max depth, generate recursive queries
                    # Check if node has been terminated before proceeding with recursive research
                    current_status = self.logger.get_node_status(current_node_id)
                    if depth < self.config.max_depth and current_status not in [TaskState.TERMINATED.value, TaskState.CANCELLED.value]:
                        # Create next query from results
                        next_query = f"""
                        Previous research goal: {query}
                        Follow-up questions: {' '.join(results['followUpQuestions'])}
                        """
                        
                        # Generate sub-queries (NOTE: Controlled by BREADTH)
                        new_breadth = max(2, breadth // 2)  # Halve breadth at each level
                        new_depth = depth + 1

                        recursive_planning_node_id = self.logger.add_node(
                            depth=new_depth,
                            breadth=new_breadth,
                            query=next_query,
                            parent_id=current_node_id,
                            status=TaskState.STARTED.value,
                            operation="plan",
                            start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        )

                        # Register planning node for result tracking
                        await self.task_manager.register_node(recursive_planning_node_id, current_node_id)
                        
                        # Generate sub-queries (NOTE: Controlled by BREADTH)
                        sub_queries = await self.generate_serp_queries(next_query, new_breadth)

                        logger.debug(f"[FlashResearch] Generated {len(sub_queries)} recursive queries for depth {new_depth}")
                        
                        # Defer launching recursive tasks until AFTER semaphore release
                        pending_children = {
                            "sub_queries": sub_queries,
                            "new_breadth": new_breadth,
                            "new_depth": new_depth,
                            "recursive_planning_node_id": recursive_planning_node_id,
                        }
                        
                except asyncio.CancelledError:
                    logger.info(f"[FlashResearch] Task {task_id} was cancelled")
                    # Best-effort salvage of intermediate data
                    try:
                        salvage = await self._salvage_researcher_data(
                            researcher,
                            query_node_id=current_node_id,
                            mark_status=TaskState.CANCELLED.value
                        )
                        # Feed salvaged data into task manager with node annotations
                        if salvage.get("visited"):
                            await self.task_manager.add_direct_visited_urls(current_node_id, set(salvage["visited"]))
                        for ctx in salvage.get("context", []) or []:
                            await self.task_manager.add_direct_context(current_node_id, ctx)
                        if salvage.get("sources"):
                            await self.task_manager.add_direct_sources(current_node_id, salvage["sources"]) 
                        # Flush any accumulated results to the node before exiting
                        try:
                            node_results = await self.task_manager.get_node_results(current_node_id)
                            if node_results:
                                self.logger.update_node(
                                    node_id=current_node_id,
                                    status=TaskState.CANCELLED.value, 
                                    results={
                                        'learnings': node_results.get('learnings', []),
                                        'citations': node_results.get('citations', {})
                                    },
                                    visited_urls=node_results.get('visited_urls', []),
                                    end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                )
                        except Exception:
                            pass
                    except Exception as salvage_err:
                        logger.error(f"[FlashResearch] Salvage on cancellation failed: {salvage_err}")
                    query_task.state = TaskState.CANCELLED
                    await self.task_manager.complete_task(task_id, error=asyncio.CancelledError("Task cancelled"))
                    self.logger.update_node(
                        node_id=current_node_id,
                        status=TaskState.CANCELLED.value, 
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )
                    # Cancel child tasks
                    await self.task_manager.cancel(current_node_id)
                    raise
                except Exception as e:
                    logger.error(f"[FlashResearch] Error in recursive research task {task_id}: {str(e)}")
                    logger.error(f"[FlashResearch] Exception traceback: {traceback.format_exc()}")
                    # Best-effort salvage of intermediate data
                    try:
                        salvage = await self._salvage_researcher_data(
                            researcher,
                            query_node_id=current_node_id,
                            mark_status=TaskState.FAILED.value
                        )
                        if salvage.get("visited"):
                            await self.task_manager.add_direct_visited_urls(current_node_id, set(salvage["visited"]))
                        for ctx in salvage.get("context", []) or []:
                            await self.task_manager.add_direct_context(current_node_id, ctx)
                        if salvage.get("sources"):
                            await self.task_manager.add_direct_sources(current_node_id, salvage["sources"]) 
                        # Flush any accumulated results to the node before exiting
                        try:
                            node_results = await self.task_manager.get_node_results(current_node_id)
                            if node_results:
                                self.logger.update_node(
                                    node_id=current_node_id,
                                    status=TaskState.FAILED.value, 
                                    results={
                                        'learnings': node_results.get('learnings', []),
                                        'citations': node_results.get('citations', {})
                                    },
                                    visited_urls=node_results.get('visited_urls', []),
                                    end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                )
                        except Exception:
                            pass
                    except Exception as salvage_err:
                        logger.error(f"[FlashResearch] Salvage on cancellation failed: {salvage_err}")
                    query_task.state = TaskState.FAILED
                    await self.task_manager.complete_task(task_id, error=e)
                    self.logger.update_node(
                        node_id=current_node_id,
                        status=TaskState.FAILED.value, 
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )
                    # Cancel child tasks
                    await self.task_manager.cancel(current_node_id)
                    raise e

            # AFTER releasing semaphore: launch and await any deferred recursive children
            if pending_children:
                try:
                    logger.debug(f"[FlashResearch] Released semaphore for task {task_id}, launching {len(pending_children['sub_queries'])} recursive sub-tasks at depth {pending_children['new_depth']}")
                    recursive_tasks = []
                    for sub_query in pending_children["sub_queries"]:
                        recursive_task = asyncio.create_task(
                            self.deep_research(
                                query=sub_query['query'],
                                breadth=pending_children["new_breadth"],
                                depth=pending_children["new_depth"],
                                on_progress=on_progress,
                                parent_node_id=pending_children["recursive_planning_node_id"],
                                is_recursive=True
                            )
                        )
                        recursive_tasks.append(recursive_task)
                    await asyncio.gather(*recursive_tasks, return_exceptions=True)
                    # Update planning node
                    self.logger.update_node(
                        node_id=pending_children["recursive_planning_node_id"],
                        status=TaskState.COMPLETED.value,
                        results={"generated_queries": len(pending_children["sub_queries"])},
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )
                    # Cancel monitoring task once all children complete
                    if self.enable_early_termination and monitor_task:
                        monitor_task.cancel()
                        try:
                            await monitor_task
                        except asyncio.CancelledError:
                            pass
                    logger.debug(f"[FlashResearch] Completed task {task_id} with recursive sub-tasks")
                finally:
                    pending_children = None

        else:  # Root call - generate initial queries with proper task management
            # Store current asyncio task for potential cancellation (root node)
            current_task = asyncio.current_task()
            if current_task:
                self.task_manager.tasks[current_node_id] = current_task
                
            # Generate initial queries (NOTE: Controlled by BREADTH)
            serp_queries = await self.generate_serp_queries(query, breadth)
            logger.debug(f"[FlashResearch] Generated {len(serp_queries)} initial queries")
            
            # Create and launch initial async tasks with proper task management
            tasks = []
            for serp_query in serp_queries:
                task_id = await self.task_manager.create_task_id()
                query_task = AsyncQueryTask(serp_query, depth, breadth, current_node_id, task_id)
                await self.task_manager.register_task(query_task)
                
                # Create asyncio task and store reference
                asyncio_task = asyncio.create_task(
                    self.deep_research(
                        query=serp_query['query'],
                        breadth=breadth,
                        depth=depth,
                        on_progress=on_progress,
                        parent_node_id=current_node_id,
                        is_recursive=True
                    )
                )
                query_task.asyncio_task = asyncio_task
                tasks.append(asyncio_task)
                
                logger.debug(f"[FlashResearch] Launched initial task {task_id} at depth {depth}")
            
            # Wait for all initial tasks to complete with timeout (consistent with recursive implementation)
            logger.debug(f"[FlashResearch] All initial tasks launched, waiting for completion...")
            try:
                # Use configured global timeout or default to 3600 seconds (60 minutes)
                root_timeout = getattr(self.config, "time_limit_seconds", 3600)
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=root_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"[FlashResearch] Root level tasks timed out after {root_timeout}s")
                # Cancel all pending tasks
                for task in tasks:
                    if not task.done():
                        task.cancel()
                # Wait briefly for cancellation to complete
                await asyncio.gather(*tasks, return_exceptions=True)
            
            # Get final results
            final_data = await self.task_manager.get_all_data()
            
            # Aggregate final_data into class-level accumulators as a backup
            try:
                async with self._partial_lock:
                    if final_data.get('learnings'):
                        self.learnings.extend(final_data['learnings'])
                    if final_data.get('visited_urls'):
                        self.visited_urls.update(set(final_data['visited_urls']))
                    if final_data.get('citations'):
                        self.citations.update(final_data['citations'])
                    if final_data.get('context'):
                        self.context.extend(final_data['context'])
                    if final_data.get('sources'):
                        self.research_sources.extend(final_data['sources'])
            except Exception:
                pass
            
            # Trim context to stay within word limits
            trimmed_context = trim_context_to_word_limit(final_data['context'], max_words=self.max_context_words)
            logger.info(f"Trimmed context from {len(final_data['context'])} items to {len(trimmed_context)} items")
            final_data['context'] = trimmed_context

        # Get node results (now merged with node annotations)
        node_results = await self.task_manager.get_node_results(current_node_id)
        
        # Log completion with merged results
        if node_results:
            # Results are already merged with node annotations
            combined_results = {
                'learnings': node_results['learnings'],
                'citations': node_results['citations'],
                'runtime_data': node_results['runtime_data']
            }
            
            self.logger.update_node(
                node_id=current_node_id,
                status=TaskState.COMPLETED.value if self.logger.get_node_status(current_node_id) == TaskState.STARTED.value else self.logger.get_node_status(current_node_id),
                results=combined_results,
                visited_urls=node_results['visited_urls'] if not is_recursive else None,
                end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
        if not is_recursive:
            logger.debug(f"[FlashResearch] Root research completed")
            return final_data
        return None  # Recursive calls don't need to return data as it's stored in task_manager

    async def _monitor_research_progress(self, researcher: GPTResearcher, query: str, 
                                       node_id: int, start_time: float):
        """Monitor research progress and terminate early if goal is satisfied"""
        try:
            logger.debug(f"[FlashResearch] Starting research monitoring for node {node_id}")
            
            # Track last evaluated content size to avoid redundant LLM calls
            last_eval_ctx_len = 0
            last_eval_learnings_count = 0
            
            while True:
                await asyncio.sleep(8)  # Check every 8 seconds
                
                # No individual timeout check - only global timeout applies
                # Track execution time for monitoring purposes
                execution_time = time.time() - start_time
                
                # Check if all child tasks are complete (for nodes with children)
                if await self.task_manager.are_all_child_tasks_complete(node_id):
                    # If no children or all children complete, we can consider termination
                    pass
                else:
                    # Still have running children, continue monitoring
                    continue
                
                # Get current research state
                try:
                    current_context = getattr(researcher, 'context', '') or ''
                    current_learnings = self._extract_learnings_from_context(current_context)
                    
                    if current_context or current_learnings:
                        # Only evaluate if there is meaningful change since last evaluation
                        ctx_growth = len(current_context) - last_eval_ctx_len
                        learnings_growth = len(current_learnings) - last_eval_learnings_count
                        
                        if ctx_growth < 200 and learnings_growth < 3:
                            # Not enough new information; skip LLM evaluation this tick
                            continue
                        
                        # Evaluate goal satisfaction
                        satisfaction_decision = await self.task_manager.evaluate_goal_satisfaction(
                            query, current_context, current_learnings, self.config
                        )
                        
                        # Update last evaluation markers after a successful eval
                        last_eval_ctx_len = len(current_context)
                        last_eval_learnings_count = len(current_learnings)

                        logger.debug(f"[FlashResearch] Monitoring Node {node_id} Goal Satisfied: {satisfaction_decision.is_goal_satisfied}")
                        logger.debug(f"[FlashResearch] Monitoring Node {node_id} Satisfaction Score: {satisfaction_decision.satisfaction_score}")
                        logger.debug(f"[FlashResearch] Monitoring Node {node_id} Quality Score: {satisfaction_decision.quality_score}")
                        logger.debug(f"[FlashResearch] Monitoring Node {node_id} Reasoning: {satisfaction_decision.reasoning}")

                        # Update runtime data
                        await self.task_manager.update_runtime_data(
                            node_id,
                            satisfaction_score=satisfaction_decision.satisfaction_score,
                            quality_score=satisfaction_decision.quality_score
                        )
                        
                        # Check if should terminate early
                        should_terminate = (
                            satisfaction_decision.satisfaction_score >= self.satisfaction_threshold and
                            satisfaction_decision.quality_score >= self.quality_threshold
                        )
                        
                        if should_terminate:
                            logger.debug(f"[FlashResearch] Node {node_id} goal satisfied, terminating early")
                            await self.task_manager.update_runtime_data(
                                node_id,
                                goal_satisfied=True,
                                termination_reason="goal_satisfied",
                                execution_time=execution_time
                            )
                            await self.task_manager.cancel(node_id)
                            break
                            
                except Exception as e:
                    logger.error(f"[FlashResearch] Error during monitoring evaluation: {e}")
                    
        except asyncio.CancelledError:
            logger.debug(f"[FlashResearch] Research monitoring cancelled for node {node_id}")
            raise
        except Exception as e:
            logger.error(f"[FlashResearch] Error in research monitoring: {e}")

    def _extract_learnings_from_context(self, context: str) -> List[str]:
        """Extract learnings from research context"""
        try:
            if not context:
                return []
                
            # Split context into sentences and filter meaningful ones
            sentences = context.replace('\n', ' ').split('. ')
            learnings = [
                sentence.strip() + '.' for sentence in sentences 
                if len(sentence.strip()) > 30 and not sentence.strip().startswith('http')
            ]
            
            return learnings[:15]  # Limit to avoid too much data
            
        except Exception as e:
            logger.warning(f"Error extracting learnings from context: {e}")
            return []
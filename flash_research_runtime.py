from typing import List, Dict, Any, Optional, Set
from fastapi import WebSocket
import asyncio
import logging
from datetime import datetime, timedelta
import traceback
import time
from pydantic import BaseModel
from enum import Enum

from modified_parallel_deep_research import ParallelizedDeepResearch, AsyncTaskManager, AsyncQueryTask, TaskState, AsyncProgress
from modified_agent import GPTResearcher
from gpt_researcher.llm_provider.generic.base import ReasoningEfforts
from gpt_researcher.utils.llm import create_chat_completion
from gpt_researcher.utils.enum import ReportType, ReportSource, Tone

from build_vector_db import load_vector_db
from utils import Config, ResearchLogger, ResearchProgress, trim_context_to_word_limit

logger = logging.getLogger(__name__)


# Pydantic models for runtime goal satisfaction
class GoalSatisfactionDecision(BaseModel):
    """Structured decision for research goal satisfaction"""
    is_goal_satisfied: bool
    satisfaction_score: float  # 0.0 to 1.0
    reasoning: str
    missing_aspects: List[str]  # What aspects still need research
    quality_score: float  # Overall quality of current research


class RuntimeTaskResult(BaseModel):
    """Enhanced result with runtime monitoring data"""
    task_id: str
    success: bool
    goal_satisfied: bool
    satisfaction_score: float
    quality_score: float
    total_learnings: int
    execution_time: float
    termination_reason: str
    research_context_summary: str


class RuntimeAsyncQueryTask(AsyncQueryTask):
    """Extended AsyncQueryTask with runtime goal satisfaction monitoring"""
    
    def __init__(self, serp_query: Dict[str, str], depth: int, breadth: int, 
                 parent_node_id: Optional[int], task_id: str,
                 research_goal: str = None,
                 satisfaction_threshold: float = 0.8,
                 quality_threshold: float = 0.7,
                 max_execution_time: float = 300.0):  # 5 minutes max per task
        super().__init__(serp_query, depth, breadth, parent_node_id, task_id)
        self.research_goal = research_goal or serp_query.get('researchGoal', '')
        self.satisfaction_threshold = satisfaction_threshold
        self.quality_threshold = quality_threshold
        self.max_execution_time = max_execution_time
        
        # Runtime monitoring state
        self.goal_satisfied = False
        self.satisfaction_score = 0.0
        self.quality_score = 0.0
        self.satisfaction_checks = []
        self.should_terminate_early = asyncio.Event()
        self.runtime_context = []
        self.execution_start_time = None
        # Termination metadata
        self.termination_reason: Optional[str] = None
        self.termination_detail: Optional[str] = None
        
    def get_execution_time(self) -> float:
        """Get current execution time"""
        if self.execution_start_time is None:
            return 0.0
        if self.end_time:
            return (self.end_time.timestamp() - self.execution_start_time)
        return time.time() - self.execution_start_time
    
    def should_terminate(self) -> bool:
        """Check if task should terminate early"""
        return (self.goal_satisfied and self.satisfaction_score >= self.satisfaction_threshold) or \
               self.get_execution_time() >= self.max_execution_time


class RuntimeAsyncTaskManager(AsyncTaskManager):
    """Enhanced AsyncTaskManager with runtime goal satisfaction monitoring"""
    
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.runtime_lock = asyncio.Lock()
        self.runtime_results: Dict[str, RuntimeTaskResult] = {}
        self.global_research_context = {}
        self.goal_satisfaction_history = []
        
        # Circuit breaker for LLM calls to prevent blocking
        self.llm_call_semaphore = asyncio.Semaphore(2)  # Limit concurrent LLM calls
        self.failed_llm_calls = 0
        self.max_failed_calls = 3
        self.llm_circuit_open = False
        self.circuit_reset_time = None
        
    async def monitor_runtime_changes(self, action: str, task_id: str, details: str = ""):
        """Monitor runtime changes with detailed logging (non-blocking)"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        active_count = len(self.active_tasks)
        completed_count = len(self.completed_tasks)
        
        try:
            # Try to acquire lock with timeout to prevent blocking
            await asyncio.wait_for(self.runtime_lock.acquire(), timeout=0.1)
            try:
                logger.info(f"[{timestamp}] RUNTIME_MONITOR: {action}")
                logger.info(f"  Task ID: {task_id}")
                logger.info(f"  Active Tasks: {active_count}")
                logger.info(f"  Completed Tasks: {completed_count}")
                if details:
                    logger.info(f"  Details: {details}")
            finally:
                self.runtime_lock.release()
        except asyncio.TimeoutError:
            # If we can't get the lock quickly, just log without lock (non-blocking)
            logger.info(f"[{timestamp}] RUNTIME_MONITOR: {action} (task_id: {task_id}, details: {details})")
    
    async def _check_circuit_breaker(self) -> bool:
        """Check if LLM circuit breaker is open (preventing calls to avoid blocking)"""
        if not self.llm_circuit_open:
            return False
            
        # Check if circuit should be reset (after 60 seconds)
        if self.circuit_reset_time and time.time() > self.circuit_reset_time:
            self.llm_circuit_open = False
            self.failed_llm_calls = 0
            self.circuit_reset_time = None
            logger.info("[RuntimeTaskManager] LLM circuit breaker reset - resuming goal evaluations")
            return False
            
        return True
    
    async def _trip_circuit_breaker(self):
        """Trip the circuit breaker to prevent blocking LLM calls"""
        self.llm_circuit_open = True
        self.circuit_reset_time = time.time() + 60  # Reset after 60 seconds
        logger.warning("[RuntimeTaskManager] LLM circuit breaker tripped - pausing goal evaluations for 60s")
    
    async def evaluate_goal_satisfaction(self, task: RuntimeAsyncQueryTask, 
                                       current_context: str, 
                                       current_learnings: List[str]) -> GoalSatisfactionDecision:
        """Evaluate if the research goal is satisfied based on current context and learnings (with circuit breaker)"""
        
        # Check circuit breaker to avoid blocking calls
        if await self._check_circuit_breaker():
            # Return default response when circuit is open
            return GoalSatisfactionDecision(
                is_goal_satisfied=False,
                satisfaction_score=0.5,
                reasoning="Circuit breaker active - skipping LLM evaluation to prevent blocking",
                missing_aspects=["LLM evaluation unavailable"],
                quality_score=0.5
            )
        
        # Use semaphore to limit concurrent LLM calls
        async with self.llm_call_semaphore:
            try:
                # Add timeout to prevent indefinite blocking
                return await asyncio.wait_for(
                    self._perform_goal_evaluation(task, current_context, current_learnings),
                    timeout=30.0  # 30 second timeout
                )
                
            except asyncio.TimeoutError:
                self.failed_llm_calls += 1
                if self.failed_llm_calls >= self.max_failed_calls:
                    await self._trip_circuit_breaker()
                
                logger.warning(f"[RuntimeTaskManager] Goal evaluation timeout for task {task.task_id}")
                return GoalSatisfactionDecision(
                    is_goal_satisfied=False,
                    satisfaction_score=0.5,
                    reasoning="Evaluation timeout - continuing research",
                    missing_aspects=["Evaluation incomplete"],
                    quality_score=0.5
                )
                
            except Exception as e:
                self.failed_llm_calls += 1
                if self.failed_llm_calls >= self.max_failed_calls:
                    await self._trip_circuit_breaker()
                
                logger.error(f"[RuntimeTaskManager] Goal evaluation error for task {task.task_id}: {e}")
                return GoalSatisfactionDecision(
                    is_goal_satisfied=False,
                    satisfaction_score=0.5,
                    reasoning=f"Evaluation error: {str(e)[:100]}",
                    missing_aspects=["Evaluation failed"],
                    quality_score=0.5
                )
    
    async def _perform_goal_evaluation(self, task: RuntimeAsyncQueryTask, 
                                     current_context: str, 
                                     current_learnings: List[str]) -> GoalSatisfactionDecision:
        """Perform the actual LLM-based goal evaluation"""
        
        # Debug log what we received
        await self.monitor_runtime_changes(
            "EVALUATION_INPUT_DEBUG", task.task_id,
            f"Evaluating with: context_len={len(current_context)}, "
            f"learnings_count={len(current_learnings)}, "
            f"context_preview='{current_context[:100] if current_context else 'EMPTY'}...'"
        )
        
        # Prepare context summary
        context_summary = f"""
        Research Goal: {task.research_goal}
        
        Current Learnings ({len(current_learnings)}):
        {chr(10).join([f"- {learning[:150]}..." if len(learning) > 150 else f"- {learning}" for learning in current_learnings[:5]])}
        {"... (and more)" if len(current_learnings) > 5 else ""}
        
        Context Preview:
        {current_context[:1000] if current_context else "No context available"}
        {"..." if len(current_context) > 1000 else ""}
        
        Execution Time: {task.get_execution_time():.2f}s
        """
        
        messages = [
            {"role": "system", "content": """You are an expert research quality evaluator. Your task is to determine if a research goal has been sufficiently satisfied based on current findings.

EVALUATION CRITERIA:
1. GOAL COVERAGE: Does the research adequately address the stated goal?
2. INFORMATION QUALITY: Are the findings comprehensive and reliable?
3. DEPTH SUFFICIENCY: Is there enough detail to answer the research question?
4. SOURCE DIVERSITY: Are findings from multiple credible sources?
5. COMPLETENESS: Are major aspects of the topic covered?

SATISFACTION THRESHOLDS:
- HIGH SATISFACTION (0.8-1.0): Goal fully satisfied, comprehensive coverage
- MEDIUM SATISFACTION (0.6-0.8): Goal mostly satisfied, minor gaps acceptable  
- LOW SATISFACTION (0.4-0.6): Goal partially satisfied, significant gaps remain
- INSUFFICIENT (0.0-0.4): Goal not satisfied, major research needed

QUALITY SCORING:
- EXCELLENT (0.8-1.0): Comprehensive, well-sourced, detailed
- GOOD (0.6-0.8): Adequate coverage, some depth
- FAIR (0.4-0.6): Basic coverage, limited depth
- POOR (0.0-0.4): Insufficient information

Be conservative - only mark as satisfied if the research truly addresses the goal comprehensively."""},
            {"role": "user", "content": f"""Evaluate the following research progress:

{context_summary}

Based on the research goal and current findings, determine:
1. Is the research goal satisfied?
2. Confidence score (0.0-1.0) in the satisfaction assessment
3. Quality score (0.0-1.0) of current research
4. What aspects are still missing (if any)?
5. Reasoning for your decision

Consider efficiency - if the goal is mostly satisfied, recommend termination to save costs."""}
        ]
        
        response = await create_chat_completion(
            messages=messages,
            llm_provider=self.config.llm_provider,
            model=self.config.reasoning_model,
            temperature=0.1,
            max_tokens=400,
            reasoning_effort=ReasoningEfforts.High.value,
            seed=42,
            response_format=GoalSatisfactionDecision
        )
        
        if isinstance(response, str):
            response = GoalSatisfactionDecision.model_validate_json(response)
        
        # Store satisfaction check
        task.satisfaction_checks.append({
            'timestamp': datetime.now().isoformat(),
            'decision': response.dict(),
            'context_length': len(current_context),
            'learnings_count': len(current_learnings)
        })
        
        # Reset failed calls counter on success
        self.failed_llm_calls = max(0, self.failed_llm_calls - 1)
        
        return response
    
    async def monitor_task_progress(self, task: RuntimeAsyncQueryTask, 
                                  context: str, learnings: List[str]) -> bool:
        """Monitor task progress and determine if early termination is warranted (non-blocking)"""
        
        # Don't check too frequently (minimum 30 seconds between checks)
        if (task.satisfaction_checks and 
            time.time() - datetime.fromisoformat(task.satisfaction_checks[-1]['timestamp']).timestamp() < 30):
            return False
        
        try:
            # Schedule goal satisfaction evaluation as a background task (non-blocking)
            eval_task = asyncio.create_task(
                self._evaluate_goal_satisfaction_non_blocking(task, context, learnings)
            )
            
            # Don't wait for the evaluation - let it run in background
            # Just check if we already have a termination signal
            if task.should_terminate_early.is_set():
                return True
                
            # Check for time-based termination (immediate, no LLM call)
            if task.get_execution_time() >= task.max_execution_time:
                # Record termination metadata
                task.termination_reason = task.termination_reason or "timeout"
                task.termination_detail = task.termination_detail or (
                    f"Task exceeded max_execution_time={task.max_execution_time}s"
                )
                task.should_terminate_early.set()
                
                await self.monitor_runtime_changes(
                    "TERMINATION_DECISION", task.task_id,
                    f"DECISION: TERMINATE - Timeout reached. "
                    f"Execution time: {task.get_execution_time():.1f}s >= {task.max_execution_time}s. "
                    f"Reason: {task.termination_detail}"
                )
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Error in progress monitoring for task {task.task_id}: {e}")
            return False
    
    async def _evaluate_goal_satisfaction_non_blocking(self, task: RuntimeAsyncQueryTask, 
                                                     context: str, learnings: List[str]):
        """Evaluate goal satisfaction in background without blocking research"""
        try:
            # Evaluate goal satisfaction asynchronously
            satisfaction_decision = await self.evaluate_goal_satisfaction(task, context, learnings)
            
            # Update task state
            task.satisfaction_score = satisfaction_decision.satisfaction_score
            task.quality_score = satisfaction_decision.quality_score
            
            await self.monitor_runtime_changes(
                "GOAL_EVALUATION", task.task_id,
                f"Satisfied: {satisfaction_decision.is_goal_satisfied}, "
                f"Satisfaction: {satisfaction_decision.satisfaction_score:.2f}, "
                f"Quality: {satisfaction_decision.quality_score:.2f}"
            )
            
            # Log the termination decision (whether to terminate or continue)
            should_terminate = (satisfaction_decision.is_goal_satisfied and 
                              satisfaction_decision.satisfaction_score >= task.satisfaction_threshold and
                              satisfaction_decision.quality_score >= task.quality_threshold)
            
            if should_terminate:
                task.goal_satisfied = True
                task.should_terminate_early.set()
                # Record termination metadata
                task.termination_reason = "goal_satisfied"
                task.termination_detail = satisfaction_decision.reasoning
                
                await self.monitor_runtime_changes(
                    "TERMINATION_DECISION", task.task_id,
                    f"DECISION: TERMINATE - Goal satisfied with high confidence. "
                    f"Satisfied: {satisfaction_decision.is_goal_satisfied}, "
                    f"Confidence: {satisfaction_decision.satisfaction_score:.2f} >= {task.satisfaction_threshold}, "
                    f"Quality: {satisfaction_decision.quality_score:.2f} >= {task.quality_threshold}. "
                    f"Reasoning: {satisfaction_decision.reasoning[:150]}..."
                )
            else:
                # Log why we decided NOT to terminate
                reasons = []
                if not satisfaction_decision.is_goal_satisfied:
                    reasons.append("goal not satisfied")
                if satisfaction_decision.satisfaction_score < task.satisfaction_threshold:
                    reasons.append(f"confidence {satisfaction_decision.satisfaction_score:.2f} < {task.satisfaction_threshold}")
                if satisfaction_decision.quality_score < task.quality_threshold:
                    reasons.append(f"quality {satisfaction_decision.quality_score:.2f} < {task.quality_threshold}")
                
                await self.monitor_runtime_changes(
                    "TERMINATION_DECISION", task.task_id,
                    f"DECISION: CONTINUE - Criteria not met: {', '.join(reasons)}. "
                    f"Missing aspects: {satisfaction_decision.missing_aspects[:3]}. "
                    f"Reasoning: {satisfaction_decision.reasoning[:150]}..."
                )
                
        except Exception as e:
            logger.error(f"Error in background goal evaluation for task {task.task_id}: {e}")
            await self.monitor_runtime_changes(
                "TERMINATION_DECISION", task.task_id,
                f"DECISION: CONTINUE - Evaluation failed: {str(e)[:100]}"
            )
    
    async def register_runtime_task(self, task: RuntimeAsyncQueryTask):
        """Register a runtime task with enhanced monitoring"""
        await self.register_task(task)
        await self.monitor_runtime_changes(
            "RUNTIME_TASK_REGISTERED", task.task_id,
            f"Goal: {task.research_goal[:100]}..., "
            f"Thresholds: satisfaction={task.satisfaction_threshold}, quality={task.quality_threshold}"
        )
    
    async def complete_runtime_task(self, task: RuntimeAsyncQueryTask, result: Dict[str, Any] = None, error: Exception = None):
        """Complete a runtime task with enhanced result tracking"""
        
        # Create runtime result
        runtime_result = RuntimeTaskResult(
            task_id=task.task_id,
            success=error is None,
            goal_satisfied=task.goal_satisfied,
            satisfaction_score=task.satisfaction_score,
            quality_score=task.quality_score,
            total_learnings=len(result.get('learnings', [])) if result else 0,
            execution_time=task.get_execution_time(),
            termination_reason="goal_satisfied" if task.goal_satisfied else "completed",
            research_context_summary=result.get('context', '')[:200] if result else ""
        )
        
        self.runtime_results[task.task_id] = runtime_result
        
        # Complete in parent class
        await self.complete_task(task.task_id, result, error)
        
        await self.monitor_runtime_changes(
            "RUNTIME_TASK_COMPLETED", task.task_id,
            f"Goal satisfied: {task.goal_satisfied}, "
            f"Confidence: {task.satisfaction_score:.2f}, "
            f"Time: {task.get_execution_time():.2f}s"
        )
    
    def get_runtime_statistics(self) -> Dict[str, Any]:
        """Get comprehensive runtime statistics"""
        if not self.runtime_results:
            return {}
            
        results = list(self.runtime_results.values())
        successful = [r for r in results if r.success]
        goal_satisfied = [r for r in results if r.goal_satisfied]
        
        return {
            'total_tasks': len(results),
            'successful_tasks': len(successful),
            'goal_satisfied_tasks': len(goal_satisfied),
            'early_termination_rate': len(goal_satisfied) / len(results) if results else 0,
            'average_execution_time': sum(r.execution_time for r in results) / len(results) if results else 0,
            'average_satisfaction_score': sum(r.satisfaction_score for r in successful) / len(successful) if successful else 0,
            'average_quality_score': sum(r.quality_score for r in successful) / len(successful) if successful else 0,
            'cost_savings_estimate': sum(300 - r.execution_time for r in goal_satisfied if r.execution_time < 300)
        }


class FlashResearchRuntime(ParallelizedDeepResearch):
    """Enhanced ParallelizedDeepResearch with runtime conditional task management and goal satisfaction monitoring"""
    
    def __init__(
        self,
        query: str,
        config_path: str,
        depth: int = 1,
        headers: Optional[Dict] = None,
        websocket: Optional[WebSocket] = None,
        tone: Tone = Tone.Objective,
        logs_dir: str = "research_progress.json",
        progress_callback: Optional[callable] = None,
        # Runtime-specific parameters
        satisfaction_threshold: float = 0.5,
        quality_threshold: float = 0.5,
        max_task_execution_time: float = 300.0,  # 5 minutes per task
        enable_early_termination: bool = True
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
        self.satisfaction_threshold = satisfaction_threshold
        self.quality_threshold = quality_threshold
        self.max_task_execution_time = max_task_execution_time
        self.enable_early_termination = enable_early_termination
        self.runtime_start_time = datetime.now()
    
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
        """Enhanced deep research with runtime monitoring and early termination"""
        logger.debug(f"[FlashResearchRuntime] Starting runtime research with query: {query[:100]}...")
        
        # Initialize runtime task manager
        runtime_task_manager = RuntimeAsyncTaskManager(self.config)
        progress_tracker = AsyncProgress(depth, breadth)
        
        # Add initial data
        if learnings:
            for learning in learnings:
                await runtime_task_manager.add_learning(learning)
        if citations:
            for learning, citation in citations.items():
                await runtime_task_manager.add_citation(learning, citation)
        if visited_urls:
            await runtime_task_manager.add_visited_urls(visited_urls)
        
        # Log research start
        current_node_id = self.logger.add_node(
            depth=depth,
            breadth=breadth,
            query=query,
            parent_id=parent_node_id,
            status="started",
            operation="plan",
            start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        
        # Generate queries using the simple approach from ParallelizedDeepResearch
        serp_queries = await self.generate_serp_queries(query, num_queries=breadth)
        logger.debug(f"[FlashResearchRuntime] Generated {len(serp_queries)} queries")
        
        # Create and launch runtime tasks
        tasks = []
        for serp_query in serp_queries:
            task_id = await runtime_task_manager.create_task_id()
            runtime_task = RuntimeAsyncQueryTask(
                serp_query=serp_query,
                depth=depth,
                breadth=breadth,
                parent_node_id=current_node_id,
                task_id=task_id,
                research_goal=serp_query.get('researchGoal', query),
                satisfaction_threshold=self.satisfaction_threshold,
                quality_threshold=self.quality_threshold,
                max_execution_time=self.max_task_execution_time
            )
            
            await runtime_task_manager.register_runtime_task(runtime_task)
            
            # Create asyncio task
            asyncio_task = asyncio.create_task(
                self._async_runtime_research(
                    runtime_task, runtime_task_manager, progress_tracker, on_progress
                )
            )
            runtime_task.asyncio_task = asyncio_task
            tasks.append(asyncio_task)
        
        logger.debug(f"[FlashResearchRuntime] All runtime tasks launched, waiting for completion...")
        
        # Wait for completion with runtime monitoring
        await self._wait_for_runtime_tasks_completion(runtime_task_manager)
        
        # Get final results
        final_data = await runtime_task_manager.get_all_data()
        
        # Trim context
        trimmed_context = trim_context_to_word_limit(final_data['context'])
        final_data['context'] = trimmed_context
        
        # Add runtime statistics to results
        final_data['runtime_statistics'] = runtime_task_manager.get_runtime_statistics()
        
        # Log completion
        self.logger.update_node(
            node_id=current_node_id,
            status="completed",
            results={
                'learnings': final_data['learnings'],
                'citations': final_data['citations'],
                'runtime_stats': final_data['runtime_statistics']
            },
            visited_urls=final_data['visited_urls'],
            end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        
        logger.info(f"[FlashResearchRuntime] Runtime research completed with statistics: {final_data['runtime_statistics']}")
        return final_data
    
    async def _async_runtime_research(self, task: RuntimeAsyncQueryTask, 
                                    task_manager: RuntimeAsyncTaskManager,
                                    progress_tracker: AsyncProgress, on_progress=None) -> None:
        """Process a runtime task with goal satisfaction monitoring"""
        async with self.semaphore:
            try:
                task.state = TaskState.RUNNING
                task.start_time = datetime.now()
                task.execution_start_time = time.time()
                
                logger.debug(f"[FlashResearchRuntime] Processing runtime task {task.task_id} with goal: {task.research_goal[:50]}...")
                
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
                
                # Log task start
                query_node_id = self.logger.add_node(
                    depth=task.depth,
                    breadth=task.breadth,
                    query=task.serp_query['query'],
                    parent_id=task.parent_node_id,
                    research_goal=task.serp_query.get('researchGoal', ''),
                    status="started",
                    operation="research",
                    start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                
                # Initialize researcher
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
                
                # Start monitoring as background task (non-blocking)
                monitor_task = asyncio.create_task(self._monitor_research_progress(task, researcher, task_manager))
                
                # Conduct research with periodic termination checks
                research_task = asyncio.create_task(self._conduct_research_with_termination_checks(researcher, task))
                
                # Wait for research completion (monitoring runs in background)
                try:
                    await research_task
                finally:
                    # Clean up monitoring task
                    monitor_task.cancel()
                    try:
                        await monitor_task
                    except asyncio.CancelledError:
                        pass
                
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
                
                # Log completion with appropriate status and termination reasoning
                node_status = "cancelled" if task.should_terminate_early.is_set() else "completed"
                self.logger.update_node(
                    node_id=query_node_id,
                    status=node_status,
                    results={
                        'learnings': results['learnings'],
                        'citations': results['citations'],
                        'goal_satisfied': task.goal_satisfied,
                        'satisfaction_score': task.satisfaction_score,
                        # Include termination details if cancelled/terminated early
                        **({
                            'termination_reason': task.termination_reason or (
                                'early_termination' if task.goal_satisfied else 'timeout'
                            ),
                            'termination_detail': task.termination_detail
                        } if node_status == 'cancelled' else {})
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
                    'researchGoal': task.serp_query.get('researchGoal', ''),
                    'citations': results['citations'],
                    'context': context if context else "",
                    'sources': sources if sources else [],
                    'runtime_data': {
                        'goal_satisfied': task.goal_satisfied,
                        'satisfaction_score': task.satisfaction_score,
                        'quality_score': task.quality_score,
                        'execution_time': task.get_execution_time(),
                        'satisfaction_checks': task.satisfaction_checks
                    }
                }
                
                # Complete runtime task
                await task_manager.complete_runtime_task(task, result)
                
                # Generate recursive tasks using simple approach (depth-based, no adaptive planning)
                if task.depth < self.config.max_depth and not task.goal_satisfied:
                    logger.debug(f"[FlashResearchRuntime] Generating recursive tasks for depth {task.depth + 1}")
                    try:
                        await self._generate_runtime_recursive_tasks(
                            result, task.depth, task.breadth, task_manager,
                            progress_tracker, on_progress
                        )
                    except Exception as e:
                        logger.error(f"[FlashResearchRuntime] Error generating recursive tasks: {e}")
                
                logger.debug(f"[FlashResearchRuntime] Completed runtime task {task.task_id}")
                
            except asyncio.CancelledError:
                logger.info(f"[FlashResearchRuntime] Task {task.task_id} was cancelled")
                task.state = TaskState.CANCELLED
                
                # Update node status to cancelled with termination reason
                self.logger.update_node(
                    node_id=query_node_id,
                    status="cancelled",
                    results={
                        'termination_reason': task.termination_reason or 'task_cancelled',
                        'termination_detail': task.termination_detail
                    },
                    end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                
                await task_manager.complete_runtime_task(task, error=asyncio.CancelledError("Task cancelled"))
                raise
            except Exception as e:
                logger.error(f"[FlashResearchRuntime] Error in runtime task {task.task_id}: {str(e)}")
                logger.error(f"[FlashResearchRuntime] Exception traceback: {traceback.format_exc()}")
                task.state = TaskState.FAILED
                
                # Update node status to failed
                self.logger.update_node(
                    node_id=query_node_id,
                    status="failed",
                    results={'termination_reason': 'task_failed', 'error': str(e)},
                    end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                
                await task_manager.complete_runtime_task(task, error=e)
    
    async def _monitor_research_progress(self, task: RuntimeAsyncQueryTask, 
                                       researcher: GPTResearcher,
                                       task_manager: RuntimeAsyncTaskManager):
        """Monitor research progress and trigger early termination if goal is satisfied (fully non-blocking)"""
        if not self.enable_early_termination:
            return
            
        try:
            # Configurable monitoring intervals
            monitoring_interval = 10  # Check every 15 seconds for responsiveness  
            last_evaluation_time = 0
            evaluation_interval = 15  # Do expensive LLM evaluation every 30 seconds (reduced from 45s)
            
            await task_manager.monitor_runtime_changes(
                "MONITORING_CONFIG", task.task_id,
                f"Starting monitoring with intervals: check={monitoring_interval}s, evaluate={evaluation_interval}s, "
                f"termination_checks_every=5s, min_between_llm_calls=30s"
            )
            
            while not task.should_terminate_early.is_set() and task.state == TaskState.RUNNING:
                await asyncio.sleep(monitoring_interval)
                
                current_time = time.time()
                
                # Quick timeout check (no LLM call needed)
                if task.get_execution_time() >= task.max_execution_time:
                    task.termination_reason = task.termination_reason or "timeout"
                    task.termination_detail = task.termination_detail or (
                        f"Task exceeded max_execution_time={task.max_execution_time}s during monitoring"
                    )
                    task.should_terminate_early.set()
                    
                    await task_manager.monitor_runtime_changes(
                        "TERMINATION_DECISION", task.task_id,
                        f"DECISION: TERMINATE - Timeout reached during monitoring. "
                        f"Execution time: {task.get_execution_time():.1f}s >= {task.max_execution_time}s"
                    )
                    logger.info(f"[FlashResearchRuntime] Timeout termination for task {task.task_id}")
                    break
                
                # Only do expensive evaluation periodically
                if current_time - last_evaluation_time >= evaluation_interval:
                    last_evaluation_time = current_time
                    
                    # Get current research state properly
                    current_context = self._extract_current_context(researcher)
                    current_learnings = self._extract_current_learnings(researcher)
                    
                    # Log what we're actually passing to the evaluator
                    await task_manager.monitor_runtime_changes(
                        "CONTEXT_DEBUG", task.task_id,
                        f"Context length: {len(current_context)}, "
                        f"Learnings count: {len(current_learnings)}, "
                        f"Sources count: {len(getattr(researcher, 'research_sources', []))}, "
                        f"Visited URLs: {len(getattr(researcher, 'visited_urls', []))}"
                    )
                    
                    # Non-blocking progress check (background evaluation)
                    await task_manager.monitor_task_progress(task, current_context, current_learnings)
                    
                    # Log periodic "continuing research" decision
                    await task_manager.monitor_runtime_changes(
                        "TERMINATION_DECISION", task.task_id,
                        f"DECISION: CONTINUE - Periodic evaluation completed. "
                        f"Time: {task.get_execution_time():.1f}s/{task.max_execution_time}s, "
                        f"Goal satisfied: {task.goal_satisfied}, "
                        f"Confidence: {task.satisfaction_score:.2f}, Quality: {task.quality_score:.2f}"
                    )
                
                # Check termination signal (set by background evaluation)
                if task.should_terminate_early.is_set():
                    await task_manager.monitor_runtime_changes(
                        "TERMINATION_DECISION", task.task_id,
                        f"DECISION: TERMINATE - Termination signal detected during monitoring. "
                        f"Goal satisfied: {task.goal_satisfied}, "
                        f"Reason: {task.termination_reason or 'signal_detected'}"
                    )
                    logger.info(f"[FlashResearchRuntime] Goal satisfaction termination for task {task.task_id}")
                    break
                    
        except asyncio.CancelledError:
            logger.debug(f"[FlashResearchRuntime] Progress monitor cancelled for task {task.task_id}")
            raise
        except Exception as e:
            logger.error(f"[FlashResearchRuntime] Error in progress monitoring: {e}")
    
    def _extract_current_context(self, researcher: GPTResearcher) -> str:
        """Extract current research context from the researcher"""
        try:
            # Get the actual context from researcher
            context = getattr(researcher, 'context', None)
            
            if context is None:
                return ""
            
            # Handle different context formats
            if isinstance(context, str):
                return context
            elif isinstance(context, list):
                return '\n'.join(str(item) for item in context)
            elif hasattr(context, '__str__'):
                return str(context)
            else:
                return ""
                
        except Exception as e:
            logger.warning(f"Error extracting context: {e}")
            return ""
    
    def _extract_current_learnings(self, researcher: GPTResearcher) -> List[str]:
        """Extract current learnings/findings from the researcher"""
        try:
            learnings = []
            
            # Get context and extract meaningful content
            context = self._extract_current_context(researcher)
            if context:
                # Split into sentences and filter for substantial content
                sentences = context.replace('\n', ' ').split('. ')
                learnings = [
                    sentence.strip() + '.' for sentence in sentences 
                    if len(sentence.strip()) > 30 and not sentence.strip().startswith('http')
                ][:10]  # Limit to 10 most relevant findings
            
            # Also check research sources for additional learnings
            research_sources = getattr(researcher, 'research_sources', [])
            if research_sources:
                for source in research_sources[:5]:  # Limit to 5 sources
                    if hasattr(source, 'content') and source.content:
                        # Extract key sentences from source content
                        source_sentences = source.content[:200].replace('\n', ' ').split('. ')
                        for sentence in source_sentences[:2]:  # Max 2 per source
                            if len(sentence.strip()) > 20:
                                learnings.append(f"From source: {sentence.strip()}.")
            
            return learnings[:15]  # Maximum 15 learnings total
            
        except Exception as e:
            logger.warning(f"Error extracting learnings: {e}")
            return []

    async def _conduct_research_with_termination_checks(self, researcher: GPTResearcher, task: RuntimeAsyncQueryTask):
        """Conduct research with periodic checks for termination signals (non-blocking)"""
        try:
            # Start the research as a background task
            research_coroutine = researcher.conduct_research()
            research_task = asyncio.create_task(research_coroutine)
            
            # Periodically check for termination while research runs
            check_interval = 5  # Check every 5 seconds for immediate responsiveness
            
            while not research_task.done():
                try:
                    # Wait for research completion or timeout
                    await asyncio.wait_for(asyncio.shield(research_task), timeout=check_interval)
                    break  # Research completed normally
                except asyncio.TimeoutError:
                    # Check for termination signal
                    if task.should_terminate_early.is_set():
                        logger.info(f"[FlashResearchRuntime] Terminating research early for task {task.task_id}")
                        research_task.cancel()
                        try:
                            await research_task
                        except asyncio.CancelledError:
                            pass
                        break
                    # Continue waiting if no termination signal
                    continue
            
            # Ensure task is completed
            if not research_task.done():
                await research_task
                
        except asyncio.CancelledError:
            logger.debug(f"[FlashResearchRuntime] Research with termination checks cancelled for task {task.task_id}")
            raise
        except Exception as e:
            logger.error(f"[FlashResearchRuntime] Error in research with termination checks: {e}")
            raise
    
    async def _generate_runtime_recursive_tasks(self, parent_result: Dict[str, Any], current_depth: int,
                                              current_breadth: int, task_manager: RuntimeAsyncTaskManager,
                                              progress_tracker: AsyncProgress, on_progress=None):
        """Generate recursive tasks using simple approach like ParallelizedDeepResearch"""
        try:
            # Use simple breadth reduction like in ParallelizedDeepResearch
            new_breadth = max(2, current_breadth // 2)
            new_depth = current_depth + 1
            
            # Create next query from parent result
            next_query = f"""
            Previous research goal: {parent_result['researchGoal']}
            Follow-up questions: {' '.join(parent_result['followUpQuestions'])}
            """
            
            # Create planning node
            recursive_planning_node_id = self.logger.add_node(
                depth=new_depth,
                breadth=new_breadth,
                query=next_query,
                parent_id=parent_result['node_id'],
                status="started",
                operation="plan",
                start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # Generate sub-queries using simple approach
            sub_queries = await self.generate_serp_queries(next_query, num_queries=new_breadth)
            
            logger.debug(f"[FlashResearchRuntime] Generated {len(sub_queries)} runtime recursive queries for depth {new_depth}")
            
            # Update planning node
            self.logger.update_node(
                node_id=recursive_planning_node_id,
                status="completed",
                results={"generated_queries": len(sub_queries)},
                end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # Create and launch runtime recursive tasks
            for serp_query in sub_queries:
                task_id = await task_manager.create_task_id()
                runtime_task = RuntimeAsyncQueryTask(
                    serp_query=serp_query,
                    depth=new_depth,
                    breadth=new_breadth,
                    parent_node_id=recursive_planning_node_id,
                    task_id=task_id,
                    research_goal=serp_query.get('researchGoal', ''),
                    satisfaction_threshold=self.satisfaction_threshold,
                    quality_threshold=self.quality_threshold,
                    max_execution_time=self.max_task_execution_time
                )
                
                await task_manager.register_runtime_task(runtime_task)
                
                # Create and launch asyncio task
                asyncio_task = asyncio.create_task(
                    self._async_runtime_research(
                        runtime_task, task_manager, progress_tracker, on_progress
                    )
                )
                runtime_task.asyncio_task = asyncio_task
                
                logger.debug(f"[FlashResearchRuntime] Launched runtime recursive task {task_id} at depth {new_depth}")
            
            logger.debug(f"[FlashResearchRuntime] All runtime recursive tasks launched for depth {new_depth}")
            
        except Exception as e:
            logger.error(f"[FlashResearchRuntime] Error in runtime recursive task generation: {str(e)}")
            logger.error(f"[FlashResearchRuntime] Exception traceback: {traceback.format_exc()}")
    
    async def _wait_for_runtime_tasks_completion(self, task_manager: RuntimeAsyncTaskManager):
        """Wait for all runtime tasks to complete with enhanced monitoring"""
        logger.debug("[FlashResearchRuntime] Waiting for all runtime tasks to complete...")
        
        max_wait_time = 60 * 15  # 15 minutes timeout
        start_time = time.time()
        last_stats_time = start_time
        
        while await task_manager.has_active_tasks():
            current_time = time.time()
            
            # Check for timeout
            if current_time - start_time > max_wait_time:
                stats = await task_manager.get_task_stats()
                runtime_stats = task_manager.get_runtime_statistics()
                logger.error(f"[FlashResearchRuntime] Timeout waiting for tasks. Stats: {stats}, Runtime: {runtime_stats}")
                await task_manager.cancel_all_tasks()
                break
            
            # Log stats periodically
            if current_time - last_stats_time > 15:  # Every 15 seconds
                stats = await task_manager.get_task_stats()
                runtime_stats = task_manager.get_runtime_statistics()
                logger.debug(f"[FlashResearchRuntime] Task stats: {stats}")
                logger.debug(f"[FlashResearchRuntime] Runtime stats: {runtime_stats}")
                last_stats_time = current_time
            
            await asyncio.sleep(1.0)
        
        final_stats = task_manager.get_runtime_statistics()
        logger.info(f"[FlashResearchRuntime] All runtime tasks completed. Final stats: {final_stats}")
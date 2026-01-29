from typing import List, Dict, Any, Optional, Set
from fastapi import WebSocket
import asyncio
import logging
import time
from datetime import datetime
import traceback

from parallelresearch.deep_research import TaskState, DeepResearch
from parallelresearch.agent import GPTResearcher

from gpt_researcher.utils.enum import ReportType, ReportSource, Tone

from utils.vector_db import load_vector_db
from utils import ResearchProgress, trim_context_to_word_limit

logger = logging.getLogger(__name__)


class AsyncProgress:
    """Async-safe progress tracking"""
    def __init__(self, total_depth: int, total_breadth: int):
        self._lock = asyncio.Lock()
        self.current_depth = total_depth
        self.total_depth = total_depth
        self.current_breadth = 0
        self.total_breadth = total_breadth
        self.current_query: Optional[str] = None
        self.total_queries = 0
        self.completed_queries = 0
    
    async def update_progress(self, current_query: str = None, completed: int = 0):
        async with self._lock:
            if current_query:
                self.current_query = current_query
            self.completed_queries += completed
    
    async def set_total_queries(self, total: int):
        async with self._lock:
            self.total_queries = total
    
    async def get_progress_copy(self):
        async with self._lock:
            # Return a copy for safe reading
            return {
                'current_depth': self.current_depth,
                'total_depth': self.total_depth,
                'current_breadth': self.current_breadth,
                'total_breadth': self.total_breadth,
                'current_query': self.current_query,
                'total_queries': self.total_queries,
                'completed_queries': self.completed_queries
            }

class AsyncQueryTask:
    """Represents a query task to be processed asynchronously"""
    def __init__(self, serp_query: Dict[str, str], depth: int, breadth: int, 
                 parent_node_id: Optional[int], task_id: str):
        self.serp_query = serp_query
        self.depth = depth
        self.breadth = breadth
        self.parent_node_id = parent_node_id
        self.task_id = task_id
        self.result = None
        self.error = None
        self.start_time = None
        self.end_time = None
        self.state = TaskState.PENDING
        self.asyncio_task: Optional[asyncio.Task] = None
        
    def cancel(self) -> bool:
        """Cancel the task if it's running"""
        if self.asyncio_task and not self.asyncio_task.done():
            self.state = TaskState.CANCELLED
            return self.asyncio_task.cancel()
        return False
        
    def is_done(self) -> bool:
        """Check if task is completed (successfully or not)"""
        return self.state in [TaskState.COMPLETED, TaskState.CANCELLED, TaskState.FAILED]

class AsyncTaskManager:
    """Async-safe task manager for research operations"""
    def __init__(self):
        self._lock = asyncio.Lock()
        self.learnings = []
        self.citations = {}
        self.visited_urls = set()
        self.context = []
        self.sources = []
        self.active_tasks: Dict[str, AsyncQueryTask] = {}
        self.completed_tasks: Dict[str, AsyncQueryTask] = {}
        self.task_counter = 0
        self.total_tasks_submitted = 0
        self.total_tasks_completed = 0
    
    async def add_learning(self, learning: str):
        async with self._lock:
            self.learnings.append(learning)
    
    async def add_learnings(self, learnings: List[str]):
        async with self._lock:
            self.learnings.extend(learnings)
    
    async def add_citation(self, learning: str, citation: str):
        async with self._lock:
            self.citations[learning] = citation
    
    async def add_citations(self, citations: Dict[str, str]):
        async with self._lock:
            self.citations.update(citations)
    
    async def add_visited_urls(self, urls: Set[str]):
        async with self._lock:
            self.visited_urls.update(urls)
    
    async def add_context(self, context: str):
        async with self._lock:
            self.context.append(context)
    
    async def add_sources(self, sources: List[str]):
        async with self._lock:
            self.sources.extend(sources)
    
    async def create_task_id(self) -> str:
        async with self._lock:
            self.task_counter += 1
            return f"task_{self.task_counter}"
    
    async def register_task(self, task: AsyncQueryTask):
        """Register a new task"""
        async with self._lock:
            self.active_tasks[task.task_id] = task
            self.total_tasks_submitted += 1
    
    async def complete_task(self, task_id: str, result: Dict[str, Any] = None, error: Exception = None):
        """Complete a task and update tracking"""
        async with self._lock:
            if task_id in self.active_tasks:
                task = self.active_tasks.pop(task_id)
                task.result = result
                task.error = error
                task.end_time = datetime.now()
                if error:
                    task.state = TaskState.FAILED
                else:
                    task.state = TaskState.COMPLETED
                self.completed_tasks[task_id] = task
                self.total_tasks_completed += 1
                
                # Add successful results to shared data immediately
                if result and not error:
                    await self._add_result_data(result)
    
    async def _add_result_data(self, result: Dict[str, Any]):
        """Add result data to shared collections (called with lock held)"""
        if 'learnings' in result:
            self.learnings.extend(result['learnings'])
        if 'visited_urls' in result:
            self.visited_urls.update(set(result['visited_urls']))
        if 'citations' in result:
            self.citations.update(result['citations'])
        if 'context' in result and result['context']:
            self.context.append(result['context'])
        if 'sources' in result and result['sources']:
            self.sources.extend(result['sources'])
    
    async def get_task_stats(self) -> Dict[str, int]:
        """Get current task processing statistics"""
        async with self._lock:
            return {
                'submitted': self.total_tasks_submitted,
                'completed': self.total_tasks_completed,
                'active': len(self.active_tasks),
                'total_registered': len(self.active_tasks) + len(self.completed_tasks)
            }
    
    async def has_active_tasks(self) -> bool:
        """Check if there are any active tasks"""
        async with self._lock:
            return len(self.active_tasks) > 0
    
    async def cancel_all_tasks(self):
        """Cancel all active tasks"""
        async with self._lock:
            cancelled_count = 0
            for task in self.active_tasks.values():
                if task.cancel():
                    cancelled_count += 1
            logger.info(f"[Parallelized DeepResearch] Cancelled {cancelled_count} active tasks")

    async def get_all_data(self) -> Dict[str, Any]:
        async with self._lock:
            return {
                'learnings': list(self.learnings),
                'citations': self.citations.copy(),
                'visited_urls': list(self.visited_urls),
                'context': self.context.copy(),
                'sources': self.sources.copy()
            }



class ParallelDeepResearch(DeepResearch):
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
        # Create semaphore for concurrency control
        self.semaphore = asyncio.Semaphore(self.concurrency_limit)


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
        logger.debug(f"[Parallelized DeepResearch] async parallel research called with query: {query[:100]}..., breadth: {breadth}, depth: {depth}")
        
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
            status=TaskState.STARTED.value,
            operation="plan",
            start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        # Generate initial queries (NOTE: Controlled by BREADTH)
        serp_queries = await self.generate_serp_queries(query, num_queries=breadth)
        
        logger.debug(f"[Parallelized DeepResearch] Generated {len(serp_queries)} initial queries")
        
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

        logger.debug(f"[Parallelized DeepResearch] All initial tasks launched, waiting for completion...")
        
        # Wait for all tasks (including recursive ones) to complete
        await self._wait_for_all_tasks_completion(task_manager)
        
        # Get final results
        final_data = await task_manager.get_all_data()
        
        # Trim context to stay within word limits
        trimmed_context = trim_context_to_word_limit(final_data['context'], max_words=self.max_context_words)
        logger.info(f"[Parallelized DeepResearch] Trimmed context from {len(final_data['context'])} items to {len(trimmed_context)} items")
        final_data['context'] = trimmed_context

        # Log completion
        self.logger.update_node(
            node_id=current_node_id,
            status=TaskState.COMPLETED.value,
            results={
                'learnings': final_data['learnings'],
                'citations': final_data['citations']
            },
            visited_urls=final_data['visited_urls'],
            end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        logger.debug(f"[Parallelized DeepResearch] async research completed")
        return final_data

    async def _async_research(self, task: AsyncQueryTask, task_manager: AsyncTaskManager,
                               progress_tracker: AsyncProgress, on_progress=None) -> None:
        """Process a single query task asynchronously with semaphore-controlled concurrency"""
        async with self.semaphore:  # Control concurrency
            researcher = None
            query_node_id = None
            try:
                task.state = TaskState.RUNNING
                task.start_time = datetime.now()
                
                logger.debug(f"[Parallelized DeepResearch] Processing async task {task.task_id} at depth {task.depth} for query: {task.serp_query['query']}")
                
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
                    status=TaskState.STARTED.value,
                    operation="research",
                    start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )

                # Initialize researcher and conduct research
                researcher = GPTResearcher(
                    query=task.serp_query['query'],
                    report_type=ReportType.ResearchReport.value,
                    report_source=self.config.report_source,
                    vector_store=load_vector_db("vector_db") if self.config.report_source == ReportSource.LangChainVectorStore.value else None,
                    tone=self.tone,
                    websocket=self.websocket,
                    config_path=self.config_path,
                    headers=self.headers,
                    log_handler=self.logger,
                    enable_enhanced_logging=self.enable_enhanced_logging,
                    parent_node_id=query_node_id,
                    verbose=self.verbose
                )

                # Conduct research with timeout (consistent with other implementations)
                try:
                    # Use configured timeout or default to 300 seconds
                    research_timeout = getattr(self.config, "individual_research_timeout", 300)
                    await asyncio.wait_for(
                        researcher.conduct_research(),
                        timeout=research_timeout
                    )
                except asyncio.TimeoutError:
                    logger.error(f"[Parallelized DeepResearch] Research timed out after {research_timeout}s for query: {task.serp_query['query'][:100]}...")
                    raise asyncio.TimeoutError(f"Research timed out for query: {task.serp_query['query'][:100]}...")
                
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
                    status=TaskState.COMPLETED.value,
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
                
                # Mark task as completed
                await task_manager.complete_task(task.task_id, result)
                
                # Generate recursive tasks if needed (NOTE: Controlled by DEPTH)
                if task.depth < self.config.max_depth:
                    logger.debug(f"[Parallelized DeepResearch] Generating recursive tasks for depth {task.depth + 1}")
                    
                    try:
                        await self._generate_recursive_tasks(
                            result, task.depth, task.breadth, task_manager,
                            progress_tracker, on_progress
                        )
                    except Exception as e:
                        logger.error(f"[Parallelized DeepResearch] Error generating recursive tasks: {e}")
                
                logger.debug(f"[Parallelized DeepResearch] Completed async task {task.task_id}")

            except asyncio.CancelledError:
                logger.info(f"[Parallelized DeepResearch] Task {task.task_id} was cancelled")
                # Best-effort salvage of intermediate data and mark node as cancelled
                try:
                    salvage = await self._salvage_researcher_data(
                        researcher,
                        query_node_id=query_node_id,
                        mark_status=TaskState.CANCELLED.value
                    )
                    # Feed salvaged data into task manager for aggregation
                    if salvage.get("visited"):
                        await task_manager.add_visited_urls(set(salvage["visited"]))
                    for ctx in salvage.get("context", []) or []:
                        await task_manager.add_context(ctx)
                    if salvage.get("sources"):
                        await task_manager.add_sources(salvage["sources"]) 
                except Exception as salvage_err:
                    logger.debug(f"[Parallelized DeepResearch] Salvage on cancellation failed: {salvage_err}")
                task.state = TaskState.CANCELLED
                await task_manager.complete_task(task.task_id, error=asyncio.CancelledError("Task cancelled"))
                raise
            except Exception as e:
                logger.error(f"[Parallelized DeepResearch] Error in async task {task.task_id}: {str(e)}")
                logger.error(f"[Parallelized DeepResearch] Exception traceback: {traceback.format_exc()}")
                # Best-effort salvage and mark node as failed
                try:
                    salvage = await self._salvage_researcher_data(
                        researcher,
                        query_node_id=query_node_id,
                        mark_status=TaskState.FAILED.value
                    )
                    if salvage.get("visited"):
                        await task_manager.add_visited_urls(set(salvage["visited"]))
                    for ctx in salvage.get("context", []) or []:
                        await task_manager.add_context(ctx)
                    if salvage.get("sources"):
                        await task_manager.add_sources(salvage["sources"]) 
                except Exception as salvage_err:
                    logger.debug(f"[Parallelized DeepResearch] Salvage on cancellation failed: {salvage_err}")
                task.state = TaskState.FAILED
                await task_manager.complete_task(task.task_id, error=e)

    async def _generate_recursive_tasks(self, parent_result: Dict[str, Any], current_depth: int, 
                                       current_breadth: int, task_manager: AsyncTaskManager,
                                       progress_tracker: AsyncProgress, on_progress=None):
        """Generate recursive tasks and launch them as async tasks"""
        try:
            # NOTE: Controlling BREADTH, currently each recursive level halves the breadth
            new_breadth = max(2, current_breadth // 2)
            new_depth = current_depth + 1
            
            # Create next query from parent result
            next_query = f"""
            Previous research goal: {parent_result['researchGoal']}
            Follow-up questions: {' '.join(parent_result['followUpQuestions'])}
            """
            
            # Create planning node for this recursive level
            recursive_planning_node_id = self.logger.add_node(
                depth=new_depth,
                breadth=new_breadth,
                query=next_query,
                parent_id=parent_result['node_id'],
                status=TaskState.STARTED.value,
                operation="plan",
                start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            logger.debug(f"[Parallelized DeepResearch] Created recursive planning node: {recursive_planning_node_id} for depth {new_depth}")
            
            # Generate sub-queries for this recursive level (NOTE: Controlled by BREADTH)
            sub_queries = await self.generate_serp_queries(next_query, num_queries=new_breadth)
            
            logger.debug(f"[Parallelized DeepResearch] Generated {len(sub_queries)} recursive queries for depth {new_depth}")
            
            # Update the planning node with completion
            self.logger.update_node(
                node_id=recursive_planning_node_id,
                status=TaskState.COMPLETED.value,
                results={"generated_queries": len(sub_queries)},
                end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # Create and launch recursive async tasks immediately
            for serp_query in sub_queries:
                task_id = await task_manager.create_task_id()
                query_task = AsyncQueryTask(serp_query, new_depth, new_breadth, recursive_planning_node_id, task_id)
                await task_manager.register_task(query_task)
                
                # Create and launch asyncio task immediately
                asyncio_task = asyncio.create_task(
                    self._async_research(
                        query_task, task_manager, progress_tracker, on_progress
                    )
                )
                query_task.asyncio_task = asyncio_task
                
                logger.debug(f"[Parallelized DeepResearch] Launched recursive task {task_id} at depth {new_depth}")
            
            logger.debug(f"[Parallelized DeepResearch] All recursive tasks launched for depth {new_depth}")
            
        except Exception as e:
            logger.error(f"[Parallelized DeepResearch] Error in _generate_recursive_tasks: {str(e)}")
            logger.error(f"[Parallelized DeepResearch] Exception traceback: {traceback.format_exc()}")

    async def _wait_for_all_tasks_completion(self, task_manager: AsyncTaskManager):
        """Wait for all active tasks to complete with timeout and better logging"""
        logger.debug("[Parallelized DeepResearch] Waiting for all tasks to complete...")
        # Use configured global timeout or default to 3600 seconds (consistent with other implementations)
        max_wait_time = getattr(self.config, "time_limit_seconds", 3600)
        start_time = time.time()
        last_stats_time = start_time
        
        while await task_manager.has_active_tasks():
            current_time = time.time()
            
            # Check for timeout
            if current_time - start_time > max_wait_time:
                stats = await task_manager.get_task_stats()
                logger.error(f"[Parallelized DeepResearch] Timeout waiting for tasks. Stats: {stats}")
                # Cancel remaining tasks
                await task_manager.cancel_all_tasks()
                break
            
            # Log stats periodically
            if current_time - last_stats_time > 10:  # Every 10 seconds
                stats = await task_manager.get_task_stats()
                logger.debug(f"[Parallelized DeepResearch] Task stats: {stats}")
                last_stats_time = current_time
            
            await asyncio.sleep(0.5)  # Wait before checking again
            
        logger.debug("[Parallelized DeepResearch] All tasks completed")

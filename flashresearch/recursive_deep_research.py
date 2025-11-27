from typing import List, Dict, Any, Optional, Set
from fastapi import WebSocket
import asyncio
import logging
from datetime import datetime
import traceback

from flashresearch.agent import GPTResearcher
from flashresearch.deep_research import TaskState, DeepResearch

from gpt_researcher.utils.enum import ReportType, ReportSource, Tone

from utils.vector_db import load_vector_db
from utils import ResearchProgress, trim_context_to_word_limit

logger = logging.getLogger(__name__)


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


class NodeResults:
    """Represents research results for a single node with merged findings and node annotations"""
    def __init__(self, node_id: int):
        self.node_id = node_id
        # Merged findings with node annotations
        self.learnings = []  # Each entry will have format "text [Node: X]"
        self.citations = {}  # Key: "learning [Node: X]", Value: "citation [Node: X]"
        self.visited_urls = set()  # Each entry will have format "url [Node: X]"
        self.context = []  # Each entry will have format "context [Node: X]"
        self.sources = []  # Each entry will have format "source [Node: X]"
        # Parent node reference
        self.parent_node_id: Optional[int] = None


class AsyncTaskManager:
    """Async-safe task manager for research operations"""
    def __init__(self):
        self._lock = asyncio.Lock()
        # Task tracking with full protocol from parallel version
        self.active_tasks_dict: Dict[str, AsyncQueryTask] = {}
        self.completed_tasks_dict: Dict[str, AsyncQueryTask] = {}
        self.task_counter = 0
        self.total_tasks_submitted = 0
        self.total_tasks_completed = 0
        # Map of node_id to NodeResults
        self.node_results: Dict[int, NodeResults] = {}
    
    async def register_node(self, node_id: int, parent_node_id: Optional[int] = None):
        """Register a new node and set up its result tracking"""
        async with self._lock:
            node_results = NodeResults(node_id)
            node_results.parent_node_id = parent_node_id
            self.node_results[node_id] = node_results
    
    async def add_direct_learning(self, node_id: int, learning: str):
        """Add a direct learning to a node with node annotation and propagate to parents"""
        async with self._lock:
            if node_id in self.node_results:
                node = self.node_results[node_id]
                annotated_learning = f"{learning}" #  [Node: {node_id}]
                node.learnings.append(annotated_learning)
                # Propagate to parent
                await self._propagate_to_parent(node_id, 'learning', annotated_learning)
    
    async def add_direct_learnings(self, node_id: int, learnings: List[str]):
        """Add multiple direct learnings to a node with node annotations and propagate to parents"""
        async with self._lock:
            if node_id in self.node_results:
                node = self.node_results[node_id]
                for learning in learnings:
                    annotated_learning = f"{learning}" #  [Node: {node_id}]
                    node.learnings.append(annotated_learning)
                    # Propagate to parent
                    await self._propagate_to_parent(node_id, 'learning', annotated_learning)
    
    async def add_direct_citation(self, node_id: int, learning: str, citation: str):
        """Add a direct citation to a node with node annotations and propagate to parents"""
        async with self._lock:
            if node_id in self.node_results:
                node = self.node_results[node_id]
                annotated_learning = f"{learning}" #  [Node: {node_id}]
                annotated_citation = f"{citation}" #  [Node: {node_id}]
                node.citations[annotated_learning] = annotated_citation
                # Propagate to parent
                await self._propagate_to_parent(node_id, 'citation', (annotated_learning, annotated_citation))
    
    async def add_direct_citations(self, node_id: int, citations: Dict[str, str]):
        """Add multiple direct citations to a node with node annotations and propagate to parents"""
        async with self._lock:
            if node_id in self.node_results:
                node = self.node_results[node_id]
                for learning, citation in citations.items():
                    annotated_learning = f"{learning}" #  [Node: {node_id}]
                    annotated_citation = f"{citation}" #  [Node: {node_id}]
                    node.citations[annotated_learning] = annotated_citation
                    # Propagate to parent
                    await self._propagate_to_parent(node_id, 'citation', (annotated_learning, annotated_citation))
    
    async def add_direct_visited_urls(self, node_id: int, urls: Set[str]):
        """Add direct visited URLs to a node with node annotations and propagate to parents"""
        async with self._lock:
            if node_id in self.node_results:
                node = self.node_results[node_id]
                for url in urls:
                    annotated_url = f"{url}" #  [Node: {node_id}]
                    node.visited_urls.add(annotated_url)
                    # Propagate to parent
                    await self._propagate_to_parent(node_id, 'visited_url', annotated_url)
    
    async def add_direct_context(self, node_id: int, context: str):
        """Add direct context to a node with node annotation and propagate to parents"""
        async with self._lock:
            if node_id in self.node_results:
                node = self.node_results[node_id]
                annotated_context = f"{context}" #  [Node: {node_id}]
                node.context.append(annotated_context)
                # Propagate to parent
                await self._propagate_to_parent(node_id, 'context', annotated_context)
    
    async def add_direct_sources(self, node_id: int, sources: List[str]):
        """Add direct sources to a node with node annotations and propagate to parents"""
        async with self._lock:
            if node_id in self.node_results:
                node = self.node_results[node_id]
                for source in sources:
                    annotated_source = f"{source}" #  [Node: {node_id}]
                    node.sources.append(annotated_source)
                    # Propagate to parent
                    await self._propagate_to_parent(node_id, 'source', annotated_source)
    
    async def _propagate_to_parent(self, node_id: int, result_type: str, value: Any):
        """Propagate a result to parent node (values are already annotated with source node)"""
        if node_id in self.node_results:
            node = self.node_results[node_id]
            if node.parent_node_id and node.parent_node_id in self.node_results:
                parent = self.node_results[node.parent_node_id]
                if result_type == 'learning':
                    parent.learnings.append(value)
                elif result_type == 'citation':
                    learning, citation = value
                    parent.citations[learning] = citation
                elif result_type == 'visited_url':
                    parent.visited_urls.add(value)
                elif result_type == 'context':
                    parent.context.append(value)
                elif result_type == 'source':
                    parent.sources.append(value)
                # Continue propagation up the tree
                await self._propagate_to_parent(node.parent_node_id, result_type, value)
    
    async def get_node_results(self, node_id: int) -> Optional[Dict[str, Any]]:
        """Get merged results for a specific node"""
        async with self._lock:
            if node_id not in self.node_results:
                return None
            
            node = self.node_results[node_id]
            return {
                'learnings': list(node.learnings),
                'citations': node.citations.copy(),
                'visited_urls': list(node.visited_urls),
                'context': list(node.context),
                'sources': list(node.sources)
            }
    
    async def get_all_data(self) -> Dict[str, Any]:
        """Get all research data (combined from all nodes with node annotations)"""
        async with self._lock:
            all_learnings = []
            all_citations = {}
            all_visited_urls = set()
            all_context = []
            all_sources = []
            
            for node in self.node_results.values():
                # Add results (already annotated with node IDs)
                all_learnings.extend(node.learnings)
                all_citations.update(node.citations)
                all_visited_urls.update(node.visited_urls)
                all_context.extend(node.context)
                all_sources.extend(node.sources)
            
            return {
                'learnings': list(all_learnings),
                'citations': all_citations.copy(),
                'visited_urls': list(all_visited_urls),
                'context': list(all_context),
                'sources': list(all_sources)
            }
    
    async def create_task_id(self) -> str:
        """Create a unique task ID"""
        async with self._lock:
            self.task_counter += 1
            return f"task_{self.task_counter}"
    
    async def register_task(self, task: AsyncQueryTask):
        """Register a new task"""
        async with self._lock:
            self.active_tasks_dict[task.task_id] = task
            self.total_tasks_submitted += 1
    
    async def complete_task(self, task_id: str, result: Dict[str, Any] = None, error: Exception = None):
        """Complete a task and update tracking"""
        async with self._lock:
            if task_id in self.active_tasks_dict:
                task = self.active_tasks_dict.pop(task_id)
                task.result = result
                task.error = error
                task.end_time = datetime.now()
                if error:
                    task.state = TaskState.FAILED
                else:
                    task.state = TaskState.COMPLETED
                self.completed_tasks_dict[task_id] = task
                self.total_tasks_completed += 1
    
    async def cancel_all_tasks(self):
        """Cancel all active tasks"""
        async with self._lock:
            cancelled_count = 0
            for task in self.active_tasks_dict.values():
                if task.cancel():
                    cancelled_count += 1
            logger.info(f"[Recursive DeepResearch] Cancelled {cancelled_count} active tasks")
    
    async def get_task_stats(self) -> Dict[str, int]:
        """Get current task processing statistics"""
        async with self._lock:
            return {
                'submitted': self.total_tasks_submitted,
                'completed': self.total_tasks_completed,
                'active': len(self.active_tasks_dict),
                'total_registered': len(self.active_tasks_dict) + len(self.completed_tasks_dict),
            }
    
    async def has_active_tasks(self) -> bool:
        """Check if there are any active tasks"""
        async with self._lock:
            return len(self.active_tasks_dict) > 0


class RecursiveDeepResearch(DeepResearch):
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
        self.task_manager = AsyncTaskManager()
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
        """Recursive async-based parallel research using asyncio task management"""
        logger.debug(f"[DeepResearch] async parallel research called with query: {query[:100]}..., breadth: {breadth}, depth: {depth}")

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
            # Create and register a proper AsyncQueryTask for this recursive call
            task_id = await self.task_manager.create_task_id()
            serp_query = {'query': query, 'researchGoal': f'Research depth {depth}'}
            query_task = AsyncQueryTask(serp_query, depth, breadth, parent_node_id, task_id)
            await self.task_manager.register_task(query_task)
            
            # Holder for deferred child recursion to run AFTER releasing the semaphore
            pending_children = None

            async with self.semaphore:  # Control concurrency
                researcher = None
                try:
                    query_task.state = TaskState.RUNNING
                    query_task.start_time = datetime.now()
                    
                    logger.debug(f"[Recursive DeepResearch] Processing async task {task_id} at depth {depth} for query: {query[:100]}...")
                    
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
                    await researcher.conduct_research()
                    
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
                            'citations': results['citations']
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

                    # If not at max depth, generate recursive queries
                    if depth < self.config.max_depth:
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
                        sub_queries = await self.generate_serp_queries(next_query, num_queries=new_breadth)
                        
                        logger.debug(f"[DeepResearch] Generated {len(sub_queries)} recursive queries for depth {new_depth}")
                        
                        # Defer launching recursive tasks until AFTER releasing the semaphore
                        pending_children = {
                            "sub_queries": sub_queries,
                            "new_breadth": new_breadth,
                            "new_depth": new_depth,
                            "recursive_planning_node_id": recursive_planning_node_id,
                        }
                        
                except asyncio.CancelledError:
                    logger.info(f"[Recursive DeepResearch] Task {task_id} was cancelled")
                    # Salvage partial data and mark node as cancelled
                    try:
                        salvage = await self._salvage_researcher_data(
                            researcher,
                            query_node_id=current_node_id,
                            mark_status=TaskState.CANCELLED.value
                        )
                        # Feed salvaged data into task manager for aggregation with node annotations
                        if salvage.get("visited"):
                            await self.task_manager.add_direct_visited_urls(current_node_id, set(salvage["visited"]))
                        for ctx in salvage.get("context", []) or []:
                            await self.task_manager.add_direct_context(current_node_id, ctx)
                        if salvage.get("sources"):
                            await self.task_manager.add_direct_sources(current_node_id, salvage["sources"]) 
                        # Best-effort: flush any accumulated results to the node before exiting
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
                        logger.error(f"[Recursive DeepResearch] Salvage on cancellation failed: {salvage_err}")
                    query_task.state = TaskState.CANCELLED
                    await self.task_manager.complete_task(task_id, error=asyncio.CancelledError("Task cancelled"))
                    raise
                except Exception as e:
                    logger.error(f"[Recursive DeepResearch] Error in recursive research task {task_id}: {str(e)}")
                    logger.error(f"[Recursive DeepResearch] Exception traceback: {traceback.format_exc()}")
                    # Best-effort salvage on error
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
                        # Best-effort: flush any accumulated results to the node before exiting
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
                        logger.error(f"[Recursive DeepResearch] Salvage on error failed: {salvage_err}")
                    query_task.state = TaskState.FAILED
                    await self.task_manager.complete_task(task_id, error=e)
                    raise e

            # After releasing the semaphore, run any pending recursive children
            if pending_children:
                try:
                    # Optional debug to help diagnose semaphore release ordering
                    logger.debug(f"[Recursive DeepResearch] Released semaphore for task {task_id}, launching {len(pending_children['sub_queries'])} recursive sub-tasks at depth {pending_children['new_depth']}")

                    recursive_tasks = []
                    for sub_query in pending_children["sub_queries"]:
                        recursive_task = asyncio.create_task(
                            self.deep_research(
                                query=sub_query['query'],
                                breadth=pending_children["new_breadth"],
                                depth=pending_children["new_depth"],
                                on_progress=on_progress,
                                parent_node_id=pending_children["recursive_planning_node_id"],  # Use planning node as parent
                                is_recursive=True
                            )
                        )
                        recursive_tasks.append(recursive_task)

                    # Wait for recursive tasks (no timeout - let individual research timeouts handle it)
                    await asyncio.gather(*recursive_tasks, return_exceptions=True)

                    # Update planning node after all child nodes terminate
                    self.logger.update_node(
                        node_id=pending_children["recursive_planning_node_id"],
                        status=TaskState.COMPLETED.value,
                        results={"generated_queries": len(pending_children["sub_queries"])},
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )

                    logger.debug(f"[Recursive DeepResearch] Completed task {task_id} with recursive sub-tasks")
                finally:
                    pending_children = None

        else:  # Root call - generate initial queries with proper task management
            # Generate initial queries (NOTE: Controlled by BREADTH)
            serp_queries = await self.generate_serp_queries(query, num_queries=breadth)
            logger.debug(f"[Recursive DeepResearch] Generated {len(serp_queries)} initial queries")
            
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
                
                logger.debug(f"[Recursive DeepResearch] Launched initial task {task_id} at depth {depth}")
            
            # Wait for all initial tasks to complete with timeout
            logger.debug(f"[Recursive DeepResearch] All initial tasks launched, waiting for completion...")
            try:
                # Use configured global timeout or default to 3600 seconds (60 minutes)
                root_timeout = getattr(self.config, "time_limit_seconds", 3600)
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=root_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"[DeepResearch] Root level tasks timed out after {root_timeout}s")
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
                'citations': node_results['citations']
            }
            
            self.logger.update_node(
                node_id=current_node_id,
                status=TaskState.COMPLETED.value,
                results=combined_results,
                visited_urls=node_results['visited_urls'] if not is_recursive else None,
                end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
        if not is_recursive:
            logger.debug(f"[Recursive DeepResearch] Root research completed")
            return final_data
        return None  # Recursive calls don't need to return data as it's stored in task_manager

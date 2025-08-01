from typing import List, Dict, Any, Optional, Set
from fastapi import WebSocket
import asyncio
import logging
import time
from datetime import datetime, timedelta
import traceback
import re
from pydantic import BaseModel
from enum import Enum

# NOTE: This is a modified version of the GPTResearcher class
# from gpt_researcher.agent import GPTResearcher
from modified_agent import GPTResearcher
from modified_researcher import get_vector_store_results
from gpt_researcher.llm_provider.generic.base import ReasoningEfforts
from gpt_researcher.utils.llm import create_chat_completion
from gpt_researcher.utils.enum import ReportType, ReportSource, Tone
from gpt_researcher.actions.query_processing import get_search_results

from build_vector_db import load_vector_db
from utils import Config, ResearchLogger, ResearchProgress, trim_context_to_word_limit

logger = logging.getLogger(__name__)


class TaskState(Enum):
    """Task lifecycle states"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


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
            logger.info(f"Cancelled {cancelled_count} active tasks")
    
    async def get_all_data(self) -> Dict[str, Any]:
        async with self._lock:
            return {
                'learnings': list(self.learnings),
                'citations': self.citations.copy(),
                'visited_urls': list(self.visited_urls),
                'context': self.context.copy(),
                'sources': self.sources.copy()
            }


class DeepResearch:
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
        self.query = query
        self.depth = depth
        self.websocket = websocket
        self.tone = tone
        self.config_path = config_path
        self.headers = headers or {}
        self.visited_urls: Set[str] = set()
        self.learnings: List[str] = []
        self.research_sources: List[str] = []
        self.context: List[str] = []
        self.progress_callback = progress_callback
        self.logger = ResearchLogger(logs_dir, update_callback=self._on_logger_update)  # Initialize logger with callback
        self.enable_enhanced_logging = True

        self.config = Config(config_path)
        self.breadth = self.config.max_breadth
        self.concurrency_limit = self.config.concurrency_limit

        # Create semaphore for concurrency control
        self.semaphore = asyncio.Semaphore(self.concurrency_limit)

        self.researcher = GPTResearcher(
            query=self.query,
            report_type=ReportType.DeepResearch.value,
            report_source=self.config.report_source,
            # NOTE: Using the langchain vector store
            # vector_store=load_vector_db("vector_db"),
            tone=self.tone,
            websocket=self.websocket,
            config_path=self.config_path,
            headers=self.headers
        )
    
    def _on_logger_update(self, log_data):
        """Called whenever the logger updates the progress.json file"""
        if self.progress_callback:
            try:
                self.progress_callback({
                    'type': 'visualization_update',
                    'nodes': log_data.get('nodes', []),
                    'edges': log_data.get('edges', [])
                })
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")

    async def generate_feedback(self, query: str, num_questions: int = 3) -> List[str]:
        """Generate follow-up questions to clarify research direction"""
        if self.config.report_source == ReportSource.LangChainVectorStore.value:
            search_results = await get_vector_store_results(query, self.researcher.vector_store, self.researcher.vector_store_filter)
        else:
            search_results = await get_search_results(query, self.researcher.retrievers[0])
        logger.info(f"Initial web knowledge obtained: {len(search_results)} results")

        # Get current time for context
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        messages = [
            {"role": "system", "content": "You are an expert researcher. Your task is to analyze the original query and search results, then generate targeted questions that explore different aspects and time periods of the topic."},
            {"role": "user",
            "content": f"""Original query: {query}

Current time: {current_time}

Search results:
{search_results}

Based on these results, the original query, and the current time, generate {num_questions} unique questions. Each question should explore a different aspect or time period of the topic, considering recent developments up to {current_time}.

Format each question on a new line starting with 'Question: '"""}
            ]

        response = await create_chat_completion(
            messages=messages,
            llm_provider=self.config.llm_provider,
            model=self.config.reasoning_model,  # Using reasoning model for better question generation
            # NOTE: temperature set to 0 for reproducibility
            temperature=0,
            max_tokens=500,
            reasoning_effort=ReasoningEfforts.High.value,
            seed=42
        )

        # Parse questions from response
        questions = [q.replace('Question:', '').strip()
                    for q in response.split('\n')
                    if q.strip().startswith('Question:')]
        return questions[:num_questions]

    async def generate_serp_queries(self, query: str, num_queries: int = 3) -> List[Dict[str, str]]:
        """Generate SERP queries for research"""

        # Pydantic models for structured output
        class ResearchQuery(BaseModel):
            query: str
            researchGoal: str

        class SerpQueriesResponse(BaseModel):
            queries: List[ResearchQuery]

        messages = [
            {"role": "system", "content": "You are an expert researcher generating search queries. Generate exactly the requested number of unique search queries with their research goals."},
            {"role": "user",
                "content": f"Generate {num_queries} unique search queries to research the following topic thoroughly. For each query, provide a clear research goal that explains what specific aspect or information the query aims to uncover: {query}"}
        ]
        
        response = await create_chat_completion(
            messages=messages,
            llm_provider=self.config.llm_provider,
            model=self.config.standard_model,  # Using GPT-4 for general task
            # NOTE: temperature set to 0 for reproducibility
            temperature=0,
            # temperature=0.7,
            reasoning_effort=ReasoningEfforts.High.value,
            max_tokens=1000,
            seed=42,
            response_format=SerpQueriesResponse  # Use structured output
        )

        # convert response to structured format
        if isinstance(response, str):
            try:
                response = SerpQueriesResponse.model_validate_json(response)
            except Exception as e:
                logger.error(f"Failed to parse SERP queries response: {str(e)}")
                logger.error(f"Response content: {response}")
                raise ValueError("Failed to parse SERP queries response")

        # With structured output, response is already parsed
        queries = [{"query": q.query, "researchGoal": q.researchGoal} for q in response.queries]

        return queries[:num_queries]

    async def process_serp_result(self, query: str, context: str, num_learnings: int = 3) -> Dict[str, List[str]]:
        """Process research results to extract learnings and follow-up questions"""
        messages = [
            {"role": "system", "content": "You are an expert researcher analyzing search results."},
            {"role": "user",
            "content": f"Given the following research results for the query '{query}', extract key learnings and suggest follow-up questions. For each learning, include a citation to the source URL if available. Format each learning as 'Learning [source_url]: <insight>' and each question as 'Question: <question>':\n\n{context}"}
        ]
        
        response = await create_chat_completion(
            messages=messages,
            llm_provider=self.config.llm_provider,
            model=self.config.reasoning_model,  # Using reasoning model for analysis
            # NOTE: temperature set to 0 for reproducibility
            temperature=0,
            # temperature=0.7,
            max_tokens=1000,
            reasoning_effort=ReasoningEfforts.High.value,
            seed=42
        )

        # Parse learnings and questions with citations
        lines = response.split('\n')
        learnings = []
        questions = []
        citations = {}

        for line in lines:
            line = line.strip()
            if line.startswith('Learning'):
                # Extract URL if present in square brackets
                url_match = re.search(r'\[(.*?)\]:', line)
                if url_match:
                    url = url_match.group(1)
                    learning = line.split(':', 1)[1].strip()
                    learnings.append(learning)
                    citations[learning] = url
                else:
                    # Try to find URL in the line itself
                    url_match = re.search(
                        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', line)
                    if url_match:
                        url = url_match.group(0)
                        learning = line.replace(url, '').replace('Learning:', '').strip()
                        learnings.append(learning)
                        citations[learning] = url
                    else:
                        learnings.append(line.replace('Learning:', '').strip())
            elif line.startswith('Question:'):
                questions.append(line.replace('Question:', '').strip())

        return {
            'learnings': learnings[:num_learnings],
            'followUpQuestions': questions[:num_learnings],
            'citations': citations
        }

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
        logger.debug(f"[DeepResearch] async parallel research called with query: {query[:100]}..., breadth: {breadth}, depth: {depth}")
        
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

        # Generate initial queries (NOTE: Controlled by BREADTH)
        serp_queries = await self.generate_serp_queries(query, num_queries=breadth)
        
        logger.debug(f"[DeepResearch] Generated {len(serp_queries)} initial queries")
        
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

        logger.debug(f"[DeepResearch] All initial tasks launched, waiting for completion...")
        
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

        logger.debug(f"[DeepResearch] async research completed")
        return final_data

    async def _async_research(self, task: AsyncQueryTask, task_manager: AsyncTaskManager,
                               progress_tracker: AsyncProgress, on_progress=None) -> None:
        """Process a single query task asynchronously with semaphore-controlled concurrency"""
        async with self.semaphore:  # Control concurrency
            try:
                task.state = TaskState.RUNNING
                task.start_time = datetime.now()
                
                logger.debug(f"[DeepResearch] Processing async task {task.task_id} at depth {task.depth} for query: {task.serp_query['query']}")
                
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
                    # vector_store=load_vector_db("vector_db"),
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
                
                # Mark task as completed
                await task_manager.complete_task(task.task_id, result)
                
                # Generate recursive tasks if needed (NOTE: Controlled by DEPTH)
                if task.depth < self.config.max_depth:
                    logger.debug(f"[DeepResearch] Generating recursive tasks for depth {task.depth + 1}")
                    
                    try:
                        await self._generate_recursive_tasks(
                            result, task.depth, task.breadth, task_manager,
                            progress_tracker, on_progress
                        )
                    except Exception as e:
                        logger.error(f"[DeepResearch] Error generating recursive tasks: {e}")
                
                logger.debug(f"[DeepResearch] Completed async task {task.task_id}")

            except asyncio.CancelledError:
                logger.info(f"[DeepResearch] Task {task.task_id} was cancelled")
                task.state = TaskState.CANCELLED
                await task_manager.complete_task(task.task_id, error=asyncio.CancelledError("Task cancelled"))
                raise
            except Exception as e:
                logger.error(f"[DeepResearch] Error in async task {task.task_id}: {str(e)}")
                logger.error(f"[DeepResearch] Exception traceback: {traceback.format_exc()}")
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
                status="started",
                operation="plan",
                start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            logger.debug(f"[DeepResearch] Created recursive planning node: {recursive_planning_node_id} for depth {new_depth}")
            
            # Generate sub-queries for this recursive level (NOTE: Controlled by BREADTH)
            sub_queries = await self.generate_serp_queries(next_query, num_queries=new_breadth)
            
            logger.debug(f"[DeepResearch] Generated {len(sub_queries)} recursive queries for depth {new_depth}")
            
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
                query_task = AsyncQueryTask(serp_query, new_depth, new_breadth, recursive_planning_node_id, task_id)
                await task_manager.register_task(query_task)
                
                # Create and launch asyncio task immediately
                asyncio_task = asyncio.create_task(
                    self._async_research(
                        query_task, task_manager, progress_tracker, on_progress
                    )
                )
                query_task.asyncio_task = asyncio_task
                
                logger.debug(f"[DeepResearch] Launched recursive task {task_id} at depth {new_depth}")
            
            logger.debug(f"[DeepResearch] All recursive tasks launched for depth {new_depth}")
            
        except Exception as e:
            logger.error(f"[DeepResearch] Error in _generate_recursive_tasks: {str(e)}")
            logger.error(f"[DeepResearch] Exception traceback: {traceback.format_exc()}")

    async def _wait_for_all_tasks_completion(self, task_manager: AsyncTaskManager):
        """Wait for all active tasks to complete with timeout and better logging"""
        logger.debug("[DeepResearch] Waiting for all tasks to complete...")
        
        max_wait_time = 300  # 5 minutes timeout
        start_time = time.time()
        last_stats_time = start_time
        
        while await task_manager.has_active_tasks():
            current_time = time.time()
            
            # Check for timeout
            if current_time - start_time > max_wait_time:
                stats = await task_manager.get_task_stats()
                logger.error(f"[DeepResearch] Timeout waiting for tasks. Stats: {stats}")
                # Cancel remaining tasks
                await task_manager.cancel_all_tasks()
                break
            
            # Log stats periodically
            if current_time - last_stats_time > 10:  # Every 10 seconds
                stats = await task_manager.get_task_stats()
                logger.debug(f"[DeepResearch] Task stats: {stats}")
                last_stats_time = current_time
            
            await asyncio.sleep(0.5)  # Wait before checking again
            
        logger.debug("[DeepResearch] All tasks completed")

    async def run(self, on_progress=None) -> str:
        """Run the deep research process and generate final report"""
        logger.debug(f"[DeepResearch] run() started with query: {self.query}")
        start_time = time.time()
        
        # Log initial costs
        initial_costs = self.researcher.get_costs()

        # Get initial feedback
        logger.debug(f"[DeepResearch] Generating feedback questions...")
        follow_up_questions = await self.generate_feedback(self.query)
        logger.debug(f"[DeepResearch] Generated {len(follow_up_questions)} feedback questions")

        # Collect answers (this would normally come from user interaction)
        answers = ["Automatically proceeding with research"] * len(follow_up_questions)

        # Combine query and Q&A
        follow_up_qa = [f"Q: {q}\nA: {a}" for q, a in zip(follow_up_questions, answers)]
        combined_query = f"""
        Initial Query: {self.query}\nFollow - up Questions and Answers:\n
        """ + "\n".join(follow_up_qa)

        logger.debug(f"[DeepResearch] Starting deep_research with combined query...")

        # Run deep research
        results = await self.deep_research(
            query=combined_query,
            breadth=self.breadth,
            depth=self.depth,
            on_progress=on_progress
        )

        logger.debug(f"[DeepResearch] deep_research completed, results: {len(results.get('visited_urls', []))} URLs, {len(results.get('learnings', []))} learnings")

        # Get costs after deep research
        research_costs = self.researcher.get_costs() - initial_costs

        # Log research costs if we have a log handler
        if self.researcher.log_handler:
            await self.researcher._log_event("research", step="deep_research_costs", details={
                "research_costs": research_costs,
                "total_costs": self.researcher.get_costs()
            })

        # Prepare context with citations
        context_with_citations = []
        for learning in results['learnings']:
            citation = results['citations'].get(learning, '')
            if citation:
                context_with_citations.append(f"{learning} [Source: {citation}]")
            else:
                context_with_citations.append(learning)

        # Add all research context
        if results.get('context'):
            context_with_citations.extend(results['context'])

        # Trim final context to word limit
        context_with_citations = trim_context_to_word_limit(context_with_citations)
        
        # Set enhanced context and visited URLs
        self.researcher.context = """"""
        for context in context_with_citations:
            if isinstance(context, str):
                self.researcher.context += f"{context}\n"
            elif isinstance(context, list):
                self.researcher.context += "\n".join(context) + "\n"
        self.researcher.context = self.researcher.context.strip()
        self.researcher.visited_urls = results['visited_urls']

        # Set research sources
        if results.get('sources'):
            self.researcher.research_sources = results['sources']

        # Log total execution time
        end_time = time.time()
        execution_time = timedelta(seconds=end_time - start_time)
        logger.info(f"Total research execution time: {execution_time}")
        logger.info(f"Total research costs: ${research_costs:.2f}")

        logger.debug(f"[DeepResearch] Final check: {len(results['visited_urls'])} visited URLs")

        if len(results['visited_urls']) == 0:
            logger.error(f"[DeepResearch] No visited URLs found - research failed!")

        logger.debug(f"[DeepResearch] Generating final report...")

        # Generate report
        report = await self.researcher.write_report()

        logger.debug(f"[DeepResearch] Report generated successfully, length: {len(report)}")

        return report
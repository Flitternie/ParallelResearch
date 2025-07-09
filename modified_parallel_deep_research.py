from typing import List, Dict, Any, Optional, Set
from fastapi import WebSocket
import asyncio
import logging
import time
from datetime import datetime, timedelta
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import queue
from pydantic import BaseModel

# NOTE: This is a modified version of the GPTResearcher class
# from gpt_researcher.agent import GPTResearcher
from modified_agent import GPTResearcher
from gpt_researcher.llm_provider.generic.base import ReasoningEfforts
from gpt_researcher.utils.llm import create_chat_completion
from gpt_researcher.utils.enum import ReportType, ReportSource, Tone
from gpt_researcher.actions.query_processing import get_search_results

from utils import ResearchLogger, ResearchProgress, trim_context_to_word_limit

logger = logging.getLogger(__name__)

# Constants for models
STANDARD_MODEL = "gpt-4o-mini"  # For standard tasks
REASONING_MODEL = "o3-mini"  # For reasoning tasks
LLM_PROVIDER = "openai"

MAX_DEPTH = 2
MAX_BREADTH = 4
CONCURRENCY_LIMIT = 4
MAX_WORKERS = 8  # Maximum number of worker threads

NEW_VERSION = True

class ThreadSafeData:
    """Thread-safe data structures for concurrent operations"""
    def __init__(self):
        self._lock = threading.Lock()
        self.learnings = []
        self.citations = {}
        self.visited_urls = set()
        self.context = []
        self.sources = []
        self.progress_queue = queue.Queue()
    
    def add_learning(self, learning: str):
        with self._lock:
            self.learnings.append(learning)
    
    def add_learnings(self, learnings: List[str]):
        with self._lock:
            self.learnings.extend(learnings)
    
    def add_citation(self, learning: str, citation: str):
        with self._lock:
            self.citations[learning] = citation
    
    def add_citations(self, citations: Dict[str, str]):
        with self._lock:
            self.citations.update(citations)
    
    def add_visited_urls(self, urls: Set[str]):
        with self._lock:
            self.visited_urls.update(urls)
    
    def add_context(self, context: str):
        with self._lock:
            self.context.append(context)
    
    def add_sources(self, sources: List[str]):
        with self._lock:
            self.sources.extend(sources)
    
    def get_all_data(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'learnings': list(set(self.learnings)),
                'citations': self.citations.copy(),
                'visited_urls': list(self.visited_urls),
                'context': self.context.copy(),
                'sources': self.sources.copy()
            }


class DeepResearch:
    def __init__(
        self,
        query: str,
        breadth: int = 4,
        depth: int = 1, # Depth of the research, starts at 1
        websocket: Optional[WebSocket] = None,
        tone: Tone = Tone.Objective,
        config_path: Optional[str] = None,
        headers: Optional[Dict] = None,
        concurrency_limit: int = CONCURRENCY_LIMIT,  # Match TypeScript version
        logs_dir: str = "research_progress.json",  # New parameter for logging
        max_workers: int = MAX_WORKERS,  # Maximum worker threads
    ):
        self.query = query
        self.breadth = breadth
        self.depth = depth
        self.websocket = websocket
        self.tone = tone
        self.config_path = config_path
        self.headers = headers or {}
        self.visited_urls: Set[str] = set()
        self.learnings: List[str] = []
        self.research_sources: List[str] = []
        self.context: List[str] = []
        self.concurrency_limit = concurrency_limit
        self.max_workers = max_workers
        self.logger = ResearchLogger(logs_dir)  # Initialize logger
        self.enable_enhanced_logging = True
        self.thread_safe_data = ThreadSafeData()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        self.researcher = GPTResearcher(
            query=self.query,
            report_type=ReportType.DeepResearch.value,
            report_source=ReportSource.Web.value,
            tone=self.tone,
            websocket=self.websocket,
            config_path=self.config_path,
            headers=self.headers
        )

    def __del__(self):
        """Cleanup executor on deletion"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)

    async def generate_feedback(self, query: str, num_questions: int = 3) -> List[str]:
        """Generate follow-up questions to clarify research direction"""

        if NEW_VERSION:
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
        else:
            messages = [
                {"role": "system", "content": "You are an expert researcher helping to clarify research directions."},
                {"role": "user", "content": f"Given the following query from the user, ask some follow up questions to clarify the research direction. Return a maximum of {num_questions} questions, but feel free to return less if the original query is clear. Format each question on a new line starting with 'Question: ': {query}"}
            ]

        response = await create_chat_completion(
            messages=messages,
            llm_provider=LLM_PROVIDER,
            model=REASONING_MODEL,  # Using reasoning model for better question generation
            # NOTE: temperature set to 0 for reproducibility
            # temperature=0.4,
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
        if NEW_VERSION:
            messages = [
                {"role": "system", "content": "You are an expert researcher generating search queries."},
                {"role": "user",
                    "content": f"Given the following prompt, generate {num_queries} unique search queries to research the topic thoroughly. For each query, provide a research goal. Format as 'Query: <query>' followed by 'Goal: <goal>' for each pair: {query}"}
            ]
        else:
            messages = [
                {"role": "system", "content": "You are an expert researcher generating search queries."},
                # TODO: add the current date and time to the prompt
                {"role": "user", "content": f"Given the following prompt, generate {num_queries} unique search queries to research the topic thoroughly. For each query, provide a research goal. Format as 'Query: <query>' followed by 'Goal: <goal>' for each pair: {query}"}
            ]

        response = await create_chat_completion(
            messages=messages,
            llm_provider=LLM_PROVIDER,
            model=STANDARD_MODEL,  # Using GPT-4 for general task
            # NOTE: temperature set to 0 for reproducibility
            temperature=0,
            # temperature=0.7,
            reasoning_effort=ReasoningEfforts.High.value,
            max_tokens=1000,
            seed=42
        )

        # Parse queries and goals from response
        lines = response.split('\n')
        queries = []
        current_query = {}

        for line in lines:
            line = line.strip()
            if line.startswith('Query:'):
                if current_query:
                    queries.append(current_query)
                current_query = {'query': line.replace('Query:', '').strip()}
            elif line.startswith('Goal:') and current_query:
                current_query['researchGoal'] = line.replace('Goal:', '').strip()

        if current_query:
            queries.append(current_query)

        return queries[:num_queries]

    async def process_serp_result(self, query: str, context: str, num_learnings: int = 3) -> Dict[str, List[str]]:
        """Process research results to extract learnings and follow-up questions"""
        if NEW_VERSION:
            messages = [
                {"role": "system", "content": "You are an expert researcher analyzing search results."},
                {"role": "user",
                "content": f"Given the following research results for the query '{query}', extract key learnings and suggest follow-up questions. For each learning, include a citation to the source URL if available. Format each learning as 'Learning [source_url]: <insight>' and each question as 'Question: <question>':\n\n{context}"}
            ]
        else:
            messages = [
                {"role": "system", "content": "You are an expert researcher analyzing search results."},
                {"role": "user", "content": f"Given the following research results for the query '{query}', extract key learnings and suggest follow-up questions. For each learning, include a citation to the source URL if available. Format each learning as 'Learning [source_url]: <insight>' and each question as 'Question: <question>':\n\n{context}"}
            ]


        response = await create_chat_completion(
            messages=messages,
            llm_provider=LLM_PROVIDER,
            model=REASONING_MODEL,  # Using reasoning model for analysis
            # NOTE: temperature set to 0 for reproducibility
            # temperature=0.7,
            temperature=0,
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
                import re
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

    def _process_query_sync(self, serp_query: Dict[str, str], depth: int, breadth: int, 
                           current_node_id: int, progress: ResearchProgress, 
                           on_progress=None) -> Optional[Dict[str, Any]]:
        """Synchronous version of process_query for threading"""
        try:
            logger.debug(f"[DeepResearch] Starting process_query for: {serp_query['query']}")
            progress.update_progress(current_query=serp_query['query'])
            if on_progress:
                on_progress(progress)

            # Log the start of processing this query
            query_node_id = self.logger.add_node(
                depth=depth,
                breadth=breadth,
                query=serp_query['query'],
                parent_id=current_node_id,
                research_goal=serp_query['researchGoal'],
                status="started",
                operation="research",
                start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

            logger.debug(f"[DeepResearch] Created query node: {query_node_id}")

            # Initialize researcher for this query with enhanced logging if enabled
            researcher = GPTResearcher(
                query=serp_query['query'],
                report_type=ReportType.ResearchReport.value,
                report_source=ReportSource.Web.value,
                tone=self.tone,
                websocket=self.websocket,
                config_path=self.config_path,
                headers=self.headers,
                log_handler=self.logger,  # Pass the logger as log_handler
                enable_enhanced_logging=self.enable_enhanced_logging,  # Pass enhanced logging flag
                parent_node_id=query_node_id  # Pass the current node id to the researcher
            )

            logger.debug(f"[DeepResearch] Initialized GPTResearcher, starting conduct_research")

            # Conduct research (this needs to be run in event loop)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(researcher.conduct_research())
            finally:
                loop.close()

            logger.debug(f"[DeepResearch] conduct_research completed")

            # Get results
            context = researcher.context
            visited = set(researcher.visited_urls)
            sources = researcher.research_sources

            logger.debug(f"[DeepResearch] Got results - context length: {len(str(context))}, visited URLs: {len(visited)}")

            # Process results (this also needs event loop)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results = loop.run_until_complete(self.process_serp_result(
                    query=serp_query['query'],
                    context=context
                ))
            finally:
                loop.close()

            logger.debug(f"[DeepResearch] Processed results - learnings: {len(results['learnings'])}")

            # Update progress
            progress.update_progress(completed=1)
            if on_progress:
                on_progress(progress)
            
            # Log the completion of this query
            self.logger.update_node(
                node_id=query_node_id,
                status="completed",
                visited_urls=visited,
                end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

            logger.debug(f"[DeepResearch] Successfully completed process_query for: {serp_query['query']}")

            return {
                'node_id': query_node_id,
                'learnings': results['learnings'],
                'visited_urls': visited,
                'followUpQuestions': results['followUpQuestions'],
                'researchGoal': serp_query['researchGoal'],
                'citations': results['citations'],
                'context': context if context else "",
                'sources': sources if sources else []
            }

        except Exception as e:
            logger.error(f"[DeepResearch] Error processing query '{serp_query['query']}': {str(e)}")
            logger.error(f"[DeepResearch] Exception traceback: {traceback.format_exc()}")
            # Log the error
            try:
                self.logger.update_node(
                    node_id=query_node_id,
                    status="error",
                    results={"error": str(e)}
                )
            except Exception as log_error:
                logger.error(f"[DeepResearch] Failed to log error: {log_error}")
            return None

    def _deep_research_sync(self, query: str, breadth: int, depth: int,
                           thread_safe_data: ThreadSafeData, on_progress=None,
                           parent_node_id: Optional[int] = None) -> Dict[str, Any]:
        """Synchronous version of deep_research for threading"""
        logger.debug(f"[DeepResearch] deep_research_sync called with query: {query[:100]}..., breadth: {breadth}, depth: {depth}")
        
        progress = ResearchProgress(depth, breadth)

        if on_progress:
            on_progress(progress)

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

        logger.debug(f"[DeepResearch] Created research level node: {current_node_id}")

        # Generate search queries (needs event loop)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            serp_queries = loop.run_until_complete(self.generate_serp_queries(query, num_queries=breadth))
        finally:
            loop.close()
        
        progress.total_queries = len(serp_queries)
        logger.debug(f"[DeepResearch] Generated {len(serp_queries)} SERP queries")

        logger.debug(f"[DeepResearch] Starting concurrent processing of {len(serp_queries)} queries")

        # Submit all queries to thread pool
        future_to_query = {}
        for serp_query in serp_queries:
            future = self.executor.submit(
                self._process_query_sync,
                serp_query, depth, breadth, current_node_id, progress, on_progress
            )
            future_to_query[future] = serp_query

        # Collect results as they complete
        results = []
        for future in as_completed(future_to_query):
            result = future.result()
            if result is not None:
                results.append(result)
                logger.debug(f"[DeepResearch] Completed query: {future_to_query[future]['query']}")

        logger.debug(f"[DeepResearch] Collected {len(results)} successful results")

        # Update thread-safe data
        for result in results:
            thread_safe_data.add_learnings(result['learnings'])
            thread_safe_data.add_visited_urls(set(result['visited_urls']))
            thread_safe_data.add_citations(result['citations'])
            if result['context']:
                thread_safe_data.add_context(result['context'])
            if result['sources']:
                thread_safe_data.add_sources(result['sources'])

        # Prepare for concurrent recursive calls
        if depth < MAX_DEPTH:
            logger.debug(f"[DeepResearch] Starting concurrent deeper research for {len(results)} nodes")
            
            # Create recursive tasks
            recursive_futures = []
            for result in results:
                new_breadth = max(2, breadth // 2)
                new_depth = depth + 1
                
                next_query = f"""
                Previous research goal: {result['researchGoal']}
                Follow-up questions: {' '.join(result['followUpQuestions'])}
                """

                # Submit recursive research task
                future = self.executor.submit(
                    self._deep_research_sync,
                    next_query,
                    new_breadth,
                    new_depth,
                    thread_safe_data,  # Share the same thread-safe data
                    on_progress,
                    result['node_id']
                )
                recursive_futures.append(future)

            # Wait for all recursive calls to complete
            for future in as_completed(recursive_futures):
                try:
                    future.result()  # This will raise any exceptions
                except Exception as e:
                    logger.error(f"[DeepResearch] Error in recursive research: {str(e)}")

        # Get final data from thread-safe storage
        final_data = thread_safe_data.get_all_data()

        # Trim context to stay within word limits
        trimmed_context = trim_context_to_word_limit(final_data['context'])
        logger.info(f"Trimmed context from {len(final_data['context'])} items to {len(trimmed_context)} items to stay within word limit")

        # Update final data with trimmed context
        final_data['context'] = trimmed_context

        # Log the completion of this research level
        self.logger.update_node(
            node_id=current_node_id,
            status="completed",
            results={
                'learnings': final_data['learnings'],
                'visited_urls': final_data['visited_urls'],
                'citations': final_data['citations']
            },
            end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        logger.debug(f"[DeepResearch] deep_research_sync completed")

        return final_data

    async def deep_research(
        self,
        query: str,
        breadth: int,
        depth: int,
        learnings: List[str] = None,
        citations: Dict[str, str] = None,
        visited_urls: Set[str] = None,
        on_progress = None,
        parent_node_id: Optional[int] = None  # New parameter for tracking parent node
    ) -> Dict[str, Any]:
        """Conduct deep iterative research using multi-threading"""
        logger.debug(f"[DeepResearch] deep_research called with query: {query[:100]}..., breadth: {breadth}, depth: {depth}")
        
        # Initialize thread-safe data
        thread_safe_data = ThreadSafeData()
        
        # Add initial data if provided
        if learnings:
            for learning in learnings:
                thread_safe_data.add_learning(learning)
        if citations:
            for learning, citation in citations.items():
                thread_safe_data.add_citation(learning, citation)
        if visited_urls:
            thread_safe_data.add_visited_urls(visited_urls)

        # Run the synchronous version in a thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self.executor,
            self._deep_research_sync,
            query, breadth, depth, thread_safe_data, on_progress, parent_node_id
        )

        return result

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
        self.researcher.context = "\n".join(context_with_citations)
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
            raise ValueError("No relevant information found, no Deep Research Report generated")

        logger.debug(f"[DeepResearch] Generating final report...")

        # Generate report
        report = await self.researcher.write_report()

        logger.debug(f"[DeepResearch] Report generated successfully, length: {len(report)}")

        return report
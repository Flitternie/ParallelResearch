from typing import List, Dict, Any, Optional, Set
from fastapi import WebSocket
import asyncio
import logging
import time
from datetime import datetime, timedelta
import traceback
import re
import contextlib
from enum import Enum
from pydantic import BaseModel

# NOTE: This is a modified version of the GPTResearcher class
from parallelresearch.agent import GPTResearcher
from parallelresearch.researcher import get_vector_store_results

from gpt_researcher.llm_provider.generic.base import ReasoningEfforts
from gpt_researcher.utils.llm import create_chat_completion
from gpt_researcher.utils.enum import ReportType, ReportSource, Tone
from gpt_researcher.actions.query_processing import get_search_results

from utils.vector_db import load_vector_db
from utils import Config, ResearchLogger, ResearchProgress, trim_context_to_word_limit

# NOTE: This is a modified version from gpt_researcher.skills.deep_research
logger = logging.getLogger(__name__)

class TaskState(Enum):
    """Task lifecycle states"""
    STARTED = "started"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    TERMINATED = "terminated"
    CANCELLED = "cancelled"
    FAILED = "error"


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
        # Configurable context word limit (fallback to 25k words)
        self.max_context_words = getattr(self.config, "max_context_words", 25000)

        # Optional hard time limit in seconds; if not set, run until completion
        # Expecting key TIME_LIMIT_SECONDS in config mapped to self.config.time_limit_seconds
        self.time_limit_seconds = getattr(self.config, "time_limit_seconds", None)

        # Accumulation lock to update class-level containers safely during concurrent processing
        self._partial_lock = asyncio.Lock()
        # Class-level citations store for early aggregation on timeout
        self.citations: Dict[str, str] = {}

        self.verbose = getattr(self.config, "verbose", False)

        self.researcher = GPTResearcher(
            query=self.query,
            report_type=ReportType.DeepResearch.value,
            report_source=self.config.report_source,
            vector_store=load_vector_db("vector_db") if self.config.report_source == ReportSource.LangChainVectorStore.value else None,
            tone=self.tone,
            websocket=self.websocket,
            config_path=self.config_path,
            headers=self.headers,
            verbose=self.verbose,
            root_query=self.query
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

    async def _salvage_researcher_data(
        self,
        researcher: Optional[GPTResearcher],
        query_node_id: Optional[int] = None,
        mark_status: Optional[str] = None
    ) -> Dict[str, Any]:
        """Safely salvage partial data from a researcher and update class-level stores.

        Optionally marks the corresponding node with a final status (e.g., "cancelled").
        Returns the salvaged collections for potential upstream use.
        """
        visited: Set[str] = set()
        sources: List[str] = []
        context: List[str] = []
        try:
            if researcher is not None:
                try:
                    visited = set(getattr(researcher, "visited_urls", set()) or [])
                except Exception:
                    visited = set()
                try:
                    sources = getattr(researcher, "research_sources", []) or []
                except Exception:
                    sources = []
                try:
                    ctx = getattr(researcher, "context", [])
                    if isinstance(ctx, list):
                        context = [c for c in ctx if isinstance(c, str)]
                    elif isinstance(ctx, str):
                        context = [ctx]
                    else:
                        context = []
                except Exception:
                    context = []

            async with self._partial_lock:
                if visited:
                    self.visited_urls.update(visited)
                if sources:
                    self.research_sources.extend(sources)
                if context:
                    self.context.extend(context)

            if mark_status and query_node_id is not None:
                try:
                    self.logger.update_node(
                        node_id=query_node_id,
                        status=mark_status,
                        visited_urls=visited,
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )
                except Exception:
                    pass
        except Exception as salvage_err:
            logger.debug(f"[DeepResearch] Salvage failed: {salvage_err}")

        return {"visited": visited, "sources": sources, "context": context}

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
            llm_provider=self.config.strategic_llm_provider,
            model=self.config.strategic_llm_model,
            # NOTE: temperature set to 0 for reproducibility
            temperature=0.0,
            max_tokens=500,
            reasoning_effort=ReasoningEfforts.High.value,
            seed=42,
            usage_tag="research"
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
            llm_provider=self.config.smart_llm_provider,
            model=self.config.smart_llm_model,
            # NOTE: temperature set to 0 for reproducibility
            temperature=0.0,
            reasoning_effort=ReasoningEfforts.High.value,
            max_tokens=1000,
            seed=42,
            response_format=SerpQueriesResponse,  # Use structured output
            usage_tag="research"
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
            llm_provider=self.config.strategic_llm_provider,
            model=self.config.strategic_llm_model,
            # NOTE: temperature set to 0 for reproducibility
            temperature=0.0,
            max_tokens=1000,
            reasoning_effort=ReasoningEfforts.High.value,
            seed=42,
            usage_tag="research"
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
        """Conduct deep iterative research"""
        logger.debug(f"[DeepResearch] deep_research called with query: {query[:100]}..., breadth: {breadth}, depth: {depth}")
        
        if learnings is None:
            learnings = []
        if citations is None:
            citations = {}
        if visited_urls is None:
            visited_urls = set()

        progress = ResearchProgress(depth, breadth)

        if on_progress:
            on_progress(progress)

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

        logger.debug(f"[DeepResearch] Created research level node: {current_node_id}")

        # Generate search queries
        logger.debug(f"[DeepResearch] Generating SERP queries...")
        serp_queries = await self.generate_serp_queries(query, num_queries=breadth)
        progress.total_queries = len(serp_queries)
        logger.debug(f"[DeepResearch] Generated {len(serp_queries)} SERP queries")
        if len(serp_queries) == 0:
            logger.error(f"[DeepResearch] No SERP queries generated, returning empty results")
            return {
                'learnings': [],
                'visited_urls': [],
                'citations': {},
            }

        all_learnings = learnings.copy()
        all_citations = citations.copy()
        all_visited_urls = visited_urls.copy()
        all_context = []
        all_sources = []

        # Process queries with concurrency limit
        semaphore = asyncio.Semaphore(self.concurrency_limit)
        concurrent_group_id = id(semaphore)  # Use semaphore id as group identifier

        logger.debug(f"[DeepResearch] Starting concurrent processing of {len(serp_queries)} queries")

        async def process_query(serp_query: Dict[str, str]) -> Optional[Dict[str, Any]]:
            async with semaphore:
                researcher = None
                query_node_id = None
                try:
                    logger.debug(f"[DeepResearch] Starting process_query for: {serp_query['query']}")
                    progress.current_query = serp_query['query']
                    if on_progress:
                        on_progress(progress)

                    # Log the start of processing this query
                    query_node_id = self.logger.add_node(
                        depth=depth,
                        breadth=breadth,
                        query=serp_query['query'],
                        parent_id=current_node_id,
                        research_goal=serp_query['researchGoal'],
                        status=TaskState.STARTED.value,
                        concurrent_group=concurrent_group_id,  # Add concurrent group tracking
                        operation="research",
                        start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )

                    logger.debug(f"[DeepResearch] Created query node: {query_node_id}")

                    # Initialize researcher for this query with enhanced logging if enabled
                    researcher = GPTResearcher(
                        query=serp_query['query'],
                        report_type=ReportType.ResearchReport.value,
                        report_source=self.config.report_source,
                        vector_store=load_vector_db("vector_db") if self.config.report_source == ReportSource.LangChainVectorStore.value else None,
                        tone=self.tone,
                        websocket=self.websocket,
                        config_path=self.config_path,
                        headers=self.headers,
                        log_handler=self.logger,  # Pass the logger as log_handler
                        enable_enhanced_logging=self.enable_enhanced_logging,  # Pass enhanced logging flag
                        parent_node_id=query_node_id,  # Pass the current node id to the researcher
                        verbose=self.verbose,  # Pass the verbose flag
                        root_query=self.query  # Pass the original root query
                    )

                    logger.debug(f"[DeepResearch] Initialized GPTResearcher, starting conduct_research")

                    # Conduct research
                    await researcher.conduct_research()

                    logger.debug(f"[DeepResearch] conduct_research completed")

                    # Get results
                    context = researcher.context
                    visited = set(researcher.visited_urls)
                    sources = researcher.research_sources

                    logger.debug(f"[DeepResearch] Got results - context length: {len(str(context))}, visited URLs: {len(visited)}")

                    # Process results
                    results = await self.process_serp_result(
                        query=serp_query['query'],
                        context=context
                    )

                    logger.debug(f"[DeepResearch] Processed results - learnings: {len(results['learnings'])}")

                    # Update progress
                    progress.completed_queries += 1
                    progress.current_breadth += 1
                    if on_progress:
                        on_progress(progress)
                    
                    # Log the completion of this query
                    self.logger.update_node(
                        node_id=query_node_id,
                        status=TaskState.COMPLETED.value,
                        results={
                            'learnings': results['learnings'],
                            'citations': results['citations'],
                            'researchGoal': serp_query['researchGoal']
                        },
                        visited_urls=visited,
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )

                    logger.debug(f"[DeepResearch] Successfully completed process_query for: {serp_query['query']}")

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

                except asyncio.CancelledError:
                    logger.info(f"[DeepResearch] process_query cancelled for: {serp_query['query']}")
                    # Best-effort salvage of intermediate data from researcher before propagating cancellation
                    try:
                        await self._salvage_researcher_data(
                            researcher,
                            query_node_id=query_node_id,
                            mark_status="cancelled"
                        )
                    except Exception as salvage_err:
                        logger.debug(f"[DeepResearch] Salvage on cancellation failed: {salvage_err}")
                    # Propagate cancellation so the outer timeout can stop promptly
                    raise
                except Exception as e:
                    logger.error(f"[DeepResearch] Error processing query '{serp_query['query']}': {str(e)}")
                    logger.error(f"[DeepResearch] Exception traceback: {traceback.format_exc()}")
                    # Log the error
                    try:
                        if query_node_id is not None:
                            self.logger.update_node(
                                node_id=query_node_id,
                                status=TaskState.FAILED.value,
                                results={"error": str(e)}
                            )
                    except Exception as log_error:
                        logger.error(f"[DeepResearch] Failed to log error: {log_error}")
                    # Best-effort salvage of any partial data from researcher
                    try:
                        await self._salvage_researcher_data(
                            researcher,
                            query_node_id=query_node_id
                        )
                    except Exception as salvage_err:
                        logger.debug(f"[DeepResearch] Salvage on cancellation failed: {salvage_err}")
                    return None

        # Process queries concurrently with limit
        tasks = [process_query(query) for query in serp_queries]
        logger.debug(f"[DeepResearch] Created {len(tasks)} tasks, starting asyncio.gather")
        results = await asyncio.gather(*tasks)
        logger.debug(f"[DeepResearch] asyncio.gather completed, got {len(results)} results")
        results = [r for r in results if r is not None]  # Filter out failed queries
        logger.debug(f"[DeepResearch] After filtering None results: {len(results)} successful results")

        # Update breadth progress based on successful queries
        progress.current_breadth = len(results)
        if on_progress:
            on_progress(progress)

        logger.debug(f"[DeepResearch] Collecting results from {len(results)} successful queries")

        # Collect all results
        for result in results:
            node_id = result['node_id']
            all_learnings.extend(result['learnings'])
            all_visited_urls.update(set(result['visited_urls']))
            all_citations.update(result['citations'])
            if result['context']:
                all_context.append(result['context'])
            if result['sources']:
                all_sources.extend(result['sources'])

            logger.debug(f"[DeepResearch] Collected result from node {node_id}: {len(result['learnings'])} learnings, {len(result['visited_urls'])} URLs")

            # Continue deeper if needed
            if depth < self.config.max_depth: # max_depth is the maximum depth of the research
                logger.debug(f"[DeepResearch] Starting deeper research for node {node_id}")
                new_breadth = max(2, breadth // 2)
                new_depth = depth + 1
                progress.current_depth += 1

                # Create next query from research goal and follow-up questions
                next_query = f"""
                Previous research goal: {result['researchGoal']}
                Follow-up questions: {' '.join(result['followUpQuestions'])}
                """

                # Recursive research
                deeper_results = await self.deep_research(
                    query=next_query,
                    breadth=new_breadth,
                    depth=new_depth,
                    learnings=all_learnings,
                    citations=all_citations,
                    visited_urls=all_visited_urls,
                    on_progress=on_progress,
                    parent_node_id=node_id  # Pass the research node id as the parent
                )

                all_learnings = list(set(all_learnings + deeper_results['learnings']))
                all_visited_urls.update(deeper_results['visited_urls'])
                all_citations.update(deeper_results['citations'])
                if deeper_results.get('context'):
                    all_context.extend(deeper_results['context'])
                if deeper_results.get('sources'):
                    all_sources.extend(deeper_results['sources'])

        logger.debug(f"[DeepResearch] Final collection: {len(all_learnings)} learnings, {len(all_visited_urls)} URLs, {len(all_context)} context items")

        # Update class tracking
        self.context.extend(all_context)
        self.research_sources.extend(all_sources)
        # Also aggregate learnings/visited/citations for timeout salvage in run()
        try:
            async with self._partial_lock:
                if all_learnings:
                    self.learnings.extend(all_learnings)
                if all_visited_urls:
                    self.visited_urls.update(all_visited_urls)
                if all_citations:
                    self.citations.update(all_citations)
        except Exception:
            pass

        # Trim context to stay within word limits
        trimmed_context = trim_context_to_word_limit(all_context, max_words=self.max_context_words)
        logger.info(f"Trimmed context from {len(all_context)} items to {len(trimmed_context)} items to stay within word limit")

        # Log the completion of this research level
        self.logger.update_node(
            node_id=current_node_id,
            status=TaskState.COMPLETED.value,
            results={
                'learnings': list(set(all_learnings)),
                'visited_urls': list(all_visited_urls),
                'citations': all_citations
            },
            end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        logger.debug(f"[DeepResearch] deep_research completed, returning results")

        return {
            'learnings': list(set(all_learnings)),
            'visited_urls': list(all_visited_urls),
            'citations': all_citations,
            'context': all_context,
            'sources': all_sources
        }

    async def run(self, on_progress=None) -> str:
        """Run the deep research process and generate final report"""
        logger.debug(f"[DeepResearch] run() started with query: {self.query}")
        start_time = time.time()
        
        # Log initial global costs
        from gpt_researcher.utils.token_tracker import TokenTracker
        initial_costs = TokenTracker.get_totals().get("cost", 0.0)

        # Run deep research with optional hard timeout
        results: Dict[str, Any] = {}
        deep_task = asyncio.create_task(self.deep_research(
            query=self.query,
            breadth=self.breadth,
            depth=self.depth,
            on_progress=on_progress
        ))

        try:
            if self.time_limit_seconds and self.time_limit_seconds > 0:
                logger.info(f"[DeepResearch] Enforcing hard time limit: {self.time_limit_seconds} seconds")
                results = await asyncio.wait_for(deep_task, timeout=self.time_limit_seconds)
            else:
                results = await deep_task
        except asyncio.TimeoutError:
            logger.warning("[DeepResearch] Time limit reached. Cancelling ongoing research and generating partial report.")
            deep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await deep_task
            # Synthesize results from class-level accumulators
            async with self._partial_lock:
                results = {
                    'learnings': list(set(self.learnings)),
                    'visited_urls': list(self.visited_urls),
                    'citations': dict(self.citations),
                    'context': list(self.context),
                    'sources': list(self.research_sources),
                }
        except asyncio.CancelledError:
            # Propagate cancellation as partial completion
            logger.warning("[DeepResearch] Research cancelled. Generating partial report.")
            async with self._partial_lock:
                results = {
                    'learnings': list(set(self.learnings)),
                    'visited_urls': list(self.visited_urls),
                    'citations': dict(self.citations),
                    'context': list(self.context),
                    'sources': list(self.research_sources),
                }

        logger.debug(f"[DeepResearch] deep_research completed, results: {len(results.get('visited_urls', []))} URLs, {len(results.get('learnings', []))} learnings")

        # Get global costs after deep research
        research_costs = TokenTracker.get_totals().get("cost", 0.0) - initial_costs

        # Log research costs if we have a log handler
        if self.researcher.log_handler:
            await self.researcher._log_event("research", step="deep_research_costs", details={
                "research_costs": research_costs,
                "total_costs": TokenTracker.get_totals().get("cost", 0.0)
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
        # if results.get('context'):
        #     context_with_citations.extend(results['context'])

        # Trim final context to word limit
        # context_with_citations = trim_context_to_word_limit(context_with_citations, max_words=self.max_context_words)
        
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
        
        # Save token usage to file if logs_dir is available
        try:
            # Use global token tracker
            per_model = TokenTracker.get_per_model_totals()
            per_usage = TokenTracker.get_per_usage_totals()
            totals = TokenTracker.get_totals()
            token_counts = per_model
            summary_lines = [
                "Token Usage Summary (Global):",
                f"  Total input tokens:  {totals.get('input_tokens', 0):,}",
                f"  Total output tokens: {totals.get('output_tokens', 0):,}",
                f"  Total tokens:        {totals.get('input_tokens', 0) + totals.get('output_tokens', 0):,}",
                f"  Total cost:          ${totals.get('cost', 0.0):.4f}",
                "",
                "Per-Model Usage:",
            ]
            for model_name, stats in per_model.items():
                input_t = int(stats.get("input", 0))
                output_t = int(stats.get("output", 0))
                cost_v = float(stats.get("cost", 0.0))
                total_t = input_t + output_t
                summary_lines.append(f"  {model_name}:")
                summary_lines.append(f"    Input tokens:  {input_t:,}")
                summary_lines.append(f"    Output tokens: {output_t:,}")
                summary_lines.append(f"    Total tokens:  {total_t:,}")
                summary_lines.append(f"    Cost:          ${cost_v:.4f}")
            summary_lines.append("")
            summary_lines.append("Per-Usage Breakdown:")
            for usage_tag, stats in per_usage.items():
                input_t = int(stats.get("input", 0))
                output_t = int(stats.get("output", 0))
                cost_v = float(stats.get("cost", 0.0))
                total_t = input_t + output_t
                summary_lines.append(f"  {usage_tag}:")
                summary_lines.append(f"    Input tokens:  {input_t:,}")
                summary_lines.append(f"    Output tokens: {output_t:,}")
                summary_lines.append(f"    Total tokens:  {total_t:,}")
                summary_lines.append(f"    Cost:          ${cost_v:.4f}")
            token_summary = "\n".join(summary_lines)
            
            # Save to logs directory
            import json
            import os
            token_usage_path = os.path.join(self.logger.logs_dir, "token_usage.json")
            with open(token_usage_path, "w") as f:
                json.dump({
                    "token_counts_by_model": token_counts,
                    "token_counts_by_usage": per_usage,
                    "total_cost": totals.get("cost", 0.0),
                    "execution_time": execution_time.total_seconds(),
                    "summary": token_summary
                }, f, indent=2)
            
            logger.info(f"Token usage saved to: {token_usage_path}")
            
            # Also save a human-readable summary
            summary_path = os.path.join(self.logger.logs_dir, "token_usage_summary.txt")
            with open(summary_path, "w") as f:
                f.write(f"Research Query: {self.query}\n")
                f.write(f"Execution Time: {execution_time}\n")
                f.write(f"Total Cost: ${totals.get('cost', 0.0):.4f}\n\n")
                f.write(token_summary)
            
        except Exception as e:
            logger.warning(f"Failed to save token usage: {e}")


        return report
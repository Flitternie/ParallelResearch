from typing import List, Dict, Any, Optional, Set
from fastapi import WebSocket
import asyncio
import logging
import time
from datetime import datetime, timedelta
import traceback
import re
from pydantic import BaseModel

# NOTE: This is a modified version of the GPTResearcher class
from modified_agent import GPTResearcher
from modified_researcher import get_vector_store_results
from gpt_researcher.llm_provider.generic.base import ReasoningEfforts
from gpt_researcher.utils.llm import create_chat_completion
from gpt_researcher.utils.enum import ReportType, ReportSource, Tone
from gpt_researcher.actions.query_processing import get_search_results

from build_vector_db import load_vector_db
from utils import Config, ResearchLogger, ResearchProgress, trim_context_to_word_limit

# NOTE: This is a modified version from gpt_researcher.skills.deep_research
logger = logging.getLogger(__name__)


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


        self.researcher = GPTResearcher(
            query=self.query,
            report_type=ReportType.DeepResearch.value,
            report_source=self.config.report_source,
            vector_store=load_vector_db("vector_db") if self.config.report_source == ReportSource.LangChainVectorStore.value else None,
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
            temperature=0.0,
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
            temperature=0.0,
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
            temperature=0.0,
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
            status="started",
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
                        status="started",
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
                        parent_node_id=query_node_id  # Pass the current node id to the researcher
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

                all_learnings = deeper_results['learnings']
                all_visited_urls = set(deeper_results['visited_urls'])
                all_citations.update(deeper_results['citations'])
                if deeper_results.get('context'):
                    all_context.extend(deeper_results['context'])
                if deeper_results.get('sources'):
                    all_sources.extend(deeper_results['sources'])

        logger.debug(f"[DeepResearch] Final collection: {len(all_learnings)} learnings, {len(all_visited_urls)} URLs, {len(all_context)} context items")

        # Update class tracking
        self.context.extend(all_context)
        self.research_sources.extend(all_sources)

        # Trim context to stay within word limits
        trimmed_context = trim_context_to_word_limit(all_context)
        logger.info(f"Trimmed context from {len(all_context)} items to {len(trimmed_context)} items to stay within word limit")

        # Log the completion of this research level
        self.logger.update_node(
            node_id=current_node_id,
            status="completed",
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
            'context': trimmed_context,
            'sources': all_sources
        }

    async def run(self, on_progress=None) -> str:
        """Run the deep research process and generate final report"""
        logger.debug(f"[DeepResearch] run() started with query: {self.query}")
        start_time = time.time()
        
        # Log initial costs
        initial_costs = self.researcher.get_costs()

        # # Get initial feedback
        # logger.debug(f"[DeepResearch] Generating feedback questions...")
        # follow_up_questions = await self.generate_feedback(self.query)
        # logger.debug(f"[DeepResearch] Generated {len(follow_up_questions)} feedback questions")

        # # Collect answers (this would normally come from user interaction)
        # answers = ["Automatically proceeding with research"] * len(follow_up_questions)

        # # Combine query and Q&A
        # follow_up_qa = [f"Q: {q}\nA: {a}" for q, a in zip(follow_up_questions, answers)]
        # combined_query = f"""
        # Initial Query: {self.query}\nFollow - up Questions and Answers:\n
        # """ + "\n".join(follow_up_qa)

        # logger.debug(f"[DeepResearch] Starting deep_research with combined query...")

        # Run deep research
        results = await self.deep_research(
            query=self.query,
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
from typing import Any, Optional, List
import json
import logging
import asyncio
from datetime import datetime

from gpt_researcher.config import Config
from gpt_researcher.memory import Memory
from gpt_researcher.utils.enum import ReportSource, ReportType, Tone
from gpt_researcher.llm_provider import GenericLLMProvider
from gpt_researcher.prompts import get_prompt_family
from gpt_researcher.vector_store import VectorStoreWrapper

# Research skills
# NOTE: This is a modified version of the ResearchConductor class
# from gpt_researcher.skills.researcher import ResearchConductor
from modified_researcher import ResearchConductor
from gpt_researcher.skills.writer import ReportGenerator
from gpt_researcher.skills.context_manager import ContextManager
from gpt_researcher.skills.browser import BrowserManager
from gpt_researcher.skills.curator import SourceCurator
from gpt_researcher.skills.deep_research import DeepResearchSkill

from gpt_researcher.actions import (
    add_references,
    extract_headers,
    extract_sections,
    table_of_contents,
    get_search_results,
    get_retrievers,
    choose_agent
)

class ResearchNode:
    """Class to represent a node in the research process"""
    def __init__(
        self,
        node_id: int,
        depth: int,
        breadth: int,
        query: str,
        parent_id: Optional[int] = None,
        research_goal: Optional[str] = None,
        status: str = "started",
        concurrent_group: Optional[int] = None,
        operation: Optional[str] = None,
        start_time: Optional[str] = None
    ):
        self.id = node_id
        self.depth = depth
        self.breadth = breadth
        self.query = query
        self.parent_id = parent_id
        self.research_goal = research_goal
        self.status = status
        self.timestamp = datetime.now().isoformat()
        self.results = None
        self.concurrent_group = concurrent_group
        self.operation = operation
        self.start_time = start_time or datetime.now().isoformat()
        self.end_time = None
        self.visited_urls = None
        self.duration = None

    def to_dict(self) -> dict:
        """Convert node to dictionary format compatible with ResearchLogger"""
        node_dict = {
            "id": self.id,
            "depth": self.depth,
            "breadth": self.breadth,
            "query": self.query,
            "parent_id": self.parent_id,
            "research_goal": self.research_goal,
            "status": self.status,
            "timestamp": self.timestamp,
            "results": self.results,
            "concurrent_group": self.concurrent_group,
            "operation": self.operation,
            "start_time": self.start_time
        }
        if self.end_time:
            node_dict["end_time"] = self.end_time
        if self.visited_urls is not None:
            node_dict["visited_urls"] = list(self.visited_urls)
        if self.duration:
            node_dict["duration"] = self.duration
        return node_dict

class GPTResearcher:
    def __init__(
        self,
        query: str,
        report_type: str = ReportType.ResearchReport.value,
        report_format: str = "markdown",
        report_source: str = ReportSource.Web.value,
        tone: Tone = Tone.Objective,
        source_urls: list[str] | None = None,
        document_urls: list[str] | None = None,
        complement_source_urls: bool = False,
        query_domains: list[str] | None = None,
        documents=None,
        vector_store=None,
        vector_store_filter=None,
        config_path=None,
        websocket=None,
        agent=None,
        role=None,
        parent_query: str = "",
        subtopics: list | None = None,
        visited_urls: set | None = None,
        verbose: bool = True,
        context=None,
        headers: dict | None = None,
        max_subtopics: int = 5,
        log_handler=None,
        prompt_family: str | None = None,
        enable_enhanced_logging: bool = False,
        parent_node_id: Optional[int] = None,
        **kwargs
    ):
        # Initialize all the same parameters as GPTResearcher
        self.kwargs = kwargs
        self.query = query
        self.report_type = report_type
        self.cfg = Config(config_path)
        self.cfg.set_verbose(verbose)
        self.llm = GenericLLMProvider(self.cfg)
        self.report_source = report_source if report_source else getattr(self.cfg, 'report_source', None)
        self.report_format = report_format
        self.max_subtopics = max_subtopics
        self.tone = tone if isinstance(tone, Tone) else Tone.Objective
        self.source_urls = source_urls
        self.document_urls = document_urls
        self.complement_source_urls = complement_source_urls
        self.query_domains = query_domains or []
        self.research_sources = []
        self.research_images = []
        self.documents = documents
        self.vector_store = VectorStoreWrapper(vector_store) if vector_store else None
        self.vector_store_filter = vector_store_filter
        self.websocket = websocket
        self.agent = agent
        self.role = role
        self.parent_query = parent_query
        self.subtopics = subtopics or []
        self.visited_urls = visited_urls or set()
        self.verbose = verbose
        self.headers = headers or {}
        self.research_costs = 0.0
        self.retrievers = get_retrievers(self.headers, self.cfg)
        self.memory = Memory(
            self.cfg.embedding_provider, self.cfg.embedding_model, **self.cfg.embedding_kwargs
        )
        self.log_handler = log_handler
        self.prompt_family = get_prompt_family(prompt_family or self.cfg.prompt_family, self.cfg)

        # Real-time context tracking
        self._context_lock = asyncio.Lock()
        self._current_context = []
        self.context = context or []
        self._context_size = 10
        self._last_update = None

        # Initialize components
        self.research_conductor = ResearchConductor(self, enhanced_logger=self.log_handler)
        self.report_generator = ReportGenerator(self)
        self.context_manager = ContextManager(self)
        self.scraper_manager = BrowserManager(self)
        self.source_curator = SourceCurator(self)
        self.deep_researcher = None
        if report_type == ReportType.DeepResearch.value:
            self.deep_researcher = DeepResearchSkill(self)

        # Enhanced logging setup - only if enabled
        self.enable_enhanced_logging = enable_enhanced_logging
        self.parent_node_id = parent_node_id
        self.current_node_id = None
        self.sub_node_counter = 0

    def _get_next_node_id(self) -> str:
        """Generate next hierarchical node ID"""
        if self.parent_node_id is not None:
            self.sub_node_counter += 1
            return f"{self.parent_node_id}.{self.sub_node_counter}"
        return str(self.sub_node_counter)

    async def _log_event(self, event_type: str, **kwargs):
        """Enhanced logging method that creates and updates nodes directly in logger"""
        if self.log_handler:
            try:
                # Handle research events with direct logger updates if enhanced logging is enabled
                if self.enable_enhanced_logging:
                    step = kwargs.get('step', '')
                    action = kwargs.get('action', '')
                    details = kwargs.get('details', {})

                    if action == "choose_agent":
                        self.current_node_id = self.log_handler.add_node(
                            depth=0,
                            breadth=1,
                            query=self.query,
                            parent_id=self.parent_node_id,
                            status="started",
                            operation="agent_selection",
                            start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            node_id=self._get_next_node_id()
                        )
                    elif action == "agent_selected":
                        self.log_handler.update_node(
                            node_id=self.current_node_id,
                            status="completed",
                            results={"agent": details.get('agent', ''), "role": details.get('role', '')},
                            end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        )
                    
                    if step == "conducting_research":
                        # Create node for research execution
                        self.current_node_id = self.log_handler.add_node(
                            depth=details.get('depth', 0),
                            breadth=1,
                            query=self.query,
                            parent_id=self.current_node_id,
                            status="started",
                            operation="research_execution",
                            start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            research_goal=f"Agent: {details.get('agent', '')}, Role: {details.get('role', '')}",
                            node_id=self._get_next_node_id()
                        )

                    elif step in ["research_completed", "deep_research_complete"]:
                        if self.current_node_id is not None:
                            # Update the current node with completion details
                            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            self.log_handler.update_node(
                                node_id=self.current_node_id,
                                status="completed",
                                results=details,
                                visited_urls=self.visited_urls,
                                end_time=end_time
                            )

                    elif step == "writing_report":
                        # Create node for report writing
                        self.current_node_id = self.log_handler.add_node(
                            depth=0,
                            breadth=1,
                            query="Writing research report",
                            parent_id=self.current_node_id,
                            status="started",
                            operation="report_writing",
                            start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            node_id=self._get_next_node_id()
                        )

                    elif step == "report_completed":
                        if self.current_node_id is not None:
                            # Update report node with completion
                            self.log_handler.update_node(
                                node_id=self.current_node_id,
                                status="completed",
                                results={"report_length": details.get("report_length", 0)},
                                end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            )

                    elif step == "cost_update":
                        # Add cost information to current node
                        if self.current_node_id is not None:
                            current_results = details
                            self.log_handler.update_node(
                                node_id=self.current_node_id,
                                status="completed",
                                results=current_results
                            )

                
                # NOTE: Original logging behavior - always execute regardless of enhanced logging
                # if event_type == "tool":
                #     await self.log_handler.on_tool_start(kwargs.get('tool_name', ''), **kwargs)
                # elif event_type == "action":
                #     await self.log_handler.on_agent_action(kwargs.get('action', ''), **kwargs)
                # elif event_type == "research":
                #     await self.log_handler.on_research_step(kwargs.get('step', ''), kwargs.get('details', {}))

                # Add direct logging as backup - always execute
                
                research_logger = logging.getLogger('research')
                research_logger.info(f"{event_type}: {json.dumps(kwargs, default=str)}")

            except Exception as e:
                logging.getLogger('research').error(f"Error in _log_event: {e}", exc_info=True)

    async def conduct_research(self, on_progress=None):
        logging.getLogger('research').debug(f"[GPTResearcher] conduct_research called with query: {self.query}")
        await self._log_event("research", step="start", details={
            "query": self.query,
            "report_type": self.report_type,
            "agent": self.agent,
            "role": self.role
        })

        if self.report_type == ReportType.DeepResearch.value and self.deep_researcher:
            logging.getLogger('research').debug(f"[GPTResearcher] DeepResearch branch taken")
            return await self._handle_deep_research(on_progress)

        if not (self.agent and self.role):
            logging.getLogger('research').debug(f"[GPTResearcher] Choosing agent/role")
            await self._log_event("action", action="choose_agent",details={
                "query": self.query,
                "cfg": self.cfg
            })
            self.agent, self.role = await choose_agent(
                query=self.query,
                cfg=self.cfg,
                parent_query=self.parent_query,
                cost_callback=self.add_costs,
                headers=self.headers,
                prompt_family=self.prompt_family,
                **self.kwargs
            )
            await self._log_event("action", action="agent_selected", details={
                "agent": self.agent,
                "role": self.role
            })

        await self._log_event("research", step="conducting_research", details={
            "agent": self.agent,
            "role": self.role
        })
        
        logging.getLogger('research').debug(f"[GPTResearcher] Starting research_conductor.conduct_research")
        self.context = await self.research_conductor.conduct_research(parent_node_id=self.current_node_id)
        logging.getLogger('research').debug(f"[GPTResearcher] research_conductor.conduct_research completed, context length: {len(str(self.context))}")

        await self._log_event("research", step="research_completed", details={
            "context": self.context
        })
        return self.context

    # NOTE: The following methods are the same as in the original GPTResearcher class
    async def _handle_deep_research(self, on_progress=None):
        """Handle deep research execution and logging."""
        # Log deep research configuration
        await self._log_event("research", step="deep_research_initialize", details={
            "type": "deep_research",
            "breadth": self.deep_researcher.breadth,
            "depth": self.deep_researcher.depth,
            "concurrency": self.deep_researcher.concurrency_limit
        })

        # Log deep research start
        await self._log_event("research", step="deep_research_start", details={
            "query": self.query,
            "breadth": self.deep_researcher.breadth,
            "depth": self.deep_researcher.depth,
            "concurrency": self.deep_researcher.concurrency_limit
        })

        # Run deep research and get context
        self.context = await self.deep_researcher.run(on_progress=on_progress)

        # Get total research costs
        total_costs = self.get_costs()

        # Log deep research completion with costs
        await self._log_event("research", step="deep_research_complete", details={
            "context_length": len(self.context),
            "visited_urls": len(self.visited_urls),
            "total_costs": total_costs
        })

        # Log final cost update
        await self._log_event("research", step="cost_update", details={
            "cost": total_costs,
            "total_cost": total_costs,
            "research_type": "deep_research"
        })

        # Return the research context
        return self.context

    async def write_report(self, existing_headers: list = [], relevant_written_contents: list = [], ext_context=None, custom_prompt="") -> str:
        await self._log_event("research", step="writing_report", details={
            "existing_headers": existing_headers,
            "context_source": "external" if ext_context else "internal"
        })

        report = await self.report_generator.write_report(
            existing_headers=existing_headers,
            relevant_written_contents=relevant_written_contents,
            ext_context=ext_context or self.context,
            custom_prompt=custom_prompt
        )

        await self._log_event("research", step="report_completed", details={
            "report_length": len(report)
        })
        return report

    async def write_report_conclusion(self, report_body: str) -> str:
        await self._log_event("research", step="writing_conclusion")
        conclusion = await self.report_generator.write_report_conclusion(report_body)
        await self._log_event("research", step="conclusion_completed")
        return conclusion

    async def write_introduction(self):
        await self._log_event("research", step="writing_introduction")
        intro = await self.report_generator.write_introduction()
        await self._log_event("research", step="introduction_completed")
        return intro

    async def quick_search(self, query: str, query_domains: list[str] = None) -> list[Any]:
        return await get_search_results(query, self.retrievers[0], query_domains=query_domains)

    async def get_subtopics(self):
        return await self.report_generator.get_subtopics()

    async def get_draft_section_titles(self, current_subtopic: str):
        return await self.report_generator.get_draft_section_titles(current_subtopic)

    async def get_similar_written_contents_by_draft_section_titles(
        self,
        current_subtopic: str,
        draft_section_titles: list[str],
        written_contents: list[dict],
        max_results: int = 10
    ) -> list[str]:
        return await self.context_manager.get_similar_written_contents_by_draft_section_titles(
            current_subtopic,
            draft_section_titles,
            written_contents,
            max_results
        )

    # Utility methods
    def get_research_images(self, top_k=10) -> list[dict[str, Any]]:
        return self.research_images[:top_k]

    def add_research_images(self, images: list[dict[str, Any]]) -> None:
        self.research_images.extend(images)

    def get_research_sources(self) -> list[dict[str, Any]]:
        return self.research_sources

    def add_research_sources(self, sources: list[dict[str, Any]]) -> None:
        self.research_sources.extend(sources)

    def add_references(self, report_markdown: str, visited_urls: set) -> str:
        return add_references(report_markdown, visited_urls)

    def extract_headers(self, markdown_text: str) -> list[dict]:
        return extract_headers(markdown_text)

    def extract_sections(self, markdown_text: str) -> list[dict]:
        return extract_sections(markdown_text)

    def table_of_contents(self, markdown_text: str) -> str:
        return table_of_contents(markdown_text)

    def get_source_urls(self) -> list:
        return list(self.visited_urls)

    def get_research_context(self) -> list:
        return self.context

    def get_costs(self) -> float:
        return self.research_costs

    def set_verbose(self, verbose: bool):
        self.verbose = verbose

    def add_costs(self, cost: float) -> None:
        if not isinstance(cost, (float, int)):
            raise ValueError("Cost must be an integer or float")
        self.research_costs += cost
        if self.log_handler:
            # Schedule the async log event without waiting
            asyncio.create_task(self._log_event("research", step="cost_update", details={
                "cost": cost,
                "total_cost": self.research_costs
            }))
            
    async def get_current_context(self) -> str:
        """Get current research context"""
        async with self._context_lock:
            return "\n".join(self._current_context) if self._current_context else ""
            
    async def get_current_learnings(self) -> List[str]:
        """Get current research learnings"""
        async with self._context_lock:
            return self._extract_learnings_from_context(self._current_context)
            
    async def _update_context(self, new_content: str):
        """Update research context with new content"""
        async with self._context_lock:
            if new_content:
                self._current_context.append(new_content)
                self._last_update = datetime.now()
                # Keep only recent context
                if len(self._current_context) > self._context_size:
                    self._current_context = self._current_context[-self._context_size:]
                    
    def _extract_learnings_from_context(self, context_list: List[str]) -> List[str]:
        """Extract learnings from context"""
        learnings = []
        try:
            # Process each context chunk
            for context in context_list:
                if not context:
                    continue
                    
                # Split into sentences and filter for substantial content
                sentences = context.replace('\n', ' ').split('. ')
                chunk_learnings = [
                    sentence.strip() + '.' for sentence in sentences 
                    if len(sentence.strip()) > 30 and not sentence.strip().startswith('http')
                ]
                learnings.extend(chunk_learnings[:5])  # Take top 5 from each chunk
                
            return learnings[:15]  # Return top 15 overall learnings
            
        except Exception as e:
            logging.getLogger('research').warning(f"Error extracting learnings: {e}")
            return []

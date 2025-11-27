import asyncio
import random
import logging
import os
import time
from datetime import datetime

from gpt_researcher.actions.utils import stream_output
from gpt_researcher.actions.query_processing import plan_research_outline, get_search_results
from gpt_researcher.document import DocumentLoader, OnlineDocumentLoader, LangChainDocumentLoader
from gpt_researcher.utils.enum import ReportSource
from gpt_researcher.utils.logging_config import get_json_handler
from gpt_researcher.utils.latency_tracker import LatencyTracker

from utils import truncate, clean_document_content


class ResearchConductor:
    """Manages and coordinates the research process."""

    def __init__(self, researcher, enhanced_logger=None):
        self.researcher = researcher
        self.logger = logging.getLogger('research')
        self.json_handler = get_json_handler()
        self.enhanced_logger = enhanced_logger
        self.parent_node_id = None
        self.current_node_id = None
        self.sub_node_counter = 0

    def _get_next_node_id(self) -> str:
        """Generate next hierarchical node ID"""
        if self.parent_node_id is not None:
            self.sub_node_counter += 1
            return f"{self.parent_node_id}.{self.sub_node_counter}"
        return str(self.sub_node_counter)

    async def plan_research(self, query, query_domains=None):
        self.logger.info(f"Planning research for query: {query}")
        self.logger.debug(f"[ResearchConductor] plan_research called with query: {query}")
        
        if query_domains:
            self.logger.info(f"Query domains: {query_domains}")
        
        # Create planning node
        if self.enhanced_logger:
            self.current_node_id = self.enhanced_logger.add_node(
                depth=0,
                breadth=1,
                query=query,
                parent_id=self.current_node_id,
                status="started",
                operation="search_planning",
                start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                node_id=self._get_next_node_id()
            )

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "planning_research",
                f"🌐 Browsing the web to learn more about the task: {query}...",
                self.researcher.websocket,
            )

        self.logger.debug(f"[ResearchConductor] Getting initial search results for planning")
        # NOTE: Use vector store if report_source is LangChainVectorStore for initial planning
        if self.researcher.report_source == ReportSource.LangChainVectorStore.value:
            search_results = await get_vector_store_results(query, self.researcher.vector_store, self.researcher.vector_store_filter)
            for result in search_results:
                if result.get("href") not in self.researcher.visited_urls:
                    self.researcher.visited_urls.add(result.get("href"))
        else:
            search_results = await get_search_results(query, self.researcher.retrievers[0], query_domains)
        try:
            self.logger.info(f"Initial search results obtained: {len(search_results)} results")
            self.logger.debug(f"[ResearchConductor] Got {len(search_results)} initial search results")
        except Exception as e:
            self.logger.error(f"[ResearchConductor] Error obtaining search results for query {query}: {e}")
            search_results = []

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "planning_research",
                f"🤔 Planning the research strategy and subtasks...",
                self.researcher.websocket,
            )

        self.logger.debug(f"[ResearchConductor] Planning research outline")
        outline = await plan_research_outline(
            query=query,
            search_results=search_results,
            agent_role_prompt=self.researcher.role,
            cfg=self.researcher.cfg,
            parent_query=self.researcher.parent_query,
            report_type=self.researcher.report_type,
            cost_callback=self.researcher.add_costs,
            **self.researcher.kwargs
        )
        self.logger.info(f"Research outline planned: {outline}")
        self.logger.debug(f"[ResearchConductor] Planned research outline: {outline}")

        # Update planning node with results
        if self.enhanced_logger:
            self.enhanced_logger.update_node(
                node_id=self.current_node_id,
                status="completed",
                results={
                    "agent_role": self.researcher.role,
                    "search_results": search_results,
                    "subqueries": outline, 
                    },
                end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

        return outline

    async def conduct_research(self, parent_node_id=None):
        """Runs the GPT Researcher to conduct research"""
        self.logger.debug(f"[ResearchConductor] conduct_research called with query: {self.researcher.query}")
        
        if self.json_handler:
            self.json_handler.update_content("query", self.researcher.query)
        
        self.logger.info(f"Starting research for query: {self.researcher.query}")
        self.parent_node_id = parent_node_id
        self.current_node_id = self.parent_node_id
        
        # Reset visited_urls and source_urls at the start of each research task
        self.researcher.visited_urls.clear()
        research_data = []

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "starting_research",
                f"🔍 Starting the research task for '{self.researcher.query}'...",
                self.researcher.websocket,
            )
            await stream_output(
                "logs",
                "agent_generated",
                self.researcher.agent,
                self.researcher.websocket
            )

        # Research for relevant sources based on source types
        if self.researcher.source_urls:
            self.logger.info("Using provided source URLs")
            research_data = await self._get_context_by_urls(self.researcher.source_urls)
            if research_data and len(research_data) == 0 and self.researcher.verbose:
                await stream_output(
                    "logs",
                    "answering_from_memory",
                    f"🧐 I was unable to find relevant context in the provided sources...",
                    self.researcher.websocket,
                )
            if self.researcher.complement_source_urls:
                self.logger.info("Complementing with web search")
                additional_research = await self._get_context_by_web_search(self.researcher.query, [], self.researcher.query_domains)
                research_data += ' '.join(additional_research)

        elif self.researcher.report_source == ReportSource.Web.value:
            self.logger.info("Using web search")
            self.logger.debug(f"[ResearchConductor] Starting web search for: {self.researcher.query}")
            research_data = await self._get_context_by_web_search(self.researcher.query, [], self.researcher.query_domains)
            self.logger.debug(f"[ResearchConductor] Web search completed, data length: {len(str(research_data))}")

        elif self.researcher.report_source == ReportSource.Local.value:
            self.logger.info("Using local search")
            # Load local documents only if it's not already loaded
            if not hasattr(self, 'db') or not self.researcher.db:
                document_data = await DocumentLoader(self.researcher.cfg.doc_path).load()
                document_data = clean_document_content(document_data)
                self.db = document_data
            else:
                document_data = self.db
            self.logger.info(f"Loaded {len(document_data)} documents")
            if self.researcher.vector_store:
                self.researcher.vector_store.load(document_data)

            research_data = await self._get_context_by_web_search(self.researcher.query, document_data, self.researcher.query_domains)

        # Hybrid search including both local documents and web sources
        elif self.researcher.report_source == ReportSource.Hybrid.value:
            if self.researcher.document_urls:
                document_data = await OnlineDocumentLoader(self.researcher.document_urls).load()
            else:
                document_data = await DocumentLoader(self.researcher.cfg.doc_path).load()
            if self.researcher.vector_store:
                self.researcher.vector_store.load(document_data)
            docs_context = await self._get_context_by_web_search(self.researcher.query, document_data, self.researcher.query_domains)
            web_context = await self._get_context_by_web_search(self.researcher.query, [], self.researcher.query_domains)
            research_data = self.researcher.prompt_family.join_local_web_documents(docs_context, web_context)

        elif self.researcher.report_source == ReportSource.Azure.value:
            from gpt_researcher.document.azure_document_loader import AzureDocumentLoader
            azure_loader = AzureDocumentLoader(
                container_name=os.getenv("AZURE_CONTAINER_NAME"),
                connection_string=os.getenv("AZURE_CONNECTION_STRING")
            )
            azure_files = await azure_loader.load()
            document_data = await DocumentLoader(azure_files).load()  # Reuse existing loader
            research_data = await self._get_context_by_web_search(self.researcher.query, document_data)
            
        elif self.researcher.report_source == ReportSource.LangChainDocuments.value:
            langchain_documents_data = await LangChainDocumentLoader(
                self.researcher.documents
            ).load()
            if self.researcher.vector_store:
                self.researcher.vector_store.load(langchain_documents_data)
            research_data = await self._get_context_by_web_search(
                self.researcher.query, langchain_documents_data, self.researcher.query_domains
            )

        elif self.researcher.report_source == ReportSource.LangChainVectorStore.value:
            research_data = await self._get_context_by_vectorstore(self.researcher.query, self.researcher.vector_store_filter)

        self.researcher.context = research_data
        if self.researcher.cfg.curate_sources:                
            self.logger.info("Curating sources")
            original_context = self.researcher.context
            self.researcher.context = await self.researcher.source_curator.curate_sources(research_data)

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "research_step_finalized",
                f"Finalized research step.\n💸 Total Research Costs: ${self.researcher.get_costs()}",
                self.researcher.websocket,
            )
            if self.json_handler:
                self.json_handler.update_content("costs", self.researcher.get_costs())
                self.json_handler.update_content("context", self.researcher.context)

        self.logger.info(f"Research completed. Context size: {len(str(self.researcher.context))}")
        self.logger.debug(f"[ResearchConductor] conduct_research completed, returning context")
        return self.researcher.context

    async def _get_context_by_urls(self, urls):
        """Scrapes and compresses the context from the given urls"""
        self.logger.info(f"Getting context from URLs: {urls}")
        
        new_search_urls = await self._get_new_urls(urls)
        self.logger.info(f"New URLs to process: {new_search_urls}")

        scraped_content = await self.researcher.scraper_manager.browse_urls(new_search_urls)
        self.logger.info(f"Scraped content from {len(scraped_content)} URLs")

        if self.researcher.vector_store:
            self.logger.info("Loading content into vector store")
            self.researcher.vector_store.load(scraped_content)

        context = await self.researcher.context_manager.get_similar_content_by_query(
            self.researcher.query, scraped_content
        )
        return context

    # Add logging to other methods similarly...

    async def _get_context_by_vectorstore(self, query, filter: dict | None = None):
        """
        Generates the context for the research task by searching the vectorstore with real-time updates
        Returns:
            context: List of context
        """
        self.logger.info(f"Starting vectorstore search for query: {query}")
        context = []
        # Generate Sub-Queries including original query
        sub_queries = await self.plan_research(query)
        # If this is not part of a sub researcher, add original query to research for better results
        if self.researcher.report_type != "subtopic_report":
            sub_queries.append(query)

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "subqueries",
                f"🗂️  I will conduct my research based on the following queries: {sub_queries}...",
                self.researcher.websocket,
                True,
                sub_queries,
            )

        # Process sub-queries sequentially for real-time updates
        combined_context = []
        for sub_query in sub_queries:
            try:
                content = await self._process_sub_query_with_vectorstore(sub_query, filter)
                if content:
                    combined_context.append(content)
                    # Update context in real-time
                    await self.researcher._update_context(content)
            except Exception as e:
                self.logger.warning(f"Error processing sub-query {sub_query}: {e}")
                continue
        
        if combined_context:
            final_context = " ".join(combined_context)
            self.logger.info(f"Combined context size: {len(final_context)}")
            self.logger.debug(f"[ResearchConductor] Combined context successfully, length: {len(final_context)}")
            return final_context
        self.logger.warning(f"[ResearchConductor] No context found after filtering")
        return ""

    async def _get_context_by_web_search(self, query, scraped_data: list | None = None, query_domains: list | None = None):
        """
        Generates the context for the research task by searching the query and scraping the results
        Returns:
            context: List of context
        """
        self.logger.info(f"Starting web search for query: {query}")
        self.logger.debug(f"[ResearchConductor] _get_context_by_web_search called with query: {query}")
        
        if scraped_data is None:
            scraped_data = []
        if query_domains is None:
            query_domains = []

        # Generate Sub-Queries including original query
        self.logger.debug(f"[ResearchConductor] Planning research for query: {query}")
        sub_queries = await self.plan_research(query, query_domains)
        self.logger.info(f"Generated sub-queries: {sub_queries}")
        self.logger.debug(f"[ResearchConductor] Generated {len(sub_queries)} sub-queries")
        
        # If this is not part of a sub researcher, add original query to research for better results
        if self.researcher.report_type != "subtopic_report":
            sub_queries.append(query)

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "subqueries",
                f"🗂️ I will conduct my research based on the following queries: {sub_queries}...",
                self.researcher.websocket,
                True,
                sub_queries,
            )

        # Using asyncio.gather to process the sub_queries asynchronously
        try:
            # Create unique concurrent group ID using timestamp and random number
            concurrent_group = f"{id(sub_queries)}"
            self.logger.debug(f"[ResearchConductor] Starting concurrent processing of {len(sub_queries)} sub-queries")
            # Create lists to store content and node IDs
            content_list = []
            node_id_list = []
            
            # Process each sub_query and store results
            results = await asyncio.gather(
                *[
                    self._process_sub_query(sub_query, scraped_data, query_domains, concurrent_group)
                    for sub_query in sub_queries
                ]
            )
            
            # Separate content and node_ids from results
            for result in results:
                if isinstance(result, tuple):
                    content, node_id = result
                    content_list.append(content)
                    node_id_list.append(node_id)
                else:
                    content_list.append(result)
            
            context = content_list
            
            self.logger.info(f"Gathered context from {len(context)} sub-queries")
            self.logger.debug(f"[ResearchConductor] asyncio.gather completed, got {len(context)} context items")
            # Filter out empty results and join the context
            context = [c for c in context if c]
            if context:
                combined_context = " ".join(context)
                self.logger.info(f"Combined context size: {len(combined_context)}")
                self.logger.debug(f"[ResearchConductor] Combined context successfully, length: {len(combined_context)}")
                
                return combined_context
            self.logger.warning(f"[ResearchConductor] No context found after filtering")
            return []
        except Exception as e:
            raise e

    async def _process_sub_query(self, sub_query: str, scraped_data: list = [], query_domains: list = [], concurrent_group: str = None):
        """Takes in a sub query and scrapes urls based on it and gathers context."""
        self.logger.debug(f"[ResearchConductor] _process_sub_query called with sub_query: {sub_query}")
        
        if self.json_handler:
            self.json_handler.log_event("sub_query", {
                "query": sub_query,
                "scraped_data_size": len(scraped_data)
            })
        
        # Create individual subquery node
        if self.enhanced_logger:
            subquery_node_id = self.enhanced_logger.add_node(
                depth=1,
                breadth=1,
                query=sub_query,
                parent_id=self.current_node_id,
                status="started",
                operation="subquery_execution",
                start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                node_id=self._get_next_node_id(),
                concurrent_group=concurrent_group
            )

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "running_subquery_research",
                f"\n🔍 Running research for '{sub_query}'...",
                self.researcher.websocket,
            )

        try:
            if not scraped_data:
                self.logger.debug(f"[ResearchConductor] No scraped_data provided, scraping for sub_query: {sub_query}")
                scraped_data = await self._scrape_data_by_urls(sub_query, query_domains)
                self.logger.info(f"Scraped data size: {len(scraped_data)}")
                self.logger.debug(f"[ResearchConductor] Scraped {len(scraped_data)} items for sub_query: {sub_query}")

            self.logger.debug(f"[ResearchConductor] Getting similar content for sub_query: {sub_query}")
            content = await self.researcher.context_manager.get_similar_content_by_query(sub_query, scraped_data)
            self.logger.info(f"Content found for sub-query: {len(str(content)) if content else 0} chars")
            self.logger.debug(f"[ResearchConductor] Got content for sub_query: {sub_query}, length: {len(str(content)) if content else 0}")

            if not content and self.researcher.verbose:
                await stream_output(
                    "logs",
                    "subquery_context_not_found",
                    f"🤷 No content found for '{sub_query}'...",
                    self.researcher.websocket,
                )

            # Update subquery node with results
            if self.enhanced_logger:
                self.enhanced_logger.update_node(
                    node_id=subquery_node_id,
                    status="completed",
                    results={
                        "content": truncate(str(content)) if content else None,
                        "scraped_data": truncate(scraped_data)
                    },
                    end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )

            if content:
                if self.json_handler:
                    self.json_handler.log_event("content_found", {
                        "sub_query": sub_query,
                        "content_size": len(content)
                    })
            return content, subquery_node_id
        except Exception as e:
            raise e

    async def _process_sub_query_with_vectorstore(self, sub_query: str, filter: dict | None = None):
        """Takes in a sub query and gathers context from the user provided vector store

        Args:
            sub_query (str): The sub-query generated from the original query

        Returns:
            str: The context gathered from search
        """
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "running_subquery_with_vectorstore_research",
                f"\n🔍 Running research for '{sub_query}'...",
                self.researcher.websocket,
            )

        context = await self.researcher.context_manager.get_similar_content_by_query_with_vectorstore(sub_query, filter)

        return context

    async def _get_new_urls(self, url_set_input):
        """Gets the new urls from the given url set.
        Args: url_set_input (set[str]): The url set to get the new urls from
        Returns: list[str]: The new urls from the given url set
        """

        self.logger.debug(f"[ResearchConductor] _get_new_urls called with {len(url_set_input)} URLs")
        new_urls = []
        for url in url_set_input:
            if url not in self.researcher.visited_urls:
                self.researcher.visited_urls.add(url)
                new_urls.append(url)
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "added_source_url",
                        f"✅ Added source url to research: {url}\n",
                        self.researcher.websocket,
                        True,
                        url,
                    )

        self.logger.debug(f"[ResearchConductor] _get_new_urls returning {len(new_urls)} new URLs")
        return new_urls

    async def _search_relevant_source_urls(self, query, query_domains: list | None = None):
        new_search_urls = []
        if query_domains is None:
            query_domains = []

        self.logger.debug(f"[ResearchConductor] _search_relevant_source_urls called with query: {query}")

        # Iterate through all retrievers
        for retriever_class in self.researcher.retrievers:
            self.logger.debug(f"[ResearchConductor] Using retriever: {retriever_class.__name__}")
            # Instantiate the retriever with the sub-query
            try:
                retriever = retriever_class(query, query_domains=query_domains, root_query=self.researcher.root_query)
            except:
                retriever = retriever_class(query, query_domains=query_domains)

            # Perform the search using the current retriever
            self.logger.debug(f"[ResearchConductor] Performing search with retriever: {retriever_class.__name__}")
            
            # Track search API latency
            start_time = time.time()
            search_results = await asyncio.to_thread(
                retriever.search, max_results=self.researcher.cfg.max_search_results_per_query
            )
            latency = time.time() - start_time
            LatencyTracker.track_latency("search", latency, source=retriever_class.__name__)
            
            self.logger.debug(f"[ResearchConductor] Search completed, got {len(search_results)} results from {retriever_class.__name__}")

            # Collect new URLs from search results
            search_urls = [url.get("href") for url in search_results]
            new_search_urls.extend(search_urls)

        # Get unique URLs
        self.logger.debug(f"[ResearchConductor] Before deduplication: {len(new_search_urls)} URLs")
        new_search_urls = await self._get_new_urls(new_search_urls)
        self.logger.debug(f"[ResearchConductor] After deduplication: {len(new_search_urls)} new URLs")
        random.shuffle(new_search_urls)

        return new_search_urls

    async def _scrape_data_by_urls(self, sub_query, query_domains: list | None = None):
        """
        Runs a sub-query across multiple retrievers and scrapes the resulting URLs.

        Args:
            sub_query (str): The sub-query to search for.

        Returns:
            list: A list of scraped content results.
        """
        self.logger.debug(f"[ResearchConductor] _scrape_data_by_urls called with sub_query: {sub_query}")
        
        if query_domains is None:
            query_domains = []

        self.logger.debug(f"[ResearchConductor] Searching for relevant source URLs for sub_query: {sub_query}")
        new_search_urls = await self._search_relevant_source_urls(sub_query, query_domains)
        self.logger.debug(f"[ResearchConductor] Found {len(new_search_urls)} new search URLs for sub_query: {sub_query}")

        # Log the research process if verbose mode is on
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "researching",
                f"🤔 Researching for relevant information across multiple sources...\n",
                self.researcher.websocket,
            )

        # Scrape the new URLs with real-time updates
        self.logger.debug(f"[ResearchConductor] Starting to scrape {len(new_search_urls)} URLs")
        scraped_content = await self.researcher.scraper_manager.browse_urls(new_search_urls)
        self.logger.debug(f"[ResearchConductor] Scraped {len(scraped_content)} content items from URLs")

        # Process URLs one by one for real-time updates
        await self.researcher._update_context(scraped_content)

        if self.researcher.vector_store:
            self.researcher.vector_store.load(scraped_content)

        return scraped_content


async def get_vector_store_results(query, vector_store, filter: dict | None = None):
    """
    Gets the results from the vector store based on the query and filter.
    Args:
        query (str): The query to search for in the vector store.
        vector_store (VectorStore): The vector store to search in.
        filter (dict | None): Optional filter to apply to the search.
    Returns:
        list: The results from the vector store.
    """
    
    results = await vector_store.asimilarity_search(query, k=10, filter=filter)
    if not results:
        raise ValueError(f"No results found for query: {query} with filter: {filter}")
    else:
        formatted_results = [
                {
                    "href": result.metadata.get("source", "Unknown Source"),
                    "body": result.page_content
                } 
                for result in results
            ]
        return formatted_results
    

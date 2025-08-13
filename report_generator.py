import os
import json
import asyncio
import argparse
from modified_agent import GPTResearcher
from gpt_researcher.utils.enum import ReportType
from utils import Config, trim_context_to_word_limit

os.environ["OPENAI_API_KEY"] = open("./openai.key").read().strip()
os.environ["OPENAI_BASE_URL"] = open("openai_url.key").read().strip()

class ReportGenerator:
    def __init__(self, progress_file: str, config_file: str):
        self.data = self._load_progress(progress_file)
        self.query = self._load_user_query()
        self.config = Config(config_file)
        self.researcher = GPTResearcher(
            query=self.query,
            report_type=ReportType.DeepResearch.value,
            report_source=self.config.report_source,
            config_path=config_file
        )
    
    def _load_progress(self, progress_file: str) -> str:
        with open(progress_file, 'r') as file:
            progress_data = json.load(file)        
        # Extract the initial user query from the node 0
        return progress_data.get('nodes', [])

    def _load_user_query(self) -> str:
        # Assuming the first node contains the user query
        if self.data:
            return self.data[0].get('query', '').strip().split('\n')[0].strip()
        return ''
    
    def compile_data(self) -> dict:
        if not self.data:
            return {}
        
        # Extract relevant data from the progress file
        research_data = {
            'learnings': [],
            'citations': {},
            'context': [],
            'visited_urls': [],
            'sources': [],
            'context': []
        }
        
        for node in self.data:
            if node.get('operation', '') == "research":
                research_data['learnings'].extend(node.get('results', {}).get('learnings', []))
                research_data['citations'].update(node.get('results', {}).get('citations', {}))
                research_data['context'].extend(node.get('results', {}).get('context', []))
                research_data['visited_urls'].extend(node.get('results', {}).get('visited_urls', []))
                research_data['sources'].extend(node.get('results', {}).get('sources', []))
            elif node.get('operation', '') == "research_execution":
                if node.get('results', {}).get('context'):
                    research_data['context'].extend(node.get('results', {}).get('context', []))

        return research_data

    async def generate_report(self, research_data: dict) -> str:
        if not self.data:
            return "No research data available to generate a report."
        
        # Prepare the context for the researcher
        # Prepare context with citations
        context_with_citations = []
        for learning in research_data['learnings']:
            citation = research_data['citations'].get(learning, '')
            if citation:
                context_with_citations.append(f"{learning} [Source: {citation}]")
            else:
                context_with_citations.append(learning)

        # Add all research context
        if research_data.get('context'):
            context_with_citations.extend(research_data['context'])

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
        self.researcher.visited_urls = research_data['visited_urls']

        # Set research sources
        if research_data.get('sources'):
            self.researcher.research_sources = research_data['sources']

        # Generate the report
        report = await self.researcher.write_report()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a research report from progress data.")
    parser.add_argument('--progress', type=str, help='Path to the progress JSON file.')
    parser.add_argument('--config', type=str, help='Path to the configuration JSON file.')
    
    args = parser.parse_args()
    
    generator = ReportGenerator(args.progress, args.config)
    research_data = generator.compile_data()
    report = asyncio.run(generator.generate_report(research_data))
    
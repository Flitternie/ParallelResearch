import json
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Any


class BaseResearchVisualizer(ABC):
    """Abstract base class for research visualizers with common functionality"""
    
    def __init__(self, log_file: str = "research_progress.json"):
        self.log_file = log_file
    
    def load_log(self) -> Dict[str, Any]:
        """Load the research log file with error handling"""
        try:
            import os
            if not os.path.exists(self.log_file):
                # raise error if file doesn't exist
                raise FileNotFoundError(f"Log file {self.log_file} does not exist.")
            
            if os.path.getsize(self.log_file) == 0:
                # Return empty structure if file is empty
                raise Warning(f"Log file {self.log_file} is empty.")
                
            with open(self.log_file, 'r') as f:
                content = f.read().strip()
                if not content:
                    # Return empty structure if file content is empty
                    return {
                        "nodes": [],
                        "edges": [],
                        "start_time": ""
                    }
                return json.loads(content)
        except (json.JSONDecodeError, FileNotFoundError, PermissionError) as e:
            # Log the error for debugging purposes
            raise Warning(f"Error loading log file {self.log_file}: {e}") from e
    
    def _clean_text(self, text: str) -> str:
        """Clean text by removing problematic characters and normalizing quotes"""
        if text is None:
            return ""
        text = re.sub(r'[^\x20-\x7E\n\'"]', '', text)
        text = text.replace('"', '"').replace('"', '"')
        text = text.replace(''', "'").replace(''', "'")
        return text

    def _parse_initial_query(self, query: str) -> Dict[str, Any]:
        """Parse a query that contains Initial Query and Q&A format"""
        # Handle both formats: "Follow-up Questions and Answers:" and "Follow - up Questions and Answers:"
        parts = query.split("Follow - up Questions and Answers:")
        if len(parts) != 2:
            parts = query.split("Follow-up Questions and Answers:")
            if len(parts) != 2:
                return {"initial_query": query.strip(), "qa_pairs": []}
            
        initial_query = parts[0].replace("Initial Query:", "").strip()
        qa_text = parts[1].strip()
        
        qa_pairs = []
        qa_parts = qa_text.split("Q: ")
        for part in qa_parts[1:]:
            if "A: " in part:
                q, a = part.split("A: ", 1)
                qa_pairs.append({
                    "question": q.strip(),
                    "answer": a.strip()
                })
            
        return {
            "initial_query": initial_query,
            "qa_pairs": qa_pairs
        }

    def _parse_research_goal(self, query: str) -> Dict[str, Any]:
        """Parse a query that contains Previous research goal and follow-up questions"""
        sections = query.split("Follow-up questions:")
        if len(sections) != 2:
            return {"research_goal": query.strip(), "follow_up_questions": []}
            
        goal = sections[0].replace("Previous research goal:", "").strip()
        questions = [q.strip() for q in sections[1].split("?") if q.strip()]
        
        return {
            "research_goal": goal,
            "follow_up_questions": questions
        }

    def _format_initial_query_html(self, parsed_query: Dict[str, Any]) -> str:
        """Format the initial query and Q&A pairs as HTML"""
        html = f'''
            <b>Initial Query:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">{parsed_query['initial_query']}</div>
'''
        
        if parsed_query['qa_pairs']:
            html += '''
            <b>Follow-up Questions and Answers:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">
'''
            for qa in parsed_query['qa_pairs']:
                html += f'''
                <div style="margin-bottom: 8px;">
                    <b>Q:</b> {qa['question']}<br>
                    <b>A:</b> {qa['answer']}
                </div>'''
            html += "            </div>"
            
        return html

    def _format_research_goal_html(self, parsed_query: Dict[str, Any]) -> str:
        """Format the research goal and follow-up questions as HTML"""
        html = f'''
            <b>Previous Research Goal:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">{parsed_query['research_goal']}</div>
'''
        
        if parsed_query['follow_up_questions']:
            html += '''
            <b>Follow-up Questions:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">
'''
            for question in parsed_query['follow_up_questions']:
                html += f"                - {question}?<br>"
            html += "            </div>"
            
        return html

    def _format_agent_selection_html(self, results: Dict[str, Any]) -> str:
        """Format agent selection information as HTML"""
        html = ""
        
        if results.get("agent"):
            html += f'''
            <b>Selected Agent:</b>
            <div style="padding: 8px; background: #e8f4fd; border-radius: 4px; margin: 5px 0; border-left: 4px solid #2196F3;">
                {self._clean_text(results["agent"])}
            </div>
'''
        
        if results.get("role"):
            html += f'''
            <b>Agent Role:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">
                {self._clean_text(results["role"])}
            </div>
'''
        
        return html

    def _format_search_planning_html(self, results: Dict[str, Any]) -> str:
        """Format search planning subqueries as HTML"""
        html = ""
        
        if results.get("subqueries"):
            html += f'''
            <b>Planned Subqueries ({len(results["subqueries"])}):</b>
            <div style="padding: 8px; background: #fff3e0; border-radius: 4px; margin: 5px 0; border-left: 4px solid #ff9800;">
'''
            for i, subquery in enumerate(results["subqueries"], 1):
                html += f'''
                <div style="margin-bottom: 8px; padding: 6px; background: #fafafa; border-radius: 3px;">
                    <b>{i}.</b> {self._clean_text(subquery)}
                </div>'''
            html += "            </div>"
        
        return html

    def _parse_content_sections(self, content: str) -> List[Dict[str, str]]:
        """Parse content text to extract Source, Title, and Content sections"""
        sections = []
        current_section = {}
        
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            if line.startswith('Source:'):
                # Save previous section if exists
                if current_section:
                    sections.append(current_section)
                current_section = {'source': line[7:].strip()}
            elif line.startswith('Title:'):
                if current_section:
                    current_section['title'] = line[6:].strip()
            elif line.startswith('Content:'):
                if current_section:
                    current_section['content'] = line[8:].strip()
            elif current_section and 'content' in current_section:
                # Continue content from previous line
                current_section['content'] += ' ' + line
        
        # Add the last section
        if current_section:
            sections.append(current_section)
            
        return sections

    def _format_subquery_execution_html(self, results: Dict[str, Any], node: Dict[str, Any]) -> str:
        """Format subquery execution information as HTML"""
        html = ""
        
        # Display the subquery query
        if node.get("query"):
            html += f'''
            <b>Subquery:</b>
            <div style="padding: 8px; background: #fff3e0; border-radius: 4px; margin: 5px 0; border-left: 4px solid #ff9800;">
                {self._clean_text(node["query"])}
            </div>
'''
        
        if results.get("content"):
            # Parse the content into sections
            sections = self._parse_content_sections(results["content"])
            
            if sections:
                html += f'''
            <b>Research Summary ({len(sections)} sources):</b>
            <div style="padding: 8px; background: #e8f5e8; border-radius: 4px; margin: 5px 0; border-left: 4px solid #4CAF50;">
'''
                for i, section in enumerate(sections, 1):
                    html += f'''
                <div style="margin-bottom: 12px; padding: 8px; background: #f8f9fa; border-radius: 4px; border-left: 3px solid #28a745;">
                    <b>Source {i}:</b><br>
                    <small style="color: #6c757d;">{self._clean_text(section.get('source', ''))}</small><br><br>
'''
                    
                    if section.get('title'):
                        html += f'''
                    <b>Title:</b> {self._clean_text(section['title'])}<br><br>
'''
                    
                    if section.get('content'):
                        # Truncate content if too long
                        content = self._clean_text(section['content'])
                        if len(content) > 300:
                            content = content[:300] + "..."
                        html += f'''
                    <b>Content:</b> {content}
'''
                    
                    html += "                </div>"
                
                html += "            </div>"
            else:
                # Fallback if parsing fails
                html += f'''
            <b>Research Summary:</b>
            <div style="padding: 8px; background: #e8f5e8; border-radius: 4px; margin: 5px 0; border-left: 4px solid #4CAF50;">
                {self._clean_text(results["content"])}
            </div>
'''
        
        if results.get("scraped_data") and len(results["scraped_data"]) > 0:
            html += f'''
            <b>Sources ({len(results["scraped_data"])}):</b>
            <div style="padding: 8px; background: #f0f8ff; border-radius: 4px; margin: 5px 0; border-left: 4px solid #2196F3;">
'''
            for i, source in enumerate(results["scraped_data"], 1):
                title = self._clean_text(source.get("title", "Untitled"))
                url = self._clean_text(source.get("url", ""))
                html += f'''
                <div style="margin-bottom: 6px; padding: 4px; background: #fafafa; border-radius: 3px;">
                    <b>{i}.</b> {title}<br>
                    <small><a href="{url}" target="_blank">{url}</a></small>
                </div>'''
            html += "            </div>"
        
        return html

    def _format_results_html(self, results: Dict[str, Any]) -> str:
        """Format the results section of the node details"""
        html = ""
        
        if results.get("learnings"):
            parsed_learnings = self._parse_learnings(results["learnings"], results.get("citations", {}))
                
            html += f'''
            <b>Key Learnings ({len(parsed_learnings)}):</b>
            <div style="padding: 8px; background: #e8f5e8; border-radius: 4px; margin: 5px 0; border-left: 4px solid #4CAF50;">
'''
            for i, learning in enumerate(parsed_learnings, 1):
                html += f'''
                <div style="margin-bottom: 8px; padding: 6px; background: #f8f9fa; border-radius: 3px;">
                    <b>{i}.</b> {self._clean_text(learning["content"])}'''
                
                if learning["url"]:
                    html += f'''<br>
                    <small><a href="{learning['url']}" target="_blank">[Source]</a></small>'''
                
                html += "                </div>"
            html += "            </div>"

        if results.get("followUpQuestions"):
            html += f'''
            <b>Follow-up Questions ({len(results['followUpQuestions'])})</b>
            <div style="padding: 8px; background: #fff3e0; border-radius: 4px; margin: 5px 0; border-left: 4px solid #ff9800;">
'''
            for i, question in enumerate(results["followUpQuestions"], 1):
                html += f'''
                <div style="margin-bottom: 6px; padding: 4px; background: #fafafa; border-radius: 3px;">
                    <b>{i}.</b> {self._clean_text(question)}
                </div>'''
            html += "            </div>"
        
        return html

    def _parse_learnings(self, learnings: List[str], citations: Dict[str, str] = None) -> List[Dict[str, str]]:
        """Parse learnings to separate URLs from content"""
        parsed_learnings = []
        
        for learning in learnings:
            url = citations.get(learning, "")
            url = url[:-1] if url.endswith(':') else url
            # Handle format 1: "Learning [content]"
            if learning.startswith("Learning "):
                content = learning[9:].strip()  # Remove "Learning " prefix
                parsed_learnings.append({
                    "url": url,
                    "content": content
                })
            
            # Handle format 2: "//url]: [content]"
            elif learning.startswith("//"):
                # Extract URL from the beginning
                url_end = learning.find("]: ")
                if url_end != -1:
                    content = learning[url_end + 3:].strip()  # Remove "]: " and get content
                    parsed_learnings.append({
                        "url": url,
                        "content": content
                    })
                else:
                    # Fallback if format is unexpected
                    parsed_learnings.append({
                        "url": url,
                        "content": learning.strip()
                    })
            
            else:
                parsed_learnings.append({
                    "url": url,
                    "content": learning.strip()
                })
        
        return parsed_learnings

    def _is_internal_node(self, node_id: str) -> bool:
        """Check if a node is an internal node (has format X.X or X.X.X)"""
        return '.' in str(node_id)
    
    def _get_parent_node_id(self, internal_node_id: str) -> str:
        """Get the parent node ID from an internal node ID (e.g., '1.2' -> '1')"""
        return str(internal_node_id).split('.')[0]

    @abstractmethod
    def visualize(self, output_file: str):
        """Create visualization - to be implemented by subclasses"""
        pass

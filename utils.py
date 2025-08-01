import json
from typing import Dict, List, Any, Optional
from datetime import datetime
import threading
from research_visualizer_legacy import ResearchVisualizer

# Maximum words allowed in context (25k words for safety margin)
MAX_CONTEXT_WORDS = 25000


def count_words(text: str) -> int:
    """Count words in a text string"""
    if isinstance(text, str):
        return len(text.split())
    elif isinstance(text, list):
        return sum(count_words(item) for item in text)
    else:
        raise TypeError(f"Unsupported type for word counting: {type(text)}")

def trim_context_to_word_limit(context_list: List[str], max_words: int = MAX_CONTEXT_WORDS) -> List[str]:
    """Trim context list to stay within word limit while preserving most recent/relevant items"""
    total_words = 0
    trimmed_context = []

    # Process in reverse to keep most recent items
    for item in reversed(context_list):
        words = count_words(item)
        if total_words + words <= max_words:
            trimmed_context.insert(0, item)  # Insert at start to maintain original order
            total_words += words
        else:
            break

    return trimmed_context

def clean_document_content(documents):
    """Clean special tokens from document content to prevent encoding errors"""

    import re
    if not documents:
        return documents
        
    cleaned_documents = []
    special_tokens_pattern = r'<\|endoftext\|>'
    
    for doc in documents:
        if hasattr(doc, 'page_content'):
            # For LangChain-style documents
            doc.page_content = re.sub(special_tokens_pattern, '', doc.page_content)
            cleaned_documents.append(doc)
        elif isinstance(doc, dict):
            # For dictionary-style documents
            cleaned_doc = doc.copy()
            if 'content' in cleaned_doc:
                cleaned_doc['content'] = re.sub(special_tokens_pattern, '', str(cleaned_doc['content']))
            if 'raw_content' in cleaned_doc:
                cleaned_doc['raw_content'] = re.sub(special_tokens_pattern, '', str(cleaned_doc['raw_content']))
            if 'text' in cleaned_doc:
                cleaned_doc['text'] = re.sub(special_tokens_pattern, '', str(cleaned_doc['text']))
            cleaned_documents.append(cleaned_doc)
        elif isinstance(doc, str):
            # For string documents
            cleaned_doc = re.sub(special_tokens_pattern, '', doc)
            cleaned_documents.append(cleaned_doc)
        else:
            # For other document types, convert to string and clean
            cleaned_doc = re.sub(special_tokens_pattern, '', str(doc))
            cleaned_documents.append(cleaned_doc)
            
    return cleaned_documents

def truncate(obj, max_length=100):
    """Truncate text to a maximum length"""
    if isinstance(obj, str):
        if len(obj) > max_length:
            return obj[:max_length] + ' [TRUNCATED]...'
        return obj
    elif isinstance(obj, list):
        return [truncate(item, max_length) for item in obj]
    elif isinstance(obj, dict):
        new_obj = {}
        for key, value in obj.items():
            if key in ['content', 'text', 'raw_content']:
                new_obj[key] = truncate(value, max_length)
            else:
                new_obj[key] = value
        return new_obj


class Config:
    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        # Set each key as an attribute (lowercase)
        for key, value in self.config.items():
            setattr(self, key.lower(), value)
    
    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)
    
    def __getitem__(self, key: str) -> Any:
        return self.get(key)
    
    def __contains__(self, key: str) -> bool:
        return key in self.config


class ResearchProgress:
    def __init__(self, total_depth: int, total_breadth: int):
        self.current_depth = total_depth
        self.total_depth = total_depth
        self.current_breadth = total_breadth
        self.total_breadth = total_breadth
        self.current_query: Optional[str] = None
        self.total_queries = 0
        self.completed_queries = 0

class ResearchLogger:
    def __init__(self, logs_dir: str, visualization: bool = False, update_callback=None):
        self.logs_dir = logs_dir
        self.log_file = f"{logs_dir}/progress.json"
        self.log_data = {
            "nodes": [],
            "edges": [],
            "start_time": datetime.now().isoformat()
        }
        self.node_counter = 0
        self.visualizer = ResearchVisualizer(log_file=self.log_file)
        self.visualization = visualization
        self.update_callback = update_callback  # Callback for when progress is updated

        self._lock = threading.Lock()
    
    def add_node(self, 
                 depth: int,
                 breadth: int,
                 query: str,
                 parent_id: Optional[str | list[str]] = None,
                 research_goal: Optional[str] = None,
                 status: str = "started",
                 concurrent_group: Optional[int] = None,
                 operation: Optional[str] = None,
                 start_time: Optional[str] = None,
                 node_id: Optional[str] = None) -> str:
        """Add a new research node to the log"""
        if node_id is None:
            node_id = str(self.node_counter)
            self.node_counter += 1
        
        node = {
            "id": node_id,
            "depth": depth,
            "breadth": breadth,
            "query": query,
            "parent_id": parent_id,
            "research_goal": research_goal,
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "results": None,
            "concurrent_group": concurrent_group,
            "operation": operation,
            "start_time": start_time
        }
        
        self.log_data["nodes"].append(node)
        
        if parent_id is not None and isinstance(parent_id, str):
            self.log_data["edges"].append({
                "from": parent_id,
                "to": node_id
            })
        elif parent_id is not None and isinstance(parent_id, list):
            for parent_node_id in parent_id:
                self.log_data["edges"].append({
                    "from": parent_node_id,
                    "to": node_id
                })
        
        self._save_log()
        return node_id
    
    def update_node(self, 
                    node_id: str, 
                    status: str,
                    results: Optional[Dict[str, Any]] = None,
                    visited_urls: Optional[List[str]] = None,
                    end_time: Optional[str] = None
    ):
        """Update an existing research node"""
        for node in self.log_data["nodes"]:
            if str(node["id"]) == str(node_id):
                node["status"] = status
                if results:
                    node["results"] = results
                if visited_urls:
                    node["visited_urls"] = list(visited_urls)
                if end_time:
                    node["end_time"] = end_time
                    duration_td = datetime.fromisoformat(end_time) - datetime.fromisoformat(node["start_time"])
                    hours = int(duration_td.total_seconds() // 3600)
                    minutes = int((duration_td.total_seconds() % 3600) // 60)
                    seconds = int(duration_td.total_seconds() % 60)
                    node["duration"] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                node["update_timestamp"] = datetime.now().isoformat()
                break
        
        self._save_log()
    
    
    def _save_log(self):
        """Save the current log to file"""
        with self._lock:
            with open(self.log_file, 'w') as f:
                json.dump(self.log_data, f, indent=2)
        
        # Call update callback if provided
        if self.update_callback:
            try:
                self.update_callback(self.log_data)
            except Exception as e:
                print(f"Error in update callback: {e}")
        
        if self.visualization:
            self.visualizer.visualize(output_file=f"{self.logs_dir}/research_visualization.html")


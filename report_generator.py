import os
import json
import asyncio
import argparse
import random
from datetime import datetime
from collections import deque, defaultdict
from modified_agent import GPTResearcher
from gpt_researcher.utils.enum import ReportType
from utils import Config, trim_context_to_word_limit

os.environ["OPENAI_API_KEY"] = open("./openai.key").read().strip()
os.environ["OPENAI_BASE_URL"] = open("openai_url.key").read().strip()

class ReportGenerator:
    def __init__(self, progress_file: str, config_file: str, root_id: str | None = None):
        # Load full progress log (nodes + edges)
        self.log = self._load_progress(progress_file)
        raw_nodes = self.log.get('nodes', {}) if self.log else {}
        raw_edges = self.log.get('edges', []) if self.log else []

        # Ignore subnodes (IDs like X.X or X.X.X) entirely when reading
        def _is_dotted(nid: str) -> bool:
            return '.' in str(nid)

        self.nodes = {str(nid): node for nid, node in (raw_nodes or {}).items() if not _is_dotted(nid)}
        self.edges = [
            {"from": str(e.get('from')), "to": str(e.get('to'))}
            for e in (raw_edges or [])
            if not _is_dotted(e.get('from')) and not _is_dotted(e.get('to'))
        ]
        self.root_id = root_id or self._detect_root_id()
        self.depths = {}
        self.children = defaultdict(list)  # parent -> [child,...]
        self.parents = defaultdict(list)   # child -> [parent,...]
        self._build_graph()
        self._compute_depths()

        self.query = self._load_user_query()
        self.config = Config(config_file)
        self.researcher = GPTResearcher(
            query=self.query,
            report_type=ReportType.DeepResearch.value,
            report_source=self.config.report_source,
            config_path=config_file
        )
    
    def _load_progress(self, progress_file: str) -> dict:
        with open(progress_file, 'r') as file:
            progress_data = json.load(file)        
        return progress_data or {}

    def _detect_root_id(self) -> str | None:
        # Prefer node with parent_id None
        for nid, node in (self.log.get('nodes', {}) or {}).items():
            if node.get('parent_id') in (None, ""):
                return str(nid)
        # Fallback: node that never appears as an edge 'to'
        to_ids = {str(e.get('to')) for e in (self.log.get('edges', []) or [])}
        for nid in (self.log.get('nodes', {}) or {}).keys():
            if str(nid) not in to_ids:
                return str(nid)
        # Final fallback to "0" if present
        return "0" if '0' in (self.log.get('nodes', {}) or {}) else None

    def _build_graph(self) -> None:
        # Build adjacency from edges if present
        for e in self.edges or []:
            parent = str(e.get('from'))
            child = str(e.get('to'))
            if parent is None or child is None:
                continue
            self.children[parent].append(child)
            self.parents[child].append(parent)

        # Also infer from parent_id fields to be robust
        for nid, node in (self.nodes or {}).items():
            pid = node.get('parent_id')
            if isinstance(pid, list):
                for p in pid:
                    pstr = str(p)
                    # Skip dotted parents that were ignored
                    if pstr in self.nodes:
                        self.children[pstr].append(str(nid))
                        self.parents[str(nid)].append(pstr)
            elif pid not in (None, ""):
                pstr = str(pid)
                if pstr in self.nodes:
                    self.children[pstr].append(str(nid))
                    self.parents[str(nid)].append(pstr)
        # ensure keys exist for all nodes
        for nid in (self.nodes or {}).keys():
            _ = self.children[str(nid)]
            _ = self.parents[str(nid)]

    def _compute_depths(self) -> None:
        self.depths = {}
        if not self.root_id:
            return
        # BFS from root to compute semantic depths ignoring plan nodes in distance
        # Depth increments only when entering a research or research_execution node
        allowed_research_ops = {"research"}
        queue = deque()
        queue.append((self.root_id, 0))
        self.depths[self.root_id] = 0
        visited = set()
        while queue:
            current, d = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            for child in self.children.get(current, []):
                child_op = (self.nodes.get(str(child)) or {}).get('operation')
                inc = 1 if child_op in allowed_research_ops else 0
                new_depth = d + inc
                # Keep the minimum depth seen for a node
                if child not in self.depths or new_depth < self.depths[child]:
                    self.depths[child] = new_depth
                queue.append((child, new_depth))

    def _descendant_research_nodes(self, nid: str, _cache: dict | None = None) -> list[str]:
        if _cache is None:
            _cache = {}
        nid = str(nid)
        if nid in _cache:
            return _cache[nid]
        result = []
        stack = [nid]
        visited = set()
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            if cur != nid:
                node = self.nodes.get(str(cur), {})
                if node.get('operation') == 'research':
                    result.append(str(cur))
            for ch in self.children.get(cur, []):
                if ch not in visited:
                    stack.append(ch)
        _cache[nid] = result
        return result

    def get_max_depth(self) -> int:
        if not self.depths:
            self._compute_depths()
        return max(self.depths.values()) if self.depths else 0

    def get_tree_summary(self) -> dict:
        return {
            'root_id': self.root_id,
            'nodes': len(self.nodes or {}),
            'edges': len(self.edges or []),
            'max_depth': self.get_max_depth()
        }

    def _load_user_query(self) -> str:
        # Assuming the first node contains the user query
        if self.nodes:
            root_key = self.root_id or "0"
            root_node = self.nodes.get(str(root_key))
            if root_node:
                return root_node.get('query', '').strip().split('\n')[0].strip()
        return ''
    
    def _parse_dt(self, value: str | None) -> datetime | None:
        if not value:
            return None
        # Try multiple formats
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except Exception:
                continue
        # Fallback: datetime.fromisoformat may handle subsecond variations
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _filter_node_ids(self, max_depth: int | None) -> list[str]:
        # Exclude dotted IDs like X.X or X.X.X
        candidates = [nid for nid in (self.nodes or {}).keys() if '.' not in str(nid)]
        if max_depth is None:
            return candidates
        # Keep nodes with computed distance <= max_depth
        filtered = []
        for nid in candidates:
            dist = self.depths.get(str(nid))
            if dist is not None and dist <= max_depth:
                filtered.append(str(nid))
            # If we lack a computed depth (disconnected), keep only root
            elif dist is None and str(nid) == (self.root_id or "0") and max_depth >= 0:
                filtered.append(str(nid))
        return filtered

    def _eligible_node_ids(self, max_depth: int | None) -> list[str]:
        # Apply depth/dotted filtering, then include only research-related ops
        ids = self._filter_node_ids(max_depth)
        allowed_ops = {"research", "research_execution"}
        return [nid for nid in ids if (self.nodes.get(str(nid)) or {}).get('operation') in allowed_ops]

    def _order_node_ids(self, node_ids: list[str], ordering: str) -> list[str]:
        ordering = (ordering or 'start_time_asc').lower()
        if ordering in ("dfs", "depth_first"):
            return self._order_dfs(node_ids)
        if ordering in ("bfs", "breadth_first"):
            return self._order_bfs(node_ids)
        if ordering in ("random", "shuffle"):
            ids = list(node_ids)
            random.shuffle(ids)
            return ids
        # time-based
        reverse = ordering.endswith("_desc")
        key = 'start_time' if ordering.startswith('start') else 'end_time'
        def time_key(nid: str):
            node = self.nodes.get(str(nid), {})
            op = node.get('operation')
            dt = None
            if op == 'research':
                dt = self._parse_dt(node.get(key)) or self._parse_dt(node.get('timestamp'))
            else:
                # derive time from descendant research nodes
                desc = self._descendant_research_nodes(nid)
                times = []
                for d in desc:
                    dn = self.nodes.get(str(d), {})
                    dt_candidate = self._parse_dt(dn.get(key)) or self._parse_dt(dn.get('timestamp'))
                    if dt_candidate:
                        times.append(dt_candidate)
                if times:
                    # for start_time use min; for end_time use max as aggregate
                    dt = min(times) if key == 'start_time' else max(times)
            # Use type priority: research before non-research to prefer child producers
            type_priority = 0 if op == 'research' else 1
            # Use depth and id to stabilize ties
            return (dt or datetime.min, type_priority, self.depths.get(str(nid), 10**6), str(nid))
        return sorted(node_ids, key=time_key, reverse=reverse)

    def _order_bfs(self, node_ids: list[str]) -> list[str]:
        if not self.root_id:
            return node_ids
        allowed = set(node_ids)
        order: list[str] = []
        queue = deque([self.root_id])
        visited = set()
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            if nid in allowed:
                order.append(nid)
            for child in self.children.get(nid, []):
                if child not in visited:
                    queue.append(child)
        # Append any remaining nodes not connected
        for nid in node_ids:
            if nid not in visited:
                order.append(nid)
        return order

    def _order_dfs(self, node_ids: list[str]) -> list[str]:
        if not self.root_id:
            return node_ids
        allowed = set(node_ids)
        order: list[str] = []
        stack = [self.root_id]
        visited = set()
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            if nid in allowed:
                order.append(nid)
            # push children in reverse to keep file order where possible
            for child in reversed(self.children.get(nid, [])):
                if child not in visited:
                    stack.append(child)
        for nid in node_ids:
            if nid not in visited:
                order.append(nid)
        return order

    def compile_data(self, max_depth: int | None = None, ordering: str | None = None) -> dict:
        if not self.nodes:
            return {}
        
        # Select nodes by depth and ordering, skipping plan/aggregate nodes
        eligible_ids = self._eligible_node_ids(max_depth)
        ordered_ids = self._order_node_ids(eligible_ids, ordering or 'start_time_asc')

        # Extract relevant data from selected nodes
        research_data = {
            'learnings': [],
            'citations': {},
            'context': [],
            'visited_urls': [],
            'sources': [],
            'context': []
        }

        seen_learnings = set()
        seen_urls = set()
        seen_sources = set()
        research_learnings = set()

        for node_id in ordered_ids:
            node = self.nodes.get(str(node_id)) or {}
            op = node.get('operation', '')
            results = node.get('results', {}) or {}
            if op == "research":
                for learning in results.get('learnings', []) or []:
                    if learning not in seen_learnings:
                        research_data['learnings'].append(learning)
                        seen_learnings.add(learning)
                        research_learnings.add(learning)
                        cite = (results.get('citations', {}) or {}).get(learning)
                        if cite:
                            research_data['citations'][learning] = cite
                # context/sources may be saved under node-level as well
                if results.get('context'):
                    research_data['context'].extend(results.get('context', []) or [])
                if results.get('visited_urls'):
                    for u in (results.get('visited_urls', []) or []):
                        if u not in seen_urls:
                            research_data['visited_urls'].append(u)
                            seen_urls.add(u)
                if results.get('sources'):
                    for s in (results.get('sources', []) or []):
                        if s not in seen_sources:
                            research_data['sources'].append(s)
                            seen_sources.add(s)
                # also include any node-level visited_urls if present
                if node.get('visited_urls'):
                    for u in (node.get('visited_urls', []) or []):
                        if u not in seen_urls:
                            research_data['visited_urls'].append(u)
                            seen_urls.add(u)
            elif op == "research_execution":
                if results.get('context'):
                    research_data['context'].extend(results.get('context', []) or [])
            else:
                # Skip plan/aggregate nodes by default to avoid double counting
                pass

        return research_data

    async def generate_report(self, research_data: dict) -> str:
        if not self.nodes:
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
        context_with_citations = trim_context_to_word_limit(context_with_citations, max_words=self.config.max_context_words)
        
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

        return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a research report from progress data.")
    parser.add_argument('--progress', type=str, required=True, help='Path to the progress JSON file.')
    parser.add_argument('--config', type=str, required=True, help='Path to the configuration JSON file.')
    parser.add_argument('--output', type=str, required=True, help='Directory to write the output report file.')
    parser.add_argument('--max_depth', type=int, default=None, help='Maximum depth (distance from root) to include. Root has depth 0.')
    parser.add_argument('--ordering', type=str, default='start_time_asc',
                        choices=['start_time_asc','start_time_desc','end_time_asc','end_time_desc','dfs','bfs','random'],
                        help='Ordering strategy for node aggregation.')
    parser.add_argument('--root_id', type=str, default=None, help='Override root node id if not auto-detected.')

    args = parser.parse_args()
    
    generator = ReportGenerator(args.progress, args.config, root_id=args.root_id)
    stats = generator.get_tree_summary()
    print(f"Progress tree -> root_id: {stats['root_id']}, nodes: {stats['nodes']}, edges: {stats['edges']}, max_depth: {stats['max_depth']}")
    research_data = generator.compile_data(max_depth=args.max_depth, ordering=args.ordering)
    if args.max_depth is not None:
        try:
            eligible = len(generator._eligible_node_ids(args.max_depth))
            print(f"Selected nodes with max_depth={args.max_depth}: {eligible}")
        except Exception:
            pass
    try:
        uniq_learnings = len(set(research_data.get('learnings', [])))
        uniq_urls = len(set(research_data.get('visited_urls', [])))
        uniq_sources = len(set(research_data.get('sources', [])))
        print(f"Unique research results -> learnings: {uniq_learnings}, urls: {uniq_urls}, sources: {uniq_sources}")
    except Exception:
        pass
    report = asyncio.run(generator.generate_report(research_data))

    os.makedirs(args.output, exist_ok=True)
    with open(os.path.join(args.output, 'report.md'), 'w') as file:
        file.write(report)

    
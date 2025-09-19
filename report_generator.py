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
    def __init__(self, progress_file: str, config_file: str, root_id: str | None = None, random_seed: int | None = None):
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
        # Deterministic RNG if seed provided
        self.random_seed = random_seed
        self.rng = random.Random(random_seed) if random_seed is not None else random.Random()
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

    def _format_ascii_levels(self, levels: dict[int, list[str]], title: str) -> str:
        # Deprecated by _print_ascii_tree_summary but kept for compatibility; delegates to it without metadata
        lines: list[str] = []
        lines.append(title)
        max_level = max(levels.keys()) if levels else 0
        total = sum(len(v) for v in (levels or {}).values())
        lines.append(f"Layers: {max_level} | Total nodes: {total}")
        counts = ", ".join([f"L{lvl}={len(levels.get(lvl, []))}" for lvl in range(1, max_level + 1)]) if max_level else ""
        lines.append(f"Nodes per layer: {counts}")
        for lvl in range(1, max_level + 1):
            nodes = levels.get(lvl, [])
            sample = nodes[:10]
            more = f" ...( +{len(nodes) - len(sample)} more)" if len(nodes) > len(sample) else ""
            lines.append(f"L{lvl} [{len(nodes)}]: " + " ".join(sample) + more)
        return "\n".join(lines)

    def _print_ascii_tree_summary(self, stage: str, max_depth: int | None, max_breadth: int | None, levels: dict[int, list[str]]) -> None:
        # Standardized ASCII block for before/after filtering
        max_level = max(levels.keys()) if levels else 0
        total = sum(len(v) for v in (levels or {}).values())
        depth_str = str(max_depth) if max_depth is not None else "full"
        breadth_str = str(max_breadth) if max_breadth is not None else "none"
        counts = ", ".join([f"L{lvl}={len(levels.get(lvl, []))}" for lvl in range(1, max_level + 1)]) if max_level else ""
        print(f"=== Tree Summary ({stage}) ===")
        print(f"Depth limit: {depth_str} | Breadth limit: {breadth_str}")
        print(f"Layers: {max_level} | Total nodes: {total}")
        print(f"Nodes per layer: {counts}")
        for lvl in range(1, max_level + 1):
            nodes = levels.get(lvl, [])
            sample = nodes[:10]
            more = f" ...( +{len(nodes) - len(sample)} more)" if len(nodes) > len(sample) else ""
            print(f"L{lvl} [{len(nodes)}]: " + " ".join(sample) + more)

    def print_ascii_tree_all(self, max_depth: int | None = None) -> None:
        # Standardized summary BEFORE filtering
        levels = self._level_research_nodes(max_depth=max_depth)
        self._print_ascii_tree_summary(stage="BEFORE", max_depth=max_depth, max_breadth=None, levels=levels)

    def _select_research_nodes_by_breadth_levels(self, max_breadth: int, max_depth: int | None) -> dict[int, list[str]]:
        # Select research nodes per level using breadth sampling rule; returns per-level mapping
        if not self.depths:
            self._compute_depths()
        target_max_depth = max_depth if max_depth is not None else self.get_max_depth()
        levels = self._level_research_nodes(max_depth=target_max_depth)
        rng = self.rng
        selected: dict[int, list[str]] = {}
        if target_max_depth is None or target_max_depth <= 0:
            return {1: []}
        b_curr = int(max_breadth)
        lvl1_nodes = list(levels.get(1, []))
        if b_curr > 0 and lvl1_nodes:
            if len(lvl1_nodes) > b_curr:
                selected[1] = rng.sample(lvl1_nodes, b_curr)
            else:
                selected[1] = list(lvl1_nodes)
        else:
            selected[1] = []
        prev_b = b_curr
        for lvl in range(2, (target_max_depth or 0) + 1):
            next_b = max(2, prev_b // 2) if max_breadth > 1 else max_breadth
            chosen: list[str] = []
            for parent in selected.get(lvl - 1, []):
                candidates = self._research_children_next_level(parent, lvl)
                if not candidates:
                    continue
                k = min(next_b, len(candidates))
                if len(candidates) > k:
                    chosen.extend(rng.sample(candidates, k))
                else:
                    chosen.extend(candidates)
            # Deduplicate preserving order
            seen = set()
            deduped: list[str] = []
            for nid in chosen:
                if nid in seen:
                    continue
                seen.add(nid)
                deduped.append(nid)
            selected[lvl] = deduped
            prev_b = next_b
        return selected

    def print_ascii_tree_filtered(self, max_depth: int | None = None, max_breadth: int | None = None) -> None:
        # Print ASCII summary after applying depth and optional breadth filtering (research nodes only)
        target_max_depth = max_depth if max_depth is not None else self.get_max_depth()
        if max_breadth is None or max_breadth <= 0:
            levels = self._level_research_nodes(max_depth=target_max_depth)
            self._print_ascii_tree_summary(stage="AFTER", max_depth=target_max_depth, max_breadth=None, levels=levels)
            return
        levels = self._select_research_nodes_by_breadth_levels(max_breadth, target_max_depth)
        # Ensure all levels exist up to target_max_depth
        for lvl in range(1, (target_max_depth or 0) + 1):
            _ = levels.setdefault(lvl, [])
        self._print_ascii_tree_summary(stage="AFTER", max_depth=target_max_depth, max_breadth=max_breadth, levels=levels)

    def verify_breadth_filtered(self, max_depth: int | None, max_breadth: int | None) -> dict:
        # Verify counts after applying breadth filtering against theoretical counts from provided max_breadth
        if max_breadth is None or max_breadth <= 0:
            # Nothing to verify beyond depth-only; reuse pre-filter verification
            return self.verify_breadth(max_depth=max_depth)
        target_max_depth = max_depth if max_depth is not None else self.get_max_depth()
        levels = self._select_research_nodes_by_breadth_levels(int(max_breadth), target_max_depth)
        # Normalize levels to full depth range
        for lvl in range(1, (target_max_depth or 0) + 1):
            _ = levels.setdefault(lvl, [])
        actual = {lvl: len(nodes) for lvl, nodes in sorted(levels.items())}
        expected = self._expected_level_counts(int(max_breadth), target_max_depth or 0)
        report_levels = []
        all_ok = True
        for lvl in range(1, (target_max_depth or 0) + 1):
            a = int(actual.get(lvl, 0))
            e = int(expected.get(lvl, 0))
            ok = a == e
            if not ok:
                all_ok = False
            report_levels.append({'level': lvl, 'actual': a, 'expected': e, 'ok': ok})
        return {
            'max_depth': target_max_depth or 0,
            'max_breadth': int(max_breadth),
            'levels': report_levels,
            'ok': all_ok
        }

    def print_verify_breadth_filtered(self, max_depth: int | None = None, max_breadth: int | None = None) -> None:
        v = self.verify_breadth_filtered(max_depth=max_depth, max_breadth=max_breadth)
        parts = []
        for lv in v.get('levels', []):
            parts.append(f"L{lv['level']}: {lv['actual']} (exp {lv['expected']}{'' if lv['ok'] else '!)'})")
        print("Filtered breadth check -> " + ", ".join(parts))
    
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
            try:
                self.rng.shuffle(ids)
            except Exception:
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

    def _level_research_nodes(self, max_depth: int | None = None) -> dict[int, list[str]]:
        # Returns mapping: semantic depth -> list of research node ids at that depth (depth starts at 1)
        if not self.depths:
            self._compute_depths()
        target_max_depth = max_depth if max_depth is not None else self.get_max_depth()
        levels: dict[int, list[str]] = {}
        for nid, d in (self.depths or {}).items():
            if d is None or d == 0:
                continue
            if d > target_max_depth:
                continue
            node = self.nodes.get(str(nid), {})
            if node.get('operation') != 'research':
                continue
            levels.setdefault(int(d), []).append(str(nid))
        # Ensure all levels up to target_max_depth exist
        for lvl in range(1, (target_max_depth or 0) + 1):
            _ = levels.setdefault(lvl, [])
        return levels

    def _descendants(self, nid: str) -> list[str]:
        # All descendants (any operation) following edges
        nid = str(nid)
        result: list[str] = []
        stack = [nid]
        visited = set([nid])
        while stack:
            cur = stack.pop()
            for ch in self.children.get(str(cur), []):
                if ch in visited:
                    continue
                visited.add(ch)
                result.append(str(ch))
                stack.append(ch)
        return result

    def _research_children_next_level(self, parent_id: str, next_level: int) -> list[str]:
        # Research descendants of parent that are exactly one semantic level deeper
        parent_id = str(parent_id)
        target = int(next_level)
        result: list[str] = []
        for ch in self._descendants(parent_id):
            node = self.nodes.get(str(ch), {})
            if node.get('operation') != 'research':
                continue
            if self.depths.get(str(ch)) == target:
                result.append(str(ch))
        return result

    def get_breadth_counts(self, max_depth: int | None = None) -> dict[int, int]:
        levels = self._level_research_nodes(max_depth=max_depth)
        return {lvl: len(nodes) for lvl, nodes in sorted(levels.items())}

    def _expected_level_counts(self, initial_breadth: int, max_depth: int) -> dict[int, int]:
        # Compute expected total nodes per level using iterative halving rule with floor and minimum of 2 per deep_research
        counts: dict[int, int] = {}
        if initial_breadth <= 0 or max_depth <= 0:
            return {lvl: 0 for lvl in range(1, max_depth + 1)}
        b = int(initial_breadth)
        cumulative = 1
        for lvl in range(1, max_depth + 1):
            if lvl == 1:
                cumulative = b
            else:
                b = max(2, b // 2) if initial_breadth > 1 else initial_breadth
                cumulative *= b
            counts[lvl] = cumulative
        return counts

    def verify_breadth(self, max_depth: int | None = None) -> dict:
        # Verify actual per-level counts against expected counts derived from level 1 breadth
        target_max_depth = max_depth if max_depth is not None else self.get_max_depth()
        actual = self.get_breadth_counts(max_depth=target_max_depth)
        initial_breadth = int(actual.get(1, 0))
        expected = self._expected_level_counts(initial_breadth, target_max_depth or 0)
        levels_report = []
        all_ok = True
        for lvl in range(1, (target_max_depth or 0) + 1):
            a = int(actual.get(lvl, 0))
            e = int(expected.get(lvl, 0))
            ok = a == e
            if not ok:
                all_ok = False
            levels_report.append({
                'level': lvl,
                'actual': a,
                'expected': e,
                'ok': ok
            })
        return {
            'max_depth': target_max_depth or 0,
            'initial_breadth': initial_breadth,
            'levels': levels_report,
            'ok': all_ok
        }

    def assert_breadth(self, max_depth: int | None = None) -> None:
        v = self.verify_breadth(max_depth=max_depth)
        if not v.get('ok', False):
            parts = []
            for lv in v.get('levels', []):
                if not lv.get('ok', False):
                    parts.append(f"L{lv['level']}: {lv['actual']} vs expected {lv['expected']}")
            details = ", ".join(parts)
            raise ValueError(f"Breadth verification failed (before filtering). {details}")

    def _select_nodes_by_breadth(self, max_breadth: int, max_depth: int | None) -> list[str]:
        # Select research nodes according to breadth sampling per level. Also include their research_execution descendants.
        if not self.depths:
            self._compute_depths()
        target_max_depth = max_depth if max_depth is not None else self.get_max_depth()
        if not target_max_depth:
            return []
        # Build mapping of research nodes by level
        levels = self._level_research_nodes(max_depth=target_max_depth)
        # Level 1 selection
        rng = self.rng
        selected_by_level: dict[int, list[str]] = {}
        b_curr = int(max_breadth)
        lvl1_nodes = list(levels.get(1, []))
        if b_curr <= 0 or not lvl1_nodes:
            return []
        if len(lvl1_nodes) > b_curr:
            selected_by_level[1] = rng.sample(lvl1_nodes, b_curr)
        else:
            selected_by_level[1] = list(lvl1_nodes)
        # Deeper levels
        prev_b = b_curr
        for lvl in range(2, (target_max_depth or 0) + 1):
            next_b = max(2, prev_b // 2) if max_breadth > 1 else max_breadth
            chosen: list[str] = []
            for parent in selected_by_level.get(lvl - 1, []):
                candidates = self._research_children_next_level(parent, lvl)
                if not candidates:
                    continue
                k = min(next_b, len(candidates))
                if len(candidates) > k:
                    chosen.extend(rng.sample(candidates, k))
                else:
                    chosen.extend(candidates)
            # Deduplicate preserving order
            seen = set()
            deduped: list[str] = []
            for nid in chosen:
                if nid in seen:
                    continue
                seen.add(nid)
                deduped.append(nid)
            selected_by_level[lvl] = deduped
            prev_b = next_b
        # Aggregate selected research nodes
        selected_research: list[str] = []
        for lvl in range(1, (target_max_depth or 0) + 1):
            selected_research.extend(selected_by_level.get(lvl, []))
        # Include research_execution descendants of selected research nodes
        include_ids: set[str] = set(selected_research)
        for rid in selected_research:
            for d in self._descendants(rid):
                node = self.nodes.get(str(d), {})
                if node.get('operation') == 'research_execution':
                    include_ids.add(str(d))
        return list(include_ids)

    def compile_data(self, max_depth: int | None = None, ordering: str | None = None, max_breadth: int | None = None) -> dict:
        if not self.nodes:
            return {}
        
        # Select nodes by depth and ordering, skipping plan/aggregate nodes
        eligible_ids = self._eligible_node_ids(max_depth)
        eligible_set = set(eligible_ids)
        # Apply breadth sampling if requested
        if isinstance(max_breadth, int) and max_breadth is not None and max_breadth > 0:
            target_max_depth = max_depth if max_depth is not None else self.get_max_depth()
            selected_ids = self._select_nodes_by_breadth(max_breadth, target_max_depth)
            # Keep only eligible
            selected_set = {str(nid) for nid in selected_ids if str(nid) in eligible_set}
            # Order all eligible then filter to selected to keep stable ordering strategy
            ordered_all = self._order_node_ids(list(eligible_set), ordering or 'start_time_asc')
            ordered_ids = [nid for nid in ordered_all if str(nid) in selected_set]
        else:
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
    parser.add_argument('--max_breadth', type=int, default=None, help='Limit breadth per level via sampling (level1=B, level2=max(2,B//2) per parent, etc.).')
    parser.add_argument('--random_seed', type=int, default=42, help='Random seed for deterministic sampling and ordering.')

    args = parser.parse_args()
    
    generator = ReportGenerator(args.progress, args.config, root_id=args.root_id, random_seed=args.random_seed)
    stats = generator.get_tree_summary()
    print(f"Progress tree -> root_id: {stats['root_id']}, nodes: {stats['nodes']}, edges: {stats['edges']}, max_depth: {stats['max_depth']}")
    # ASCII summary before filtering
    try:
        generator.print_ascii_tree_all(max_depth=args.max_depth)
    except Exception:
        pass
    # Breadth verification
    try:
        verification = generator.verify_breadth(max_depth=args.max_depth)
        lv_summ = ", ".join([f"L{lv['level']}: {lv['actual']} (exp {lv['expected']}{'' if lv['ok'] else '!)'})" for lv in verification.get('levels', [])])
        print(f"Breadth by level -> {lv_summ}")
        # Raise if the pre-filter breadth is inconsistent
        generator.assert_breadth(max_depth=args.max_depth)
    except Exception as e:
        raise
    if args.max_breadth is not None:
        print(f"Applying max_breadth={args.max_breadth}")
    research_data = generator.compile_data(max_depth=args.max_depth, ordering=args.ordering, max_breadth=args.max_breadth)
    # ASCII summary after filtering (depth/breadth)
    try:
        generator.print_ascii_tree_filtered(max_depth=args.max_depth, max_breadth=args.max_breadth)
    except Exception:
        pass
    # Verify filtered breadth strictly
    try:
        generator.print_verify_breadth_filtered(max_depth=args.max_depth, max_breadth=args.max_breadth)
        generator.assert_breadth_filtered(max_depth=args.max_depth, max_breadth=args.max_breadth)
    except Exception as e:
        raise
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

    
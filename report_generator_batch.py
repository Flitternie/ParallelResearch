import os
import json
import asyncio
import argparse
from typing import List, Tuple, Optional
from report_generator import ReportGenerator

os.environ["OPENAI_API_KEY"] = open("./openai.key").read().strip()
os.environ["OPENAI_BASE_URL"] = open("openai_url.key").read().strip()

def find_progress_files(root_dir: str) -> List[str]:
    results: List[str] = []
    for dirpath, _, filenames in os.walk(root_dir):
        if 'progress.json' in filenames:
            results.append(os.path.join(dirpath, 'progress.json'))
    return sorted(results)


def parse_ids_from_path(progress_path: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    # Expected pattern: <root>/logs/<question_id>/run_<i>/try_<j>/progress.json
    parts = progress_path.replace('\\', '/').split('/')
    try:
        logs_idx = max(i for i, p in enumerate(parts) if p == 'logs')
    except ValueError:
        return None, None, None
    question_id = parts[logs_idx + 1] if len(parts) > logs_idx + 1 else None
    run_part = parts[logs_idx + 2] if len(parts) > logs_idx + 2 else ''
    try_part = parts[logs_idx + 3] if len(parts) > logs_idx + 3 else ''
    run_idx = None
    try_idx = None
    if run_part.startswith('run_'):
        try:
            run_idx = int(run_part.split('_', 1)[1])
        except Exception:
            run_idx = None
    if try_part.startswith('try_'):
        try:
            try_idx = int(try_part.split('_', 1)[1])
        except Exception:
            try_idx = None
    return question_id, run_idx, try_idx


async def process_one(progress_path: str, args, out_lock: asyncio.Lock, semaphore: asyncio.Semaphore) -> Optional[str]:
    async with semaphore:
        question_id, run_idx, try_idx = parse_ids_from_path(progress_path)
        if not question_id:
            print(f"Skipping (unrecognized path structure): {progress_path}")
            return None

        print(f"\nProcessing: {progress_path}")
        print(f"Question: {question_id} | run: {run_idx} | try: {try_idx}")

        # Determine output file path early and skip if it already exists
        if run_idx is not None:
            out_name = f"{question_id}_run_{run_idx}.a"
        else:
            out_name = f"{question_id}.a"
        out_path = os.path.join(args.output, out_name)
        if os.path.exists(out_path):
            print(f"Skipping (output already exists): {out_path}")
            return None

        generator = ReportGenerator(progress_path, args.config, root_id=args.root_id, random_seed=args.random_seed)
        stats = generator.get_tree_summary()
        print(f"Progress tree -> root_id: {stats['root_id']}, nodes: {stats['nodes']}, edges: {stats['edges']}, max_depth: {stats['max_depth']}")
        # ASCII summary before filtering
        try:
            generator.print_ascii_tree_all(max_depth=args.max_depth)
        except Exception:
            pass
        # Verify breadth distribution per level
        try:
            verification = generator.verify_breadth(max_depth=args.max_depth)
            lv_summ = ", ".join([f"L{lv['level']}: {lv['actual']} (exp {lv['expected']}{'' if lv['ok'] else '!)'})" for lv in verification.get('levels', [])])
            print(f"Breadth by level -> {lv_summ}")
        except Exception:
            pass

        if args.max_breadth is not None:
            print(f"Applying max_breadth={args.max_breadth}")
        research_data = generator.compile_data(max_depth=args.max_depth, ordering=args.ordering, max_breadth=args.max_breadth)
        # ASCII summary after filtering (depth/breadth)
        try:
            generator.print_ascii_tree_filtered(max_depth=args.max_depth, max_breadth=args.max_breadth)
        except Exception:
            pass
        # Verification after filtering
        try:
            generator.print_verify_breadth_filtered(max_depth=args.max_depth, max_breadth=args.max_breadth)
        except Exception:
            pass
        # Verify breadth distribution per level
        try:
            verification = generator.verify_breadth(max_depth=args.max_depth)
            lv_summ = ", ".join([f"L{lv['level']}: {lv['actual']} (exp {lv['expected']}{'' if lv['ok'] else '!)'})" for lv in verification.get('levels', [])])
            print(f"Breadth by level -> {lv_summ}")
        except Exception:
            pass
        
        try:
            uniq_learnings = len(set(research_data.get('learnings', [])))
            uniq_urls = len(set(research_data.get('visited_urls', [])))
            uniq_sources = len(set(research_data.get('sources', [])))
            print(f"Unique research results -> learnings: {uniq_learnings}, urls: {uniq_urls}, sources: {uniq_sources}")
        except Exception:
            pass

        report = await generator.generate_report(research_data)

        async with out_lock:
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(report)
        return out_path


async def main_async():
    parser = argparse.ArgumentParser(description="Batch-generate research reports from multiple progress.json files under a directory.")
    parser.add_argument('--logs_root', type=str, required=True, help='Root directory containing logs subfolders with progress.json files.')
    parser.add_argument('--config', type=str, required=True, help='Path to the configuration JSON file used for report generation.')
    parser.add_argument('--output', type=str, required=True, help='Directory to write output .a files.')
    parser.add_argument('--max_depth', type=int, default=None, help='Maximum depth (distance from root) to include. Root has depth 0.')
    parser.add_argument('--ordering', type=str, default='start_time_asc',
                        choices=['start_time_asc','start_time_desc','end_time_asc','end_time_desc','dfs','bfs','random'],
                        help='Ordering strategy for node aggregation.')
    parser.add_argument('--root_id', type=str, default=None, help='Override root node id if not auto-detected.')
    parser.add_argument('--max_breadth', type=int, default=None, help='Limit breadth per level via sampling (level1=B, level2=max(2,B//2) per parent, etc.).')
    parser.add_argument('--concurrency', type=int, default=16, help='Maximum number of reports to generate concurrently.')
    parser.add_argument('--random_seed', type=int, default=42, help='Random seed for deterministic sampling and ordering.')

    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    progress_files = find_progress_files(args.logs_root)
    progress_files = progress_files
    print(f"Found {len(progress_files)} progress.json files under {args.logs_root}")

    if not progress_files:
        print("No progress.json files found.")
        return

    out_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(max(1, args.concurrency))

    tasks = [process_one(p, args, out_lock, semaphore) for p in progress_files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    written = [r for r in results if isinstance(r, str)]
    errors = [r for r in results if isinstance(r, Exception)]
    print(f"\nCompleted generating {len(written)} reports to {args.output}")
    if errors:
        print(f"{len(errors)} tasks encountered errors.")


if __name__ == "__main__":
    asyncio.run(main_async())

    
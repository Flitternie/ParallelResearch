# ADOBE CONFIDENTIAL
#
# Copyright 2026 Adobe
# All Rights Reserved.
#
# NOTICE: All information contained herein is, and remains
# the property of Adobe and its suppliers, if any. The intellectual
# and technical concepts contained herein are proprietary to Adobe
# and its suppliers and are protected by all applicable intellectual
# property laws, including trade secret and copyright laws.
# Dissemination of this information or reproduction of this material
# is strictly forbidden unless prior written permission is obtained
# from Adobe.

import os
import json
import asyncio
import argparse
import statistics
import math
from typing import List, Tuple, Optional
from utils.report_generator import ReportGenerator

os.environ["OPENAI_API_KEY"] = open("./keys/openai.key").read().strip()
os.environ["OPENAI_BASE_URL"] = open("./keys/openai_url.key").read().strip()

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


def count_eligible_nodes(progress_path: str, max_depth: Optional[int], config: str, root_id: Optional[str], random_seed: Optional[int]) -> int:
    try:
        generator = ReportGenerator(progress_path, config, root_id=root_id, random_seed=random_seed)
        eligible = generator._eligible_node_ids(max_depth)
        return len(eligible)
    except Exception as e:
        print(f"Failed to count eligible nodes for {progress_path}: {e}")
        return 0


def _render_progress_bar(completed: int, total: int, successes: int, errors: int, width: int = 40) -> str:
    total = max(1, int(total))
    completed = max(0, min(int(completed), int(total)))
    filled = int(width * completed / total)
    bar = ('#' * filled) + ('-' * (width - filled))
    return f"[{bar}] {completed}/{total} | ok:{successes} err:{errors}"


async def process_one(progress_path: str, args, out_lock: asyncio.Lock, semaphore: asyncio.Semaphore) -> Optional[str]:
    async with semaphore:
        question_id, run_idx, try_idx = parse_ids_from_path(progress_path)
        if not question_id:
            print(f"Skipping (unrecognized path structure): {progress_path}")
            return None

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
        
        has_filters = (args.max_depth is not None) or (args.max_breadth is not None)
        if has_filters:
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

        if has_filters:
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
        except Exception:
            pass

        report = await generator.generate_report(research_data)

        async with out_lock:
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(report)
        return out_path


async def main_async():
    parser = argparse.ArgumentParser(description="Batch-generate research reports from multiple progress.json files under a directory.")
    parser.add_argument('--question_dir', type=str, default=None, help='Directory containing [qid].q files to filter which questions to process.')
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
    parser.add_argument('--analysis', action='store_true', help='If set, perform pre-scan analysis and print statistics without generating reports.')

    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    progress_files = find_progress_files(args.logs_root)
    print(f"Found {len(progress_files)} progress.json files under {args.logs_root}")

    # If a question_dir is provided, scan for [qid].q files and filter progress files accordingly
    if args.question_dir:
        if not os.path.isdir(args.question_dir):
            print(f"--question_dir does not exist or is not a directory: {args.question_dir}")
            return
        qids = {os.path.splitext(fname)[0] for fname in os.listdir(args.question_dir)
                if os.path.isfile(os.path.join(args.question_dir, fname)) and os.path.splitext(fname)[1] == '.q'}
        print(f"Loaded {len(qids)} qids from {args.question_dir}")
        if not qids:
            print(f"No .q files found under {args.question_dir}. Nothing to do.")
            return
        before = len(progress_files)
        filtered: List[str] = []
        for p in progress_files:
            qid, _, _ = parse_ids_from_path(p)
            if qid and qid in qids:
                filtered.append(p)
        progress_files = filtered
        print(f"Filtered to {len(progress_files)} progress.json files matching {len(qids)} qids from {args.question_dir} (from {before}).")

    if not progress_files:
        print("No progress.json files found.")
        return

    # Pre-scan to compute average number of eligible nodes per progress file
    eligible_counts = []
    for p in progress_files:
        eligible_counts.append(count_eligible_nodes(p, args.max_depth, args.config, args.root_id, args.random_seed))
    avg_eligible = statistics.mean(eligible_counts) if eligible_counts else 0
    sd_eligible = statistics.stdev(eligible_counts) if len(eligible_counts) > 1 else 0
    ci_eligible = 1.96 * sd_eligible / math.sqrt(len(eligible_counts)) if len(eligible_counts) > 1 else 0
    print(f"Average eligible nodes across {len(progress_files)} files: {avg_eligible:.2f} ± {ci_eligible:.2f}, std={sd_eligible:.2f}")

    # Pre-scan to compute average unique learnings and citations per progress file
    learnings_counts = []
    citations_counts = []
    for p in progress_files:
        try:
            generator = ReportGenerator(p, args.config, root_id=args.root_id, random_seed=args.random_seed)
            research_data = generator.compile_data(max_depth=args.max_depth, ordering=args.ordering, max_breadth=args.max_breadth)
            num_learnings = len(set(research_data.get('learnings', []) or []))
            num_citations = len((research_data.get('citations', {}) or {}))
            learnings_counts.append(num_learnings)
            citations_counts.append(num_citations)
        except Exception as e:
            print(f"Failed to compile data for {p}: {e}")
    if learnings_counts:
        avg_learnings = statistics.mean(learnings_counts)
        sd_learnings = statistics.stdev(learnings_counts) if len(learnings_counts) > 1 else 0
        ci_learnings = 1.96 * sd_learnings / math.sqrt(len(learnings_counts)) if len(learnings_counts) > 1 else 0
        print(f"Average unique learnings across {len(learnings_counts)} files: {avg_learnings:.2f} ± {ci_learnings:.2f}, std={sd_learnings:.2f}")
    if citations_counts:
        avg_citations = statistics.mean(citations_counts)
        sd_citations = statistics.stdev(citations_counts) if len(citations_counts) > 1 else 0
        ci_citations = 1.96 * sd_citations / math.sqrt(len(citations_counts)) if len(citations_counts) > 1 else 0
        print(f"Average citations across {len(citations_counts)} files: {avg_citations:.2f} ± {ci_citations:.2f}, std={sd_citations:.2f}")

    if args.analysis:
        return

    out_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(max(1, args.concurrency))

    # if the files are already in the output directory, skip them
    skipped_files = []
    for p in progress_files:
        question_id, run_idx, try_idx = parse_ids_from_path(p)
        out_name = f"{question_id}_run_{run_idx}.a"
        out_path = os.path.join(args.output, out_name)
        if os.path.exists(out_path):
            skipped_files.append(p)
            progress_files.remove(p)
    print(f"Skipped {len(skipped_files)} files that already have outputs in {args.output}")

    tasks = [asyncio.create_task(process_one(p, args, out_lock, semaphore)) for p in progress_files]
    total = len(tasks)
    completed = 0
    successes = 0
    errors_count = 0
    results = []
    # Progress loop
    print("")
    for fut in asyncio.as_completed(tasks):
        try:
            r = await fut
            results.append(r)
            if isinstance(r, str):
                successes += 1
        except Exception as e:
            results.append(e)
            errors_count += 1
        finally:
            completed += 1
            bar = _render_progress_bar(completed, total, successes, errors_count)
            print(f"\r{bar}", end='', flush=True)
    print("")

    written = [r for r in results if isinstance(r, str)]
    errors = [r for r in results if isinstance(r, Exception)]
    print(f"\nCompleted generating {len(written)} reports to {args.output}")
    if errors:
        print(f"{len(errors)} tasks encountered errors.")


if __name__ == "__main__":
    asyncio.run(main_async())


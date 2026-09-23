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
import io
import sys
import json
import time
import argparse
import asyncio
import logging
import multiprocessing as mp
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

# Progress bar
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


# -------------------------
# Types
# -------------------------

@dataclass
class Task:
    task_id: int
    prompt: str


@dataclass
class TaskResult:
    task_id: int
    prompt: str
    success: bool
    article: str
    error_message: str
    duration_seconds: float


# -------------------------
# Utilities
# -------------------------

def setup_environment() -> None:
    """Setup environment variables for API keys (match batch_deep_research.py behavior)."""
    try:
        # Force-set to override any pre-existing env that could be incorrect
        os.environ["OPENAI_API_KEY"] = open("./keys/openai.key").read().strip()
        os.environ["OPENAI_BASE_URL"] = open("keys/openai_url.key").read().strip()
        os.environ["CUSTOM_EMBED_API_KEY"] = ""
        os.environ["CUSTOM_EMBED_BASE_URL"] = "http://0.0.0.0:8000/v1/"
        os.environ["FINEWEB_API_KEY"] = open("./keys/fineweb.key").read().strip()
    except FileNotFoundError as e:
        raise RuntimeError(f"Missing API key file: {e}")


async def process_single_task(
    task: Task,
    config_path: str,
    logs_dir: str,
    DeepResearch: Any,
    timeout: Optional[float] = None,
    attempt_num: int = 1,
) -> TaskResult:
    """Run DeepResearch for a single benchmark task, with per-attempt logging and optional timeout."""
    start_time = time.time()

    # Prepare logging per attempt
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, f"task_{task.task_id}_try_{attempt_num}.log")

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    root_logger.setLevel(logging.DEBUG)

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()

    try:
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            deep_researcher = DeepResearch(
                query=task.prompt,
                config_path=config_path,
                logs_dir=logs_dir,
            )

            root_logger.info(f"Starting research for task_id={task.task_id} (attempt {attempt_num})")
            if timeout and timeout > 0:
                article = await asyncio.wait_for(deep_researcher.run(), timeout=timeout)
            else:
                article = await deep_researcher.run()
            root_logger.info(f"Research completed for task_id={task.task_id} (attempt {attempt_num})")

    finally:
        stdout_content = stdout_buffer.getvalue()
        stderr_content = stderr_buffer.getvalue()

        if stdout_content:
            root_logger.info("=== CAPTURED STDOUT ===")
            for line in stdout_content.splitlines():
                root_logger.info(f"STDOUT: {line}")

        if stderr_content:
            root_logger.error("=== CAPTURED STDERR ===")
            for line in stderr_content.splitlines():
                root_logger.error(f"STDERR: {line}")

    duration = time.time() - start_time
    return TaskResult(task.task_id, task.prompt, True, article, "", duration)


def run_task_worker(args: Tuple[Task, str, str, float, int, float, str]) -> TaskResult:
    """Worker wrapper to execute a single task with retries."""
    task, config_path, model_logs_dir, timeout, retries, retry_delay, version = args

    try:
        setup_environment()

        # Import DeepResearch per version
        if version == "baseline":
            from flashresearch import DeepResearch
        elif version == "parallel":
            from flashresearch import RecursiveDeepResearch as DeepResearch
        elif version == "runtime":
            from flashresearch import FlashResearchRuntime as DeepResearch
        elif version == "flash":
            from flashresearch import FlashResearch as DeepResearch

        last_error = ""
        for attempt in range(1, max(1, int(retries)) + 1):
            attempt_start = time.time()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    process_single_task(
                        task=task,
                        config_path=config_path,
                        logs_dir=os.path.join(model_logs_dir, f"id_{task.task_id}", f"try_{attempt}"),
                        DeepResearch=DeepResearch,
                        timeout=timeout if timeout and timeout > 0 else None,
                        attempt_num=attempt,
                    )
                )
            except asyncio.TimeoutError:
                last_error = f"Timeout after {timeout}s while processing task_id={task.task_id}"
                result = TaskResult(task.task_id, task.prompt, False, "", last_error, time.time() - attempt_start)
            except Exception as e:
                last_error = f"Error processing task_id={task.task_id}: {str(e)}"
                result = TaskResult(task.task_id, task.prompt, False, "", last_error, time.time() - attempt_start)
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

            if result.success:
                return result

            is_timeout = last_error.startswith("Timeout")
            if not is_timeout or attempt >= max(1, int(retries)):
                return result

            try:
                time.sleep(max(0.0, float(retry_delay)))
            except Exception:
                pass

    except Exception as e:
        return TaskResult(task.task_id, task.prompt, False, "", f"Process-level error: {str(e)}", 0.0)


def read_jsonl_tasks(input_path: str, language_filter: Optional[str] = None) -> List[Task]:
    tasks: List[Task] = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)

            # Optional language filter (e.g., only 'en')
            if language_filter:
                lang = str(obj.get('language', '')).lower()
                if lang != str(language_filter).lower():
                    continue

            raw_id = obj.get('id')
            try:
                task_id = int(raw_id)
            except (TypeError, ValueError):
                # Skip records without a valid integer id
                continue

            prompt = obj.get('prompt', '')
            if not prompt:
                continue
            tasks.append(Task(task_id=task_id, prompt=prompt))
    return tasks


def load_existing_ids(output_file: str) -> List[int]:
    if not os.path.exists(output_file):
        return []
    existing: List[int] = []
    with open(output_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                obj = json.loads(line)
                existing.append(int(obj.get('id')))
            except Exception:
                continue
    return existing


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Deep Research Agent on benchmark JSONL and save outputs in required format")
    parser.add_argument("--input", dest="input", default="./deep_research_bench/data/prompt_data/query.jsonl", help="Path to input query.jsonl")
    parser.add_argument("--config", dest="config", default="./config.json", help="Path to config.json file")
    parser.add_argument("--output_dir", dest="output_dir", help="Base output directory")
    parser.add_argument("--model_name", dest="model_name", required=True, help="Model name used for output filename and logs directory")
    parser.add_argument("--workers", type=int, default=16, help="Number of worker processes")
    parser.add_argument("--timeout", type=int, default=3600, help="Per-task timeout in seconds; 0 disables timeout")
    parser.add_argument("--retries", type=int, default=3, help="Retries on timeout per task")
    parser.add_argument("--retry_delay", type=float, default=1.0, help="Delay between retries in seconds")
    parser.add_argument("--version", type=str, choices=["baseline", "parallel", "runtime", "flash"], help="DeepResearch implementation version to use")
    parser.add_argument("--language", type=str, default="en", choices=["en", "zh"], help="Filter tasks by language (default: en)")
    args = parser.parse_args()

    # Validate/resolve input path
    input_path = args.input
    if not os.path.isfile(input_path):
        # Fallback to repo path if provided path missing
        fallback = os.path.join("deep_research_bench", "data", "prompt_data", "query.jsonl")
        if os.path.isfile(fallback):
            input_path = fallback
        else:
            raise FileNotFoundError(f"Input JSONL not found: {args.input}")

    # Prepare output paths
    output_dir = args.output_dir
    model_name = args.model_name
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{model_name}.jsonl")
    model_logs_dir = os.path.join(output_dir, "logs", model_name)
    os.makedirs(model_logs_dir, exist_ok=True)

    # Load tasks (filter by language if specified)
    tasks = read_jsonl_tasks(input_path, language_filter=args.language)
    print(f"Loaded {len(tasks)} tasks (language={args.language}) from {input_path}")

    # Resume support: skip existing ids
    existing_ids = set(load_existing_ids(output_file))
    if existing_ids:
        tasks = [t for t in tasks if t.task_id not in existing_ids]
        print(f"Resuming: {len(existing_ids)} already completed, {len(tasks)} remaining")

    if not tasks:
        print("Nothing to process. Exiting.")
        return

    # Environment in parent (for immediate failures early)
    setup_environment()

    # Multiprocessing setup
    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    num_processes = min(int(args.workers), mp.cpu_count())
    print(f"Using {num_processes} worker processes")
    print(f"Writing outputs to: {output_file}")
    print(f"Logs directory: {model_logs_dir}")

    process_args: List[Tuple[Task, str, str, float, int, float, str]] = [
        (
            task,
            args.config,
            model_logs_dir,
            float(args.timeout) if args.timeout and args.timeout > 0 else 0.0,
            int(args.retries),
            float(args.retry_delay),
            args.version,
        )
        for task in tasks
    ]

    # Process and write outputs as they complete
    start_time = time.time()
    completed = 0
    failed = 0

    # Open output file in append mode once
    ensure_parent_dir(output_file)

    total_tasks = len(tasks)
    use_tqdm = tqdm is not None and total_tasks > 0
    progress_bar = tqdm(total=total_tasks, desc="Processing tasks", unit="task") if use_tqdm else None

    with open(output_file, 'a', encoding='utf-8') as outf:
        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=num_processes, maxtasksperchild=1) as pool:
            for result in pool.imap_unordered(run_task_worker, process_args):
                if result.success:
                    record = {
                        "id": result.task_id,
                        "prompt": result.prompt,
                        "article": result.article,
                    }
                    json_line = json.dumps(record, ensure_ascii=False)
                    outf.write(json_line + "\n")
                    outf.flush()
                    completed += 1
                else:
                    failed += 1
                if progress_bar:
                    progress_bar.update(1)
                elif (completed + failed) % 5 == 0:
                    print(f"Progress: done={completed}, failed={failed}, total={completed+failed}/{total_tasks}")
    if progress_bar:
        progress_bar.close()

    total_time = time.time() - start_time
    print("=== RUN COMPLETE ===")
    print(f"Completed: {completed}")
    print(f"Failed: {failed}")
    print(f"Output file: {output_file}")
    print(f"Total time: {total_time:.2f}s")


if __name__ == "__main__":
    main()


import os
import time
import argparse
import logging
import asyncio
import multiprocessing as mp
from pathlib import Path
from typing import List, Tuple, NamedTuple
import glob
import sys
import io
from contextlib import redirect_stdout, redirect_stderr
import csv
import threading
from tqdm import tqdm
import json


class ProcessResult(NamedTuple):
    """Result of processing a single question"""
    question_file: str
    run_index: int
    success: bool
    error_message: str
    duration_seconds: float


# Global lock for CSV writing
csv_lock = threading.Lock()

def write_to_csv(csv_file_path: str, result: ProcessResult):
    """Thread-safe function to write a single result to CSV"""
    with csv_lock:
        file_exists = os.path.exists(csv_file_path)
        with open(csv_file_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # Write header only if file doesn't exist and is empty
            if not file_exists:
                writer.writerow(["question_file", "run_index", "duration_seconds", "status", "error_message"])
            elif file_exists and os.path.getsize(csv_file_path) == 0:
                writer.writerow(["question_file", "run_index", "duration_seconds", "status", "error_message"])
            
            # Write the result
            status = "success" if result.success else "failed"
            error_msg = result.error_message.replace(',', ';').replace('\n', ' ')  # Clean CSV format
            writer.writerow([Path(result.question_file).name, result.run_index, f"{result.duration_seconds:.2f}", status, error_msg])


def setup_environment():
    """Setup environment variables for API keys"""
    try:
        os.environ["OPENAI_API_KEY"] = open("./openai.key").read().strip()
        os.environ["OPENAI_BASE_URL"] = open("openai_url.key").read().strip()
        os.environ["BRAVE_API_KEY"] = open("./brave.key").read().strip()
        os.environ["CUSTOM_EMBED_API_KEY"] = open("./openai.key").read().strip()
        os.environ["CUSTOM_EMBED_BASE_URL"] = "http://0.0.0.0:8000/v1/"
        # os.environ["CUSTOM_EMBED_BASE_URL"] = open("openai_url.key").read().strip()
    except FileNotFoundError as e:
        raise RuntimeError(f"Missing API key file: {e}")


async def process_single_question(question_file: str, output: str, config_path: str, run_index: int, DeepResearch, timeout: float | None = None, attempt_num: int = 1) -> ProcessResult:
    """Process a single question file and generate research report
    
    Args:
        question_file: Path to the .q file containing the question
        output: Directory to save the output .a file
        config_path: Path to the config.json file
    run_index: 1-based index of the run for repeated measurements
        
    Returns:
        ProcessResult with question_file, success, error_message, and duration
    """
    start_time = time.time()
    
    try:
        # Read the question from the file
        with open(question_file, 'r', encoding='utf-8') as f:
            question = f.read().strip()

        if not question:
            duration = time.time() - start_time
            return ProcessResult(question_file, run_index, False, "Empty question file", duration)

        # Create output filename (.a file)
        base_name = Path(question_file).stem
        output_file = os.path.join(output, f"{base_name}_run_{run_index}.a")

        # Create logs directory for this specific research (separate per attempt)
        logs_dir = os.path.join(output, "logs", base_name, f"run_{run_index}", f"try_{attempt_num}")
        os.makedirs(logs_dir, exist_ok=True)

        # Setup logging for this process - capture ALL logging
        log_file = os.path.join(logs_dir, f"run_{run_index}_try_{attempt_num}.log")

        # Configure root logger to capture everything
        root_logger = logging.getLogger()
        root_logger.handlers.clear()  # Clear any existing handlers

        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        root_logger.setLevel(logging.DEBUG)

        # Create string buffers to capture stdout/stderr
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()

        try:
            # Redirect stdout and stderr to capture all console output
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                # Initialize deep researcher
                deep_researcher = DeepResearch(
                    query=question,
                    config_path=config_path,
                    logs_dir=logs_dir
                )

                # Run the research
                root_logger.info(f"Starting research for: {question_file} (run {run_index}, attempt {attempt_num})")
                # Enforce a per-task timeout to prevent hangs
                if timeout and timeout > 0:
                    report = await asyncio.wait_for(deep_researcher.run(), timeout=timeout)
                else:
                    report = await deep_researcher.run()
                root_logger.info(f"Research completed for: {question_file} (run {run_index}, attempt {attempt_num})")

        finally:
            # Write captured stdout/stderr to log file
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

        # Save the report
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report)

        duration = time.time() - start_time
        root_logger.info(f"Completed research for {question_file} (run {run_index}, attempt {attempt_num}) in {duration:.2f}s")
        return ProcessResult(question_file, run_index, True, "", duration)
        
    except asyncio.TimeoutError:
        duration = time.time() - start_time
        error_msg = f"Timeout after {timeout}s while processing {question_file}"
        try:
            logging.error(error_msg)
        except:
            pass
        return ProcessResult(question_file, run_index, False, error_msg, duration)
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Error processing {question_file}: {str(e)}"
        
        # Try to log the error if logger is available
        try:
            logging.error(error_msg)
        except:
            pass
            
        return ProcessResult(question_file, run_index, False, error_msg, duration)


def run_single_process(args: Tuple[str, str, str, str, int, float | None, int, float, str]) -> ProcessResult:
    """Wrapper function to run async process_single_question in a separate process"""
    question_file, output, config_path, csv_file_path, run_index, timeout, retries, retry_delay, version = args
    
    try:
        # Setup environment in each process
        setup_environment()
        
        # Import DeepResearch in each process based on version
        if version == "baseline":
            from modified_deep_research import DeepResearch
        elif version == "parallel":
            from recursive_deep_research import RecursiveDeepResearch as DeepResearch
        elif version == "runtime":
            from flash_research_runtime import FlashResearchRuntime as DeepResearch
        else:
            from modified_deep_research import DeepResearch  # default fallback
        
        # Run the async function with retry-on-timeout
        last_error = ""
        for attempt in range(1, max(1, retries) + 1):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    process_single_question(
                        question_file, output, config_path, run_index, DeepResearch, timeout, attempt_num=attempt
                    )
                )
            finally:
                loop.close()

            if result.success:
                # Return the duration of the successful attempt only
                final = ProcessResult(question_file, run_index, True, "", result.duration_seconds)
                write_to_csv(csv_file_path, final)
                return final

            # If timeout, optionally retry; otherwise, stop early
            last_error = result.error_message
            is_timeout = last_error.startswith("Timeout")
            if not is_timeout or attempt >= max(1, retries):
                # Return the duration of the final failed attempt only
                final = ProcessResult(question_file, run_index, False, last_error + f" (attempt {attempt}/{retries})", result.duration_seconds)
                write_to_csv(csv_file_path, final)
                return final

            # backoff before retrying
            try:
                time.sleep(max(0.0, retry_delay))
            except Exception:
                pass
            
    except Exception as e:
        # Extra safety net: catch any exceptions that might not be pickleable
        error_msg = f"Process-level error for {question_file}: {str(e)}"
        result = ProcessResult(question_file, run_index, False, error_msg, 0.0)
        
        # Write failed result to CSV
        try:
            write_to_csv(csv_file_path, result)
        except:
            pass
            
        return result


def update_progress_bar(result: ProcessResult, pbar: tqdm, stats: dict):
    """Update progress bar with result information"""
    # Update statistics
    if result.success:
        stats['successful'] += 1
        status_symbol = "✓"
    else:
        stats['failed'] += 1
        status_symbol = "✗"
    
    stats['total_time'] += result.duration_seconds
    
    # Calculate averages
    completed = stats['successful'] + stats['failed']
    avg_time = stats['total_time'] / completed if completed > 0 else 0
    
    # Update progress bar description
    pbar.set_description(
        f"Success: {stats['successful']} | Failed: {stats['failed']} | "
        f"Avg: {avg_time:.1f}s | Last: {status_symbol} {Path(result.question_file).name} [run {result.run_index}] ({result.duration_seconds:.1f}s)"
    )
    pbar.update(1)


def find_question_files(directory: str) -> List[str]:
    """Find all .q files in the specified directory"""
    pattern = os.path.join(directory, "*.q")
    question_files = glob.glob(pattern)
    return sorted(question_files)


def scan_existing_outputs(output_dir: str, question_files: List[str], k_answers: int) -> List[Tuple[str, int]]:
    """Scan output directory for existing answer files and return missing tasks.
    
    Args:
        output_dir: Directory to scan for existing .a files
        question_files: List of question file paths
        k_answers: Required number of answers per question
        
    Returns:
        List of (question_file, run_index) tuples for missing runs
    """
    missing_tasks = []
    
    for question_file in question_files:
        base_name = Path(question_file).stem
        existing_runs = set()
        
        # Scan for existing answer files with pattern: {base_name}_run_{index}.a
        pattern = os.path.join(output_dir, f"{base_name}_run_*.a")
        existing_files = glob.glob(pattern)
        
        for existing_file in existing_files:
            # Extract run index from filename
            filename = Path(existing_file).stem
            if filename.startswith(f"{base_name}_run_"):
                try:
                    run_part = filename[len(f"{base_name}_run_"):]
                    run_index = int(run_part)
                    existing_runs.add(run_index)
                except ValueError:
                    # Skip files that don't match expected pattern
                    continue
        
        # Find missing runs
        required_runs = set(range(1, k_answers + 1))
        missing_runs = required_runs - existing_runs
        
        for run_index in sorted(missing_runs):
            missing_tasks.append((question_file, run_index))
    
    return missing_tasks


def save_run_configuration(output_dir: str, args, question_files: List[str]):
    """Save CLI args, selected env vars, and config.json contents to a file before running."""
    
    # Get DeepResearch class name based on version
    deep_research_name = "unknown"
    if args.version == "baseline":
        deep_research_name = "modified_deep_research.DeepResearch"
    elif args.version == "parallel":
        deep_research_name = "recursive_deep_research.RecursiveDeepResearch"
    elif args.version == "runtime":
        deep_research_name = "flash_research_runtime.FlashResearchRuntime"
    
    snapshot = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "cli_args": {
            "input": getattr(args, "input", None),
            "output": getattr(args, "output", None),
            "config": getattr(args, "config", None),
            "workers": getattr(args, "workers", None),
            "k_answers": getattr(args, "k_answers", None),
        },
        "env": {
            "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL"),
            "CUSTOM_EMBED_BASE_URL": os.environ.get("CUSTOM_EMBED_BASE_URL"),
            "OPENAI_API_KEY_set": bool(os.environ.get("OPENAI_API_KEY")),
            "BRAVE_API_KEY_set": bool(os.environ.get("BRAVE_API_KEY")),
            "CUSTOM_EMBED_API_KEY_set": bool(os.environ.get("CUSTOM_EMBED_API_KEY")),
        },
        "question_files_count": len(question_files),
        "question_files_sample": [Path(f).name for f in question_files[:10]],
        "deep_research_impl": deep_research_name,
        "config_json": None,
    }

    # Load config.json content, if available
    try:
        with open(args.config, "r", encoding="utf-8") as cf:
            snapshot["config_json"] = json.load(cf)
    except Exception as e:
        snapshot["config_json"] = {"error": f"Failed to load config: {e}"}

    out_path = os.path.join(output_dir, "run_configuration.json")

    # Don't overwrite existing configuration when resuming
    if os.path.exists(out_path):
        print(f"Run configuration file already exists: {out_path} (resuming previous run)")
        return

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to write run configuration snapshot: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run deep research on all .q files in a directory")
    parser.add_argument("--input", help="Directory containing .q files")
    parser.add_argument("--output", help="Directory to save .a files")
    parser.add_argument("--config", default="./config.json", help="Path to config.json file")
    parser.add_argument("--workers", type=int, default=4,
                       help="Maximum number of concurrent workers (default: 4)")
    parser.add_argument("--k", dest="k_answers", type=int, default=1,
                       help="Number of answers to generate per question (default: 1)")
    parser.add_argument("--timeout", type=int, default=1000,
                       help="Per-run timeout in seconds; 0 disables timeout (default: 1000)")
    parser.add_argument("--retries", type=int, default=3,
                       help="Number of attempts per run on timeout (default: 3)")
    parser.add_argument("--retry-delay", type=float, default=1.0,
                       help="Seconds to wait before retrying after a timeout (default: 1.0)")
    parser.add_argument("--version", type=str, choices=["baseline", "parallel", "runtime"],
                       help="Version of the research model to use")

    args = parser.parse_args()
    
    # Validate input directory
    if not os.path.isdir(args.input):
        raise ValueError(f"Input directory does not exist: {args.input}")
    
    # Create output directory
    os.makedirs(args.output, exist_ok=True)
    
    # Find all question files
    question_files = find_question_files(args.input)
    print(f"Found {len(question_files)} question files in {args.input}")
    
    if not question_files:
        print("No .q files found!")
        exit(0)
    
    # Setup environment
    setup_environment()
    # Save a snapshot of configurations and inputs
    save_run_configuration(args.output, args, question_files)
    
    # Determine number of processes
    num_processes = min(args.workers, mp.cpu_count())
    print(f"Using {num_processes} processes")
    print(f"Detailed logs will be saved in individual log files under {args.output}/logs/")
    
    # Setup CSV file path for dynamic updates
    timing_csv_file = os.path.join(args.output, "timing_details.csv")

    # Scan for existing outputs and determine what needs to be processed
    missing_tasks = scan_existing_outputs(args.output, question_files, args.k_answers)
    
    if not missing_tasks:
        print(f"All required runs already exist for {len(question_files)} questions ({args.k_answers} runs each)")
        print("Nothing to process!")
        exit(0)
    
    print(f"Found {len(missing_tasks)} missing runs out of {len(question_files) * args.k_answers} total required runs")
    
    # Only create timing CSV if it doesn't exist (for resuming runs)
    csv_exists = os.path.exists(timing_csv_file)
    if not csv_exists:
        # Create empty CSV with headers
        with open(timing_csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["question_file", "run_index", "duration_seconds", "status", "error_message"])

    # Prepare arguments for multiprocessing using missing tasks
    process_args = [
        (
            qf,
            args.output,
            args.config,
            timing_csv_file,
            run_idx,
            float(args.timeout) if args.timeout and args.timeout > 0 else None,
            int(args.retries),
            float(args.retry_delay),
            args.version,  # Add version for each worker process
        )
        for qf, run_idx in missing_tasks
    ]
    
    # Start processing with progress bar
    start_time = time.time()
    stats = {'successful': 0, 'failed': 0, 'total_time': 0.0}
    question_durations = []
    
    total_runs = len(process_args)
    print(f"\nStarting batch processing: {total_runs} runs across {len(question_files)} files...")
    
    # Initialize progress bar
    with tqdm(total=total_runs, desc="Processing", ncols=120, 
              bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}] {desc}') as pbar:
        # Use a spawn context to avoid fork-related deadlocks with threads/async
        try:
            mp.set_start_method("spawn", force=True)
        except RuntimeError:
            # Start method was already set; ignore
            pass

        ctx = mp.get_context("spawn")
        # Recycle workers to avoid potential memory leaks or stuck state
        with ctx.Pool(processes=num_processes, maxtasksperchild=1) as pool:
            # Process files and track progress (unordered to avoid head-of-line blocking)
            results = []
            for result in pool.imap_unordered(run_single_process, process_args):
                results.append(result)
                question_durations.append(result.duration_seconds)

                # Update progress bar
                update_progress_bar(result, pbar, stats)
    
    # Final summary
    total_time = time.time() - start_time
    
    # Calculate timing statistics
    successful_durations = [r.duration_seconds for r in results if r.success]
    failed_durations = [r.duration_seconds for r in results if not r.success]
    
    if question_durations:
        min_time = min(question_durations)
        max_time = max(question_durations)
        avg_time = sum(question_durations) / len(question_durations)
        median_time = sorted(question_durations)[len(question_durations) // 2]
    else:
        min_time = max_time = avg_time = median_time = 0
    
    print(f"\n=== BATCH PROCESSING COMPLETE ===")
    print(f"Total files: {len(question_files)}")
    print(f"Total runs: {total_runs}")
    print(f"Successful: {stats['successful']}")
    print(f"Failed: {stats['failed']}")
    print(f"Total time: {total_time:.2f} seconds")
    print(f"Average time per run: {total_time/total_runs:.2f} seconds")
    print(f"\n=== TIMING STATISTICS ===")
    print(f"Min question time: {min_time:.2f}s")
    print(f"Max question time: {max_time:.2f}s")
    print(f"Average question time: {avg_time:.2f}s")
    print(f"Median question time: {median_time:.2f}s")
    if successful_durations:
        print(f"Average successful question time: {sum(successful_durations)/len(successful_durations):.2f}s")
    if failed_durations:
        print(f"Average failed question time: {sum(failed_durations)/len(failed_durations):.2f}s")
    
    # Save summary log
    summary_file = os.path.join(args.output, "batch_summary.txt")
    with open(summary_file, 'w') as f:
        f.write(f"Batch Processing Summary\n")
        f.write(f"========================\n")
        f.write(f"Input Directory: {args.input}\n")
        f.write(f"Output Directory: {args.output}\n")
        f.write(f"Config File: {args.config}\n")
        f.write(f"Processes Used: {num_processes}\n")
        f.write(f"Total Files: {len(question_files)}\n")
        f.write(f"Total Runs: {total_runs}\n")
        f.write(f"Successful: {stats['successful']}\n")
        f.write(f"Failed: {stats['failed']}\n")
        f.write(f"Total Time: {total_time:.2f} seconds\n")
        f.write(f"Average Time per Run: {total_time/total_runs:.2f} seconds\n\n")
        
        f.write(f"Timing Statistics\n")
        f.write(f"=================\n")
        f.write(f"Min question time: {min_time:.2f}s\n")
        f.write(f"Max question time: {max_time:.2f}s\n")
        f.write(f"Average question time: {avg_time:.2f}s\n")
        f.write(f"Median question time: {median_time:.2f}s\n")
        if successful_durations:
            f.write(f"Average successful question time: {sum(successful_durations)/len(successful_durations):.2f}s\n")
        if failed_durations:
            f.write(f"Average failed question time: {sum(failed_durations)/len(failed_durations):.2f}s\n")
        f.write(f"\n")
        
        f.write("Individual Question Timings:\n")
        f.write("============================\n")
        for result in results:
            status = "SUCCESS" if result.success else "FAILED"
            f.write(f"{Path(result.question_file).name} [run {result.run_index}]: {result.duration_seconds:.2f}s ({status})\n")
        
        f.write(f"\nFailed Files Details:\n")
        f.write(f"=====================\n")
        for result in results:
            if not result.success:
                f.write(f"  {result.question_file} [run {result.run_index}]: {result.error_message}\n")
    
    print(f"\nDetailed reports saved:")
    print(f"  Summary: {summary_file}")
    print(f"  Real-time timing details: {timing_csv_file}")
    print(f"  Individual logs: {args.output}/logs/")


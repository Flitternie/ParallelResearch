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

from modified_deep_research import DeepResearch


class ProcessResult(NamedTuple):
    """Result of processing a single question"""
    question_file: str
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
            # Write header if file doesn't exist
            if not file_exists:
                writer.writerow(["question_file", "duration_seconds", "status", "error_message"])
            
            # Write the result
            status = "success" if result.success else "failed"
            error_msg = result.error_message.replace(',', ';').replace('\n', ' ')  # Clean CSV format
            writer.writerow([Path(result.question_file).name, f"{result.duration_seconds:.2f}", status, error_msg])


def setup_environment():
    """Setup environment variables for API keys"""
    try:
        os.environ["OPENAI_API_KEY"] = open("./openai.key").read().strip()
        os.environ["OPENAI_BASE_URL"] = open("openai_url.key").read().strip()
        os.environ["BRAVE_API_KEY"] = open("./brave.key").read().strip()
        os.environ["CUSTOM_EMBED_API_KEY"] = open("./openai.key").read().strip()
        os.environ["CUSTOM_EMBED_BASE_URL"] = open("openai_url.key").read().strip()
    except FileNotFoundError as e:
        raise RuntimeError(f"Missing API key file: {e}")


async def process_single_question(question_file: str, output_dir: str, config_path: str) -> ProcessResult:
    """Process a single question file and generate research report
    
    Args:
        question_file: Path to the .q file containing the question
        output_dir: Directory to save the output .a file
        config_path: Path to the config.json file
        
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
            return ProcessResult(question_file, False, "Empty question file", duration)
        
        # Create output filename (.a file)
        base_name = Path(question_file).stem
        output_file = os.path.join(output_dir, f"{base_name}.a")
        
        # Create logs directory for this specific research
        logs_dir = os.path.join(output_dir, "logs", base_name)
        os.makedirs(logs_dir, exist_ok=True)
        
        # Setup logging for this process - capture ALL logging
        log_file = os.path.join(logs_dir, f"{base_name}.log")
        
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
                root_logger.info(f"Starting research for: {question_file}")
                report = await deep_researcher.run()
                root_logger.info(f"Research completed for: {question_file}")
        
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
        root_logger.info(f"Completed research for {question_file} in {duration:.2f}s")
        return ProcessResult(question_file, True, "", duration)
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Error processing {question_file}: {str(e)}"
        
        # Try to log the error if logger is available
        try:
            logging.error(error_msg)
        except:
            pass
            
        return ProcessResult(question_file, False, error_msg, duration)


def run_single_process(args: Tuple[str, str, str, str]) -> ProcessResult:
    """Wrapper function to run async process_single_question in a separate process"""
    question_file, output_dir, config_path, csv_file_path = args
    
    try:
        # Setup environment in each process
        setup_environment()
        
        # Run the async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(process_single_question(question_file, output_dir, config_path))
            
            # Write result to CSV immediately after completion
            write_to_csv(csv_file_path, result)
            
            return result
        finally:
            loop.close()
            
    except Exception as e:
        # Extra safety net: catch any exceptions that might not be pickleable
        error_msg = f"Process-level error for {question_file}: {str(e)}"
        result = ProcessResult(question_file, False, error_msg, 0.0)
        
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
        f"Avg: {avg_time:.1f}s | Last: {status_symbol} {Path(result.question_file).name} ({result.duration_seconds:.1f}s)"
    )
    pbar.update(1)


def find_question_files(directory: str) -> List[str]:
    """Find all .q files in the specified directory"""
    pattern = os.path.join(directory, "*.q")
    question_files = glob.glob(pattern)
    return sorted(question_files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run deep research on all .q files in a directory")
    parser.add_argument("--input_dir", help="Directory containing .q files")
    parser.add_argument("--output_dir", help="Directory to save .a files")
    parser.add_argument("--config", default="./config.json", help="Path to config.json file")
    parser.add_argument("--workers", type=int, default=4,
                       help="Maximum number of concurrent workers (default: 4)")
    
    args = parser.parse_args()
    
    # Validate input directory
    if not os.path.isdir(args.input_dir):
        raise ValueError(f"Input directory does not exist: {args.input_dir}")
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Find all question files
    question_files = find_question_files(args.input_dir)
    print(f"Found {len(question_files)} question files in {args.input_dir}")
    
    if not question_files:
        print("No .q files found!")
        exit(0)
    
    # Setup environment
    setup_environment()
    
    # Determine number of processes
    num_processes = min(args.workers, mp.cpu_count())
    print(f"Using {num_processes} processes")
    print(f"Detailed logs will be saved in individual log files under {args.output_dir}/logs/")
    
    # Setup CSV file path for dynamic updates
    timing_csv_file = os.path.join(args.output_dir, "timing_details.csv")

    # Ensure CSV file is empty
    if os.path.exists(timing_csv_file):
        os.remove(timing_csv_file)
    
    # Prepare arguments for multiprocessing (include CSV path)
    process_args = [(qf, args.output_dir, args.config, timing_csv_file) for qf in question_files]
    
    # Start processing with progress bar
    start_time = time.time()
    stats = {'successful': 0, 'failed': 0, 'total_time': 0.0}
    question_durations = []
    
    print(f"\nStarting batch processing of {len(question_files)} files...")
    
    # Initialize progress bar
    with tqdm(total=len(question_files), desc="Processing", ncols=120, 
              bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}] {desc}') as pbar:
        
        with mp.Pool(processes=num_processes) as pool:
            # Process files and track progress
            results = []
            for result in pool.imap(run_single_process, process_args):
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
    print(f"Successful: {stats['successful']}")
    print(f"Failed: {stats['failed']}")
    print(f"Total time: {total_time:.2f} seconds")
    print(f"Average time per file: {total_time/len(question_files):.2f} seconds")
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
    summary_file = os.path.join(args.output_dir, "batch_summary.txt")
    with open(summary_file, 'w') as f:
        f.write(f"Batch Processing Summary\n")
        f.write(f"========================\n")
        f.write(f"Input Directory: {args.input_dir}\n")
        f.write(f"Output Directory: {args.output_dir}\n")
        f.write(f"Config File: {args.config}\n")
        f.write(f"Processes Used: {num_processes}\n")
        f.write(f"Total Files: {len(question_files)}\n")
        f.write(f"Successful: {stats['successful']}\n")
        f.write(f"Failed: {stats['failed']}\n")
        f.write(f"Total Time: {total_time:.2f} seconds\n")
        f.write(f"Average Time per File: {total_time/len(question_files):.2f} seconds\n\n")
        
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
            f.write(f"{Path(result.question_file).name}: {result.duration_seconds:.2f}s ({status})\n")
        
        f.write(f"\nFailed Files Details:\n")
        f.write(f"=====================\n")
        for result in results:
            if not result.success:
                f.write(f"  {result.question_file}: {result.error_message}\n")
    
    print(f"\nDetailed reports saved:")
    print(f"  Summary: {summary_file}")
    print(f"  Real-time timing details: {timing_csv_file}")
    print(f"  Individual logs: {args.output_dir}/logs/")


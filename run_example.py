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

import logging
from flashresearch import LatencyTracker
from visualization import ResearchVisualizer
import os
import time

VERSION = "flash"

if VERSION == "baseline":
    from flashresearch import DeepResearch
elif VERSION == "parallel":
    # there exist two implementations of parallel deep research
    # from flashresearch import ParallelDeepResearch as DeepResearch
    from flashresearch import RecursiveDeepResearch as DeepResearch
elif VERSION == "runtime":
    from flashresearch import FlashResearchRuntime as DeepResearch
elif VERSION == "flash":
    from flashresearch import FlashResearch as DeepResearch

# generate a new directory for the logs based on the current timestamp
logs_dir = f"logs/{time.strftime('%Y%m%d_%H%M%S')}"
os.makedirs(logs_dir, exist_ok=True)


# save all the logs to a file
logging.basicConfig(filename=f'{logs_dir}/deep_research.log', level=logging.DEBUG)

os.environ["OPENAI_API_KEY"] = open("./keys/openai.key").read().strip()
os.environ["OPENAI_BASE_URL"] = open("./keys/openai_url.key").read().strip()
os.environ["CUSTOM_EMBED_API_KEY"] = ""
os.environ["CUSTOM_EMBED_BASE_URL"] = "http://0.0.0.0:8000/v1/"

# if using FineWeb as retriever, set the API key
os.environ["FINEWEB_API_KEY"] = open("./keys/fineweb.key").read().strip()
# if using other search engines, set their API keys here
# os.environ["TAVILY_API_KEY"] = open("./keys/tavily.key").read().strip()
# os.environ["BRAVE_API_KEY"] = open("./keys/brave.key").read().strip()

user_query = "What are the latest news in Fed's monetary policy?"
deep_researcher = DeepResearch(query=user_query, config_path="./config/demo.json", logs_dir=logs_dir)


async def main():
    report = await deep_researcher.run()
    # save the report as a markdown file
    with open(f"{logs_dir}/report.md", "w") as f:
        f.write(report)
    
    # Print summary
    separator = "=" * 60
    
    # Token usage summary
    print(f"\n{separator}")
    print("TOKEN USAGE SUMMARY")
    print(separator)
    try:
        import json
        with open(f"{logs_dir}/token_usage.json", "r") as f:
            token_data = json.load(f)
        print(token_data.get("summary", "No summary available"))
    except Exception as e:
        print(f"Could not load token usage: {e}")
    
    # Execution time summary
    print(f"\n{separator}")
    print("EXECUTION TIME SUMMARY")
    print(separator)
    try:
        execution_time = token_data.get("execution_time", None)
        if execution_time is not None:
            print(f"Total Execution Time: {execution_time:.2f}s")
        else:
            print("Total Execution Time: N/A")
    except NameError:
        print("Total Execution Time: N/A")
    
    # Latency profiling summary
    latency_data = LatencyTracker.get_summary()
    if 'llm' in latency_data:
        llm_stats = latency_data['llm']
        print(f"LLM Avg Latency:       {llm_stats['avg_latency']:.2f}s per call")
    if 'search' in latency_data:
        search_stats = latency_data['search']
        print(f"Search Avg Latency:    {search_stats['avg_latency']:.2f}s per call")
    
    print(f"\n{separator}")
    print("DETAILED LATENCY BREAKDOWN")
    print(separator)
    print(LatencyTracker.get_formatted_summary())
    
    # Save the latency data to a file
    with open(f"{logs_dir}/latency_summary.txt", "w") as f:
        f.write(LatencyTracker.get_formatted_summary())
    
    # visualize the research progress
    visualizer = ResearchVisualizer(f"{logs_dir}/progress.json")
    visualizer.visualize(f"{logs_dir}/final_visualization.html")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

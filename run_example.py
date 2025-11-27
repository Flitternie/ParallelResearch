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
    
    # Print token usage summary if available
    try:
        import json
        with open(f"{logs_dir}/token_usage.json", "r") as f:
            token_data = json.load(f)
        print("\n" + "="*60)
        print("TOKEN USAGE SUMMARY")
        print("="*60)
        # Print overall summary
        print(token_data.get("summary", "No summary available"))
        print("="*60 + "\n")
        print("Total Execution Time (s):", token_data.get("execution_time", "N/A"))
        print("="*60 + "\n")
    except Exception as e:
        print(f"Could not load token usage: {e}")

    # Get detailed profiling data programmatically
    latency_data = LatencyTracker.get_summary()
    
    if 'llm' in latency_data:
        llm_stats = latency_data['llm']
        print(f"\nLLM Efficiency: {llm_stats['avg_latency']:.3f}s average per call")
    
    if 'search' in latency_data:
        search_stats = latency_data['search']
        print(f"Search Efficiency: {search_stats['avg_latency']:.3f}s average per call")
    
    print(LatencyTracker.get_formatted_summary())
    # save the latency data to a file
    with open(f"{logs_dir}/latency_summary.txt", "w") as f:
        f.write(LatencyTracker.get_formatted_summary())
    
    # visualize the research progress
    visualizer = ResearchVisualizer(f"{logs_dir}/progress.json")
    visualizer.visualize(f"{logs_dir}/final_visualization.html")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
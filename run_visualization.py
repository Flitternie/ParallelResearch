import logging
# from flashresearch import DeepResearch
# from flashresearch import ParallelizedDeepResearch as DeepResearch
from flashresearch import RecursiveDeepResearch as DeepResearch
# from flashresearch import FlashResearchRuntime as DeepResearch
from visualization import ResearchVisualizer
import os
import time

# generate a new directory for the logs based on the current timestamp
logs_dir = f"logs/{time.strftime('%Y%m%d_%H%M%S')}"
os.makedirs(logs_dir, exist_ok=True)


# save all the logs to a file
logging.basicConfig(filename=f'{logs_dir}/deep_research.log', level=logging.DEBUG)

os.environ["OPENAI_API_KEY"] = open("./openai.key").read().strip()
os.environ["OPENAI_BASE_URL"] = open("openai_url.key").read().strip()
# os.environ["TAVILY_API_KEY"] = open("./tavily.key").read().strip()
# os.environ["BRAVE_API_KEY"] = open("./brave.key").read().strip()
os.environ["CUSTOM_EMBED_API_KEY"] = open("./openai.key").read().strip()
# os.environ["CUSTOM_EMBED_BASE_URL"] = open("openai_url.key").read().strip()
os.environ["CUSTOM_EMBED_BASE_URL"] = "http://0.0.0.0:8000/v1/"
os.environ["FINEWEB_API_KEY"] = open("./fineweb.key").read().strip()

# user_query = "What are the latest news in Fed's monetary policy?"
user_query = "What are the latest advancements in AI code generation?"
deep_researcher = DeepResearch(query=user_query, config_path="./config/sequential_depth_2.json", logs_dir=logs_dir)


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
    
    # visualize the research progress
    visualizer = ResearchVisualizer(f"{logs_dir}/progress.json")
    visualizer.visualize(f"{logs_dir}/final_visualization.html")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
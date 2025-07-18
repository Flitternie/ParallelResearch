import logging
from modified_parallel_deep_research import DeepResearch
from research_visualizer_d3 import ResearchVisualizer
import os
import time

# generate a new directory for the logs based on the current timestamp
logs_dir = f"logs/{time.strftime('%Y%m%d_%H%M%S')}"
os.makedirs(logs_dir, exist_ok=True)


# save all the logs to a file
logging.basicConfig(filename=f'{logs_dir}/deep_research.log', level=logging.DEBUG)

os.environ["OPENAI_API_KEY"] = open("./openai.key").read().strip()
os.environ["OPENAI_BASE_URL"] = open("openai_url.key").read().strip()
os.environ["BRAVE_API_KEY"] = open("./brave.key").read().strip()
os.environ["CUSTOM_EMBED_API_KEY"] = open("./openai.key").read().strip()
os.environ["CUSTOM_EMBED_BASE_URL"] = open("openai_url.key").read().strip()

# user_query = "What are the latest news in Fed's monetary policy?"
user_query = "What are the latest advancements in AI code generation?"
deep_researcher = DeepResearch(query=user_query, config_path="./config.json", logs_dir=logs_dir)


async def main():
    report = await deep_researcher.run()
    # save the report as a markdown file
    with open(f"{logs_dir}/report.md", "w") as f:
        f.write(report)
    # visualize the research progress
    visualizer = ResearchVisualizer(f"{logs_dir}/progress.json")
    visualizer.visualize(f"{logs_dir}/final_visualization.html")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
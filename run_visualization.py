import logging
from modified_parallel_deep_research import DeepResearch
import os
import time

# generate a new directory for the logs based on the current timestamp
logs_dir = f"logs/{time.strftime('%Y%m%d_%H%M%S')}"
os.makedirs(logs_dir, exist_ok=True)


# save all the logs to a file
logging.basicConfig(filename=f'{logs_dir}/deep_research.log', level=logging.DEBUG)

# os.environ["TAVILY_API_KEY"] = open("./tavily.key").read().strip()
os.environ["BRAVE_API_KEY"] = open("./brave.key").read().strip()
os.environ["CUSTOM_EMBED_API_KEY"] = "EMPTY"
os.environ["CUSTOM_EMBED_BASE_URL"] = "http://localhost:8000/v1/"

user_query = "What are the latest news in Fed's monetary policy?"
deep_researcher = DeepResearch(query=user_query, config_path="./config.json", logs_dir=logs_dir)


async def main():
    report = await deep_researcher.run()
    # save the report as a markdown file
    with open(f"{logs_dir}/report.md", "w") as f:
        f.write(report)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
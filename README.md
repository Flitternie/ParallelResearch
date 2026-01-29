# ParallelResearch

ParallelResearch transforms sequential deep research into parallel, runtime orchestration by dynamically decomposing complex queries into tree-structured sub-tasks, achieving up to **5× speedup** while maintaining comparable quality.

## Key Features

- **Adaptive Planning** — Dynamically allocates resources based on query complexity
- **Real-time Orchestration** — Monitors progress and prunes redundant paths during execution  
- **Multi-dimensional Parallelization** — Concurrent execution across research breadth and depth

## Installation

First, create a conda environment and install the dependencies:

```bash
conda env create -f env.yml
conda activate parallelresearch
pip install -r requirements.txt
```

Then, install the GPT Researcher. Set your API keys under the directory of `keys/`:
```
keys/openai.key       # OPENAI_API_KEY
keys/openai_url.key   # OPENAI_BASE_URL
keys/fineweb.key      # FINEWEB_API_KEY, for reproducing paper results
keys/tavily.key       # TAVILY_API_KEY, for web search (optional)
keys/brave.key        # BRAVE_API_KEY, for web search (optional)
```

If you want to serve the embedding model locally, run:

```bash
vllm serve nomic-ai/nomic-embed-text-v1 \
  --task embed \
  --trust-remote-code \
  --host 0.0.0.0 \
  --port 8000
```

## Usage

### Quick Demo

```bash
python run_example.py
```

### Run Benchmarks

**DeepResearchGym:**

First prepare the dataset:
```bash
unzip data/gym_question.zip -d data/
```

Then run the benchmark:
```bash
python run_deepresearch_gym.py \
  --input data/gym_question/ \
  --output exp/gym_time_10_baseline/ \
  --config config/main_time_limit_10.json \
  --version baseline
```

Available `--version` options:
| Version | Description |
|---------|-------------|
| `baseline` | GPT Researcher's baseline implementation |
| `parallelresearch` | ParallelResearch (full method) |
| `runtime` | Ablation without adaptive planning |
| `parallel` | Ablation without adaptive planning or real-time orchestration |

**DeepResearch Bench:**

First prepare the dataset:
```bash
git clone https://github.com/Ayanami0730/deep_research_bench.git
```

Then run the benchmark:
```bash
python run_deep_research_bench.py \
  --input deep_research_bench/data/prompt_data/query.jsonl \
  --output exp/deep_research_bench/ \
  --config config/deep_research_bench.json \
  --version baseline \
  --model_name baseline
```

## Configuration

Configurations are stored in `config/`. 

### LLM Configuration

LLM settings use the unified format `provider:model` (e.g., `openai:gpt-4.1-mini`):

| Parameter | Description |
|-----------|-------------|
| `FAST_LLM` | LLM for fast operations like summaries (e.g., `openai:gpt-4.1-mini`) |
| `SMART_LLM` | LLM for general tasks like generating reports and reasoning (e.g., `openai:gpt-4.1-mini`) |
| `STRATEGIC_LLM` | LLM for planning and orchestration (e.g., `openai:o3-mini`) |

### Other Parameters

| Parameter | Description |
|-----------|-------------|
| `MAX_DEPTH` | Maximum research tree depth |
| `MAX_BREADTH` | Maximum subqueries per node |
| `EMBEDDING` | Embedding model for retrieval (add `custom` as prefix for local model) |
| `RETRIEVER` | Search backend (`fineweb`, `tavily`, `brave`, etc.) |
| `REPORT_SOURCE` | Source type for research (`web`, `local`, `hybrid`) |
| `CONCURRENCY_LIMIT` | Max concurrent LLM calls |
| `TOTAL_WORDS` | Target word count for final report |
| `CONTEXT_BUFFER_SIZE` | Number of context chunks to retain |
| `MAX_CONTEXT_WORDS` | Maximum words in context window |
| `MAX_SEARCH_RESULTS_PER_QUERY` | Results per search query |
| `TIME_LIMIT_SECONDS` | Time budget for research execution |
| `RUNTIME_SATISFACTION_THRESHOLD` | Goal satisfaction threshold for early termination|
| `RUNTIME_QUALITY_THRESHOLD` | Quality threshold for path pruning|

## Project Structure

```
parallelresearch/
├── parallelresearch/          # Core implementation
│   ├── agent.py            # Base agent logic
│   ├── researcher.py       # Base researcher logic
│   ├── deep_research.py    # GPT-Researcher baseline
│   ├── parallel_deep_research.py       # Parallel version
│   ├── recursive_deep_research.py      # Parallel version with recursive structure
│   ├── parallel_research_runtime.py       # Ablation version without adaptive planning
│   └── parallel_research.py               # ParallelResearch (full method)
├── config/                 # Experiment configurations
├── evaluation/             # Evaluation scripts
├── visualization/          # Visualization scripts
├── keys/                   # API keys
├── exp/                    # Experiment results
├── logs/                   # Execution logs for example runs
└── data/                   # Benchmark datasets
```

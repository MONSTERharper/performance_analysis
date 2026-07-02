# Performance Analysis

Python project for analyzing scanner performance data stored in MongoDB.

## Setup

```bash
cd performance_analysis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set your MongoDB credentials (a `.env` file is already configured for your server).

## Quick Start

```bash
# Test connection
python main.py ping

# List all collections and document counts
python main.py list

# Full database inventory
python main.py inventory --save

# Run all analyses and save CSV reports
python main.py analyze --all --save

# Run specific analyses
python main.py analyze --module stoppages --module errors --save

# Export all raw data to CSV
python main.py export --output output/raw

# Export a single collection
python main.py export --collection test_db2.scanner_stoppages
```

## Databases

| Database | Description |
|---|---|
| `local_analytics_db` | Legacy analytics — stoppages, error logs, sites, scanners |
| `test_db2` | Primary ingestion DB — largest dataset (~150k+ docs) |
| `test_db3` | Secondary ingestion DB — subset of test_db2 collections |

## Analysis Modules

| Module | Collections covered |
|---|---|
| `inventory` | All databases — document counts and field schemas |
| `stoppages` | Scanner stoppage events across all DBs |
| `errors` | Raw error logs, basket errors, error counts |
| `load_time` | Load duration and slide throughput per site/cluster |
| `regression` | Scan time vs area regression metrics |
| `sites` | Sites, scanners, customers reference data |
| `slides` | Slide counts, ingestion audit, CTA logs |

## Output

Reports are saved to `output/` when using `--save`:

```
output/
├── inventory.csv
├── stoppages_by_site.csv
├── errors_by_error_code.csv
├── load_time_by_site.csv
├── regression_regression_by_site.csv
└── raw/                  # full collection exports
    ├── test_db2_scanner_stoppages.csv
    └── ...
```

## Configuration

Environment variables in `.env`:

| Variable | Default |
|---|---|
| `MONGO_HOST` | `10.10.1.124` |
| `MONGO_PORT` | `27018` |
| `MONGO_USERNAME` | `pe_reader` |
| `MONGO_PASSWORD` | *(set in .env)* |
| `MONGO_AUTH_SOURCE` | `admin` |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` |
| `OLLAMA_PRIMARY_MODEL` | `deepseek-r1:14b` |
| `OLLAMA_FALLBACK_MODEL` | `qwen2.5:14b` |
| `OLLAMA_TIMEOUT` | `120` (seconds) |
| `OLLAMA_KEEP_ALIVE` | `60m` |
| `OLLAMA_NUM_CTX` | `8192` (model context window in tokens) |

## LLM Knowledge Base

The `knowledge/` folder contains schema documentation designed to be fed into an LLM as persistent context:

| File | Purpose |
|---|---|
| `knowledge/test_db2_context.md` | **Full reference** — all 15 collections, field meanings, relationships, example queries |
| `knowledge/test_db2_schema.json` | Structured schema for programmatic use / RAG chunking |

View or copy the context document:

```bash
python -c "from chatbot.knowledge_loader import load_context; print(load_context())"
```

## LLM Chatbot (Streamlit + Ollama)

Interactive web UI with local Ollama models and cascade fallback.

### Setup Ollama

```bash
# Start Ollama (if not already running)
ollama serve

# Pull required models
ollama pull deepseek-r1:14b
ollama pull qwen2.5:14b
```

### Run Streamlit app

```bash
pip install -r requirements.txt
streamlit run chatbot/app.py
```

Opens at `http://localhost:8501`

**Model selection (sidebar):**
- **Auto** — DeepSeek primary, Qwen fallback (default)
- **DeepSeek only** — force `deepseek-r1:14b`
- **Qwen only** — force `qwen2.5:14b`

**Layout:** persistent left **sidebar** holds all controls (New chat, connection/model
status, Filters, Charts & answers, Model, Knowledge, Saved queries, System); the centered
main column is the conversation.

**Features:**
- **Grounded answers (default on):** answers to data questions are built directly from
  MongoDB query results, so the model cannot rename or invent values (e.g. fabricated
  error types). Toggle in *Sidebar → Charts & answers*.
- **Built-in charts (default on):** reliable Plotly templates instead of flaky LLM plot
  code. Say "plot …", or enable *Attach chart to data answers*.
- **Context-safe prompts:** requests are trimmed to fit the model's context window
  (`OLLAMA_NUM_CTX`, default 8192) and automatically retry with a smaller prompt if the
  window is exceeded — no more "exceeds available context size" crashes.
- **RAG knowledge retrieval** — only relevant schema chunks per query (not the full doc).
- Live status updates: retrieving context, loading model, thinking, querying DB, plotting.
- **Opt-in filters:** site + date range are OFF by default (all data); enable per query.
- **Saved queries:** bookmark and re-run questions with filters.
- **Export buttons:** CSV, JSON, chart HTML/PNG, response text on every answer.
- **Raw data tables:** ask "give me the raw data" — interactive table + download.

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite (no live MongoDB/Ollama needed) covers intent routing, context budgeting,
grounded-answer formatting, filters, built-in queries, and the full agent flow —
including regression guards for context-window overflow recovery and post-query
hallucination.

### CLI alternative

```bash
python -m chatbot.cli
```

Example questions:
- "What are the top error codes at Stanford?"
- "Show me average load duration by site"
- "How do scanner_stoppages and raw_error_logs relate?"
- "Which site has the most slides scanned all-time?"

# Local Agents

A Python-based local LLM orchestration layer that connects IDEs and web frontends to your locally-running models. It acts as an **OpenAI-compatible proxy** with built-in agent tool execution — web search, webpage reading, and PDF search/read — all powered by `llama.cpp` or [FastFlowLM](https://github.com/FastFlowLM/FastFlowLM).

![Architecture](https://img.shields.io/badge/Python-3.11-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## Architecture

```
┌──────────────┐     ┌──────────────────────────────┐     ┌──────────────┐
│ IDE / VS Code│────▶│                              │────▶│ llama.cpp /  │
│  Open WebUI  │────▶│  main.py (FastAPI Proxy)     │────▶│  FastFlowLM  │
│  Other UIs   │────▶│  :8000                       │────▶│  :8081       │
└──────────────┘     │                              │     └──────────────┘
                     │  Agent Loop (tool execution) │
                     │  Web Search (SearXNG)        │     ┌──────────────┐
                     │  PDF Search / Read           │────▶│  SearXNG     │
                     │                              │     │  :8080       │
                     └──────────────────────────────┘     └──────────────┘
                                                             ┌──────────────┐
                                                             │  Open WebUI  │
                                                             │  :3000       │
                                                             └──────────────┘
```

The proxy sits between your frontend (IDE extension, Open WebUI, etc.) and your local model server. It:

1. **Routes** incoming OpenAI-compatible API requests to the correct model.
2. **Manages** model lifecycles — auto-starts, switches, and evicts model servers based on VRAM availability.
3. **Executes** middleware tools (web search, webpage reading, PDF search/read) within the agent loop.
4. **Cleans** IDE-specific request bloat (e.g., Android Studio's `developer` role).

## Project Structure

```
├── main.py                  # FastAPI orchestrator proxy (OpenAI-compatible API)
├── agent_loop.py            # Streaming agent loop with tool execution
├── environment.yml          # Conda environment definition
├── docker-compose.yml       # SearXNG + Open WebUI containers
├── start.ps1                # Windows PowerShell startup helper
├── .env                     # Model & path configuration (copy from .env.example)
├── .env.example             # Template for .env
│
├── models/
│   ├── model_switcher.py    # VRAM-aware model lifecycle manager
│   ├── clients.py           # OpenAI SDK client pointing to local server
│   └── startup_flags.py     # Model listing / Ollama-mock endpoints
│
├── tools/
│   ├── schemas.py           # Tool schema definitions (OpenAI format)
│   ├── tool_defs.py         # Web search & webpage reading implementations
│   ├── pdf_tools.py         # PDF full-text search with custom indexing
│   └── cleaning.py          # IDE request cleaning & history canonicalization
│
└── searxng-data/
    └── settings.yml         # SearXNG configuration
```

## Features

- **Multi-engine support** — Run models via `llama.cpp` (`llama-server`) or FastFlowLM (`flm`) for AMD NPU acceleration.
- **VRAM-aware model switching** — Automatically launches, switches, and evicts model servers; cleans up orphaned processes on startup.
- **Agent tool loop** — Streaming chat completions with built-in tool execution (web search, webpage reading, PDF search/read).
- **OpenAI-compatible API** — Drop-in replacement for IDE extensions (Continue, CodeGPT, etc.) and Open WebUI.
- **Ollama mock endpoints** — Returns proper `/api/tags`, `/api/ps`, `/api/version` responses for Open WebUI compatibility.
- **PDF search & read** — Full-text indexed PDF search with optional custom `custom_index.json` for curated category mappings.
- **IDE request cleaning** — Strips Android Studio `developer` role, filters tool bloat, canonicalizes tool-call history for context cache consistency.

## Prerequisites

| Requirement | Details |
|---|---|
| **Python 3.11** | Required (managed via Conda) |
| **Conda** | Recommended — `environment.yml` provided |
| **Docker + Docker Compose** | Required for SearXNG and Open WebUI |
| **`llama-server`** | Built from [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) |
| **`flm`** *(optional)* | [FastFlowLM](https://github.com/FastFlowLM/FastFlowLM) CLI for AMD NPU models |
| **Git** | For cloning the repo |

## Quick Start

### 1. Clone and set up the environment

```bash
git clone <repo-url>
cd Local_agents
conda env create -f environment.yml
conda activate local_agents
```

### 2. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` to set your model paths, engine binaries, and PDF directory. See the [`.env` Configuration](#env-configuration) section below for details.

### 3. Start infrastructure

```bash
docker compose up -d
```

This boots:
- **SearXNG** — local metasearch engine (`http://localhost:8080`)
- **Open WebUI** — web frontend (`http://localhost:3000`)

### 4. Launch the orchestrator

```bash
python main.py
```

The proxy starts on `http://0.0.0.0:8000` (Linux) or `http://127.0.0.1:8000` (Windows).

> **Windows users:** Run `.\start.ps1` to start Docker, infrastructure, and the Python backend in one command.

## Port Reference

| Port | Service |
|---|---|
| `8000` | Orchestrator proxy (LLM endpoint for IDEs / WebUI) |
| `8081` | Model backend (`llama-server` or `flm`) — managed dynamically |
| `8080` | SearXNG web search |
| `3000` | Open WebUI frontend |

## `.env` Configuration

All configuration is driven by a single `.env` file parsed by `pydantic-settings`.

### `MODELS`

A JSON array of model definitions. Each entry requires:

| Field | Required | Description |
|---|---|---|
| `name` | ✅ | Internal model identifier (for FLM: must match `flm list` output) |
| `display_name` | ✅ | Human-readable name shown in UI dropdowns |
| `path` | ✅ | Path to model weights (`.gguf`, etc.). For FLM engines, any placeholder works |
| `server_path` | ✅ | Path to engine binary (`llama-server` for `llama.cpp`, or `"flm"` for FastFlowLM) |
| `engine` | ✅ | `"llama.cpp"` or `"Fast_flow"` |
| `mmproj` | ❌ | Multimodal projector path for vision models (`null` if unused) |
| `special_arguments` | ❌ | Extra CLI flags as a shell string (e.g., `"-c 32768 -np 1 -t 8 -fa"`) |
| `context` | ❌ | Context window size reported to clients (default: `2048`) |

### `pdf_directory`

Absolute path to a directory containing PDFs. The agent uses `search_Pdfs` and `read_Pdf_page` tools to search and read files here. A full-text search index is built automatically on first use.

### Example `.env`

```env
MODELS='[
  {
    "name": "qwen2.5-7b",
    "display_name": "Qwen 2.5 7B",
    "path": "./models/qwen2.5-7b-Q5_K_M.gguf",
    "server_path": "/path/to/llama-server",
    "engine": "llama.cpp",
    "mmproj": null,
    "special_arguments": "-c 32768 -np 1 -t 8 -fa",
    "context": 24576
  },
  {
    "name": "qwen3.5:9b",
    "display_name": "Qwen 9B NPU",
    "path": "placeholder",
    "server_path": "flm",
    "engine": "Fast_flow",
    "context": 2048
  }
]'
pdf_directory=/home/user/documents/pdfs
```

### Custom PDF Index (Optional)

Create `custom_index.json` inside your `pdf_directory` to add curated category mappings. The format:

```json
{
  "MyPDF": {
    "Category Name": {
      "pages": [1, 5, 12],
      "see_also": ["Related Category"],
      "subs": {
        "Subcategory": {
          "pages": [3, 7],
          "see_also": []
        }
      }
    }
  }
}
```

## Engine Details

### llama.cpp

Launch command built by the model switcher:

```
<server_path> -m <path> --port 8081 --alias <name> [special_arguments]
```

The orchestrator launches **exactly one** model server at a time on port `8081`. Switching models stops the previous server and releases VRAM.

### FastFlowLM (FLM)

Launch command:

```
flm serve <name> -p 8081 --ctx-len 131072
```

FLM models run on AMD NPUs. Install models via `flm pull` and list them with `flm list`. The `name` field must exactly match the output of `flm list`.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | Standard OpenAI chat completions (agent mode) |
| `POST` | `/chat/completions` | Alias for above |
| `GET` | `/v1/models` | List available models |
| `GET` | `/models` | Alias for above |
| `GET` | `/api/tags` | Ollama-compatible model tags |
| `GET` | `/api/ps` | Currently loaded models |
| `GET` | `/api/version` | Mock version string |

IDE requests (model names ending in `-ide`) are routed through a passthrough mode that preserves inbound tool definitions.

## Agent Tools

The built-in middleware tools are available in the agent loop:

| Tool | Description |
|---|---|
| `search_web` | Queries SearXNG and returns up to 5 ranked results with titles, URLs, and snippets |
| `read_webpage` | Fetches a URL and extracts clean text content |
| `search_Pdfs` | Keyword search across indexed PDFs in `pdf_directory` |
| `read_Pdf_page` | Extracts text from a specific page of a PDF (supports table extraction) |

> **Tip:** If running on systems with ≤ 64 GB RAM, consider reducing the tool set in your frontend to avoid context pressure.

## IDE Integration

The proxy supports IDE extensions that expect an OpenAI-compatible endpoint:

1. Set your IDE's API base URL to `http://localhost:8000/v1`
2. Set the API key to any value (e.g., `sk-no-key-required`) — the proxy ignores it
3. Select models from the dropdown populated by `/v1/models`

Model names ending in `-ide` trigger passthrough mode, forwarding the IDE's own tool definitions directly to the model.

## Windows Startup Script

`start.ps1` automates the full startup sequence:

1. Verifies / starts Docker Desktop
2. Launches Docker Compose infrastructure
3. Starts the Python orchestrator
4. On exit: tears down containers and optionally stops Docker Desktop

```powershell
.\start.ps1
```

## License

MIT

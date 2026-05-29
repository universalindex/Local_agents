# Local Agents

Local Agents is a Python-based local orchestration project for running and switching local LLM backends (via `llama.cpp`) and connecting them to web-search-assisted agent workflows.

## What is in this repo

- `main.py` — simple multi-agent web research runner (Google/OpenAI/Ollama via CrewAI)
- `models/model_switcher.py` — local model + `llama-server` lifecycle management
- `models/clients.py` — OpenAI-compatible client configuration for local middleware
- `tools/schemas.py` — middleware tool schema definitions
- `docker-compose.yml` — local infra for SearXNG and Open WebUI
- `start.ps1` — startup helper script for Docker + Python backend

## Prerequisites

- Python 3.11
- Conda (recommended; environment file provided)
- Docker + Docker Compose
- **`llama.cpp` (required)**, including `llama-server` executable
- Optional API keys for cloud models:
  - `GOOGLE_API_KEY`
  - `OPENAI_API_KEY`

## Installation

1. **Clone and enter the project**
   ```bash
   git clone <repo-url>
   cd Local_agents
   ```

2. **Create the Conda environment**
   ```bash
   conda env create -f environment.yml
   conda activate local_agents
   ```

3. **Configure environment files (`.env`)**
   - Copy `.env.example` to `.env`.
   - Update paths and model entries so they match your local system.
   - Ensure each model entry includes a valid `llama_server_path` pointing to your local `llama.cpp` `llama-server` binary.

4. **Start local infrastructure**
   ```bash
   docker compose up -d
   ```

5. **Run the app**
   ```bash
   python main.py
   ```

## Notes on `.env` and `llama.cpp`

- This project expects model configuration from `.env` (via `pydantic-settings` in `models/model_switcher.py`).
- `MODELS` is parsed as structured JSON-like data describing each local model.
- Local model serving depends on `llama.cpp` and an accessible `llama-server` executable path per configured model.

## Optional startup script (Windows PowerShell)

```powershell
./start.ps1
```

This script starts Docker services and then launches the Python backend command defined in the script.

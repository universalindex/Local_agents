# Local Agents

Local Agents is a Python-based local orchestration project for running and switching local LLM backends (via `llama.cpp` or `flm` / FastFlowLM) and connecting them to web-search-assisted agent workflows. It acts as an **OpenAI-compatible proxy**, routing IDE and UI requests to your chosen local models while providing built-in middleware tools (web search, webpage reading, PDF search/read).

## What is in this repo

- `main.py` — FastAPI orchestrator proxy (OpenAI-compatible API with built-in agent tool execution and streaming)
- `models/model_switcher.py` — VRAM-aware model lifecycle manager (auto-start/stop `llama-server` or `flm` with zombie process cleanup)
- `models/clients.py` — OpenAI-compatible client configuration for local middleware
- `tools/schemas.py` — Middleware tool schema definitions (`search_web`, `read_webpage`, `search_Pdfs`, `read_Pdf_page`)
- `tools/tool_def.py` — PDF search and reading implementation with custom indexing and table extraction
- `tools/cleaning.py` — IDE request cleaning utilities (filters bloat for Android Studio, etc.)
- `docker-compose.yml` — Local infrastructure for SearXNG (web search) and Open WebUI
- `start.ps1` — Windows PowerShell startup helper script
- `environment.yml` — Conda environment configuration

## Prerequisites

- **Python 3.11**
- **Conda** (recommended; environment file provided)
- **Docker + Docker Compose**
- **`llama.cpp`** — the `llama-server` binary (built from [llama.cpp](https://github.com/ggerganov/llama.cpp))
- **`flm`** (optional) — FastFlowLM CLI tool, required only if using `engine: Fast_flow` models in `.env` enables NPU support on AMD NPU's
- **Git**

> [!NOTE]
> **Port Reference**:
> - `8000`: Orchestrator proxy (LLM endpoint for IDEs/WebUI)
> - `8081`: Model backend (llama-server or flm)
> - `8080`: SearXNG (web search)
> - `3000`: Open WebUI

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
   - Ensure each model entry includes valid file paths and a correct `server_path`.
   - See the detailed [`.env` Configuration](#env-configuration) section below for every field.

4. **Start local infrastructure**
   ```bash
   docker compose up -d
   ```
   This boots **SearXNG** (web search, port 8080) and **Open WebUI** (port 3000).

5. **Run the app**
   ```bash
   python main.py
   ```

> [!TIP]
> On Windows you can use the helper script: `.\start.ps1` (runs Docker then launches the Python backend).

---

## `.env` Configuration

The `.env` file drives all model and path configuration via `pydantic-settings`. Below is a breakdown of every required and optional field.

### `MODELS`

A JSON array describing every local model you want available. Each model object has the following fields:

| Field | Required | Description |
|---|---|---|
| `name` | ✅ | The internal model identifier (sent to the OpenAI-compatible API). |
| `display_name` | ✅ | Human-readable name shown in Open WebUI and IDE dropdowns. |
| `path` | ✅ | Absolute or relative path to the model weights file (`.gguf`, `.safetensors`, etc.). |
| `server_path` | ✅ | Absolute or relative path to the engine binary. For `llama.cpp` engines this is the `llama-server` executable. For `Fast_flow` engines you may use `"flm"` (if on PATH). |
| `engine` | ✅ | Either `"llama.cpp"` or `"Fast_flow"`. Determines which launch command is built. |
| `mmproj` | ❌ | Path to a multimodal projector file (e.g., for vision-enabled models). Leave as `null` if unused. |
| `special_arguments` | ❌ | Additional CLI flags as a shell-string (e.g., `"-ngl 99 --tensor-split 1"`). Leave as `null` if unused. |

**Example entries:**

```json
{
  "name": "qwen2.5-7b-instruct",
  "display_name": "Qwen 2.5 7B Instruct",
  "path": "./models/qwen2.5-7b-instruct-Q5_K_M.gguf",
  "server_path": "C:/llama.cpp/server/llama-server.exe",
  "engine": "llama.cpp",
  "mmproj": null,
  "special_arguments": "-ngl 99 --ctx-size 8192"
}
```

```json
{
  "name": "llama-3.1-8b",
  "display_name": "Llama 3.1 8B",
  "path": "./models/llama-3.1-8b.Q4_K_M.gguf",
  "server_path": "flm",
  "engine": "Fast_flow",
  "mmproj": null,
  "special_arguments": null
}
```

### `pdf_directory`

| Field | Required | Description |
|---|---|---|
| `pdf_directory` | ✅ | Absolute path to a directory containing PDFs. The agent can search and read PDFs here via the `search_Pdfs` and `read_Pdf_page` tools. |

> [!TIP]
> The first time you use the PDF tools against a new directory, the system will build a search index (takes a moment). Subsequent searches use the cached index.
> You can additionaly create your own JSON index that matches formatting as follows to improve effectivness: name it custom_index.json and 
```json
   {
    "Catagory name": {
        "pages": [Pages is referenced on],
        "see_also": [
            "other entries with information",
            "Other entry with inromation"
        ],
        "subs": {
         Subcatagories
        }
    },
```



### Minimal `.env` Example

```env
MODELS=[
  {
    "name": "qwen2.5-7b",
    "display_name": "Qwen 2.5 7B",
    "path": "./models/qwen2.5-7b-Q5_K_M.gguf",
    "server_path": "C:/llama.cpp/build/bin/llama-server.exe",
    "engine": "llama.cpp",
    "mmproj": null,
    "special_arguments": "-ngl 99"
  }
]
pdf_directory=D:/Documents/pdfs
```

## Notes on `llama.cpp` and Engine Selection

- The orchestrator launches **exactly one** model server at a time on port **8081**. Switching models evicts the previous server automatically.
- For `llama.cpp` models the launch command is:
  ```
  <server_path> -m <path> --port 8081 --alias <name> [special_arguments]
  ```
- For `Fast_flow` (`flm`) models the launch command is:
  ```
  flm serve <name> -p 8081 --ctx-len 131072


Credits:
llama.cpp https://github.com/ggml-org/llama.cpp and Fast Flow LM https://github.com/FastFlowLM/FastFlowLM powering the backend

This middleware server can serve as a recepticle for any endpoint you like, it has open web UI built into but pointing something expecting an openAI endpoint will allow the reciver to select models and resolve it's own tool requests.
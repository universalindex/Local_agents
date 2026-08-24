# core_backend/main.py

import json
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Any, Union
from agent_loop import agent_loop
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn
from openai import AsyncOpenAI
import httpx
import signal
import time
import models.startup_flags
from tools.schemas import MIDDLEWARE_TOOLS
import models.model_switcher
import tools.cleaning
import asyncio
import sys
import models.clients
#Setting up paths and model manager, don't forget to update your .env file.
Model_Managed = models.model_switcher.VramModelManager(models.model_switcher.MODEL_LIST)



AGENT_SYSTEM_PROMPT = """You are an autonomous, action-oriented coding assistant. Your objective is to solve tasks efficiently by leveraging local tools directly.
- Use tools (`search_web`, `read_webpage`, `search_Pdfs`, `read_Pdf_page`) to verify/ gather information before responding.
- The local directory for search and read pdf tools points to D&D manuals. ALWAYS use the read tool after the search tool if asked for any D&D information.
- For search_pdf use one or two kekywords only.
- Leave one blank line before and after tags. Never nest JSON tool calls inside thinking tags.
- Avoid calling multiple read files/webpages in a single turn. It's ok to do it multiple turns, but avoid gathering tons of information unless absolutely necessary."""


engine_client = models.clients.llama_cpp_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup Phase: Everything before 'yield' runs when the server boots.
    # We do nothing here because your VramModelManager already runs a zombie sweep on init.
    yield
    
    # Teardown Phase: Everything after 'yield' runs when the server receives a shutdown signal.
    print("\n[Lifecycle] FastAPI shutting down. Executing RAM eviction protocol...")
    Model_Managed.stop_active_server()
app = FastAPI(title="Local AI Orchestrator Sidecar Proxy", lifespan=lifespan)
logs = True
# ==========================================
# Data Contracts (OpenAI Spec Pydantic Models)
# ==========================================

class OpenAIMessage(BaseModel):
    role: str
    content: Optional[Union[str, List[Dict[str, Any]]]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

class OpenAITool(BaseModel):
    type: str = "function"
    function: Dict[str, Any]

class OpenAIChatRequest(BaseModel):
    model: str
    messages: List[OpenAIMessage]
    stream: bool = False
    tools: Optional[List[OpenAITool]] = None
    tool_choice: Optional[Any] = None

# ==========================================
# API Endpoints
# ==========================================
@app.get("/api/tags")
async def get_tags():
    return models.startup_flags.ollama_flags(Model_Managed)

@app.get("/models")
@app.get("/v1/models")
@app.get("/api/flags")
async def get_models():
    return models.startup_flags.open_models(Model_Managed)


@app.get("/api/version")
async def mock_ollama_version():
    """Some Open WebUI feature checks gate on parsing this — safe to fake."""
    return {"version": "0.5.7"}
#A nice endpoint to unload the current model without restarting the server.
@app.post("/api/kill")
async def kill_model():
    async with models.clients.generation_lock:
        killed_model = Model_Managed.current_model_id
        await asyncio.to_thread(Model_Managed.stop_active_server)
    return {"unloaded": killed_model}

@app.get("/api/ps")
async def get_processes():
    return models.startup_flags.open_api(Model_Managed)

@app.post("/chat/completions")
@app.post("/v1/chat/completions")
async def chat_completions(request: OpenAIChatRequest):
    initial_history, Android_studio = tools.cleaning.strip_ide_bloat(
        [m.model_dump(exclude_none=True) for m in request.messages]
    )
    inbound_tools = [t.model_dump(exclude_none=True) for t in request.tools] if request.tools else []

    is_vs_code_ide = request.model.endswith("-ide")
    is_ide_request = is_vs_code_ide

    target_model_name = request.model.replace("-ide", "")
    matching_model = next((m for m in Model_Managed.model_list.MODELS if m.display_name == target_model_name), None)
    if not matching_model:
        raise ValueError(f"Model '{target_model_name}' not found.")

    async with models.clients.generation_lock:
        await asyncio.to_thread(Model_Managed.start_server, target_model_name)
        health_url = f"http://127.0.0.1:8081/v1/models"
        for _ in range(300):
            try:
                async with httpx.AsyncClient() as client:
                    if (await client.get(health_url, timeout=1.0)).status_code == 200:
                        break
            except:
                await asyncio.sleep(1.0)

    if not request.stream:
        print("[LOG] Non-streaming request detected. Routing to model.")
        async with models.clients.generation_lock:
            response = await engine_client.chat.completions.create(
                model=matching_model.name,
                messages=initial_history,
                stream=False,
                max_tokens=150,
                temperature=0.7,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}}
            )
        print(f"[TITLE DEBUG] content={response.choices[0].message.content!r} reasoning={getattr(response.choices[0].message, 'reasoning_content', None)!r}")
        return response
    if Android_studio:
        print("[LOG] Trimming Android Studio native tools down to save NPU context.")
        inbound_tools = tools.cleaning.filter_android_studio_tools({"tools": inbound_tools})["tools"]
    if is_ide_request:
        print(f"[LOG] Direct IDE Passthrough Route triggered for: {matching_model.name}")
        async def ide_passthrough():
            try:
                async with models.clients.generation_lock:
                    response_stream = await engine_client.chat.completions.create(
                        model=matching_model.name,
                        messages=initial_history,
                        tools=inbound_tools if inbound_tools else None,
                        stream=True,
                        temperature=0.5,
                        max_tokens=matching_model.context,
                        stream_options={"include_usage": True}
                    )
                    async for chunk in response_stream:
                        yield f"data: {json.dumps(chunk.model_dump(exclude_none=True))}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                error_payload = json.dumps({"choices": [{"index": 0, "delta": {"content": f"\n\nIDE Stream Error: {str(e)}"}}]})
                yield f"data: {error_payload}\n\n"
                yield "data: [DONE]\n\n"
        return StreamingResponse(ide_passthrough(), media_type="text/event-stream")

    if request.messages and request.messages[0].role == "system":
        if request.messages[0].content != AGENT_SYSTEM_PROMPT:
            print("[LOG] Updating system prompt content to match hardcoded Agent Prompt.")
            request.messages[0].content = AGENT_SYSTEM_PROMPT
    else:
        print("[LOG] No system prompt found at index 0. Injecting hardcoded Agent Prompt.")
        request.messages.insert(0, OpenAIMessage(
            role="system",
            content=AGENT_SYSTEM_PROMPT
        ))

    # Rebuild history for the agent path only, now that the system prompt mutation
    # above has actually happened. `initial_history` up top was snapshotted before
    # this mutation, so agent_loop was silently running with no system prompt.
    agent_history, Android_studio = tools.cleaning.strip_ide_bloat(
        [m.model_dump(exclude_none=True) for m in request.messages]
    )
    agent_history = tools.cleaning.canonicalize_history(agent_history)
    middleware_tool_names = [t["function"]["name"] for t in MIDDLEWARE_TOOLS]
    combined_tools = inbound_tools + MIDDLEWARE_TOOLS
    return StreamingResponse(
        agent_loop(matching_model, combined_tools, middleware_tool_names, agent_history, Android_studio),
        media_type="text/event-stream"
    )
    

class NoSignalServer(uvicorn.Server):
    def install_signal_handlers(self):
        pass  # we're installing our own below instead

def handle_sigint(signum, frame):
    print("\n[SIGINT] Force-killing model server before shutdown...")
    Model_Managed.stop_active_server()
    sys.exit(0)

if __name__ == "__main__":
    host_ip = "127.0.0.1" if sys.platform == "win32" else "0.0.0.0"
    print(f"Starting server on {host_ip}:8000...")
    signal.signal(signal.SIGINT, handle_sigint)
    config = uvicorn.Config("main:app", host=host_ip, port=8000, reload=False)
    NoSignalServer(config).run()
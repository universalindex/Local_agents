# core_backend/main.py

import json
from contextlib import asynccontextmanager
import requests
from typing import Dict, List, Optional, Any, Union
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn
from openai import AsyncOpenAI
import httpx
import time
from bs4 import BeautifulSoup
from tools.schemas import MIDDLEWARE_TOOLS
import models.model_switcher
import tools.cleaning
import asyncio
import tools.tool_def

#Setting up paths and model manager, don't forget to update your .env file.
Model_Managed = models.model_switcher.VramModelManager(models.model_switcher.MODEL_LIST)
pdf_directory = models.model_switcher.AppSettings().pdf_directory


AGENT_SYSTEM_PROMPT = """[SYSTEM: LOCAL RESEARCH & CODING AGENT]
- Verify all infomation using tools provided. 
- Use tools (`search_web`, `read_webpage`, `search_Pdfs`, `read_Pdf_page`) to verify/ gather information
- The local directory for search and read pdf tools points to D&D manuals. ALWAYS use the read tool after the search tool Use this for any D&D information.
- CRITICAL: Tool arguments must strictly match required types.
- For `read_pdf_page`, the `page_number` MUST be a single integer (e.g., 94). Do NOT write strings or ranges. Use this tool after the search tool
- For search_pdf use one or two kekywords only.
- Leave one blank line before and after tags. Never nest JSON tool calls inside thinking tags."""


# I don't love this bit but I was having issues with the clients.py and letting the internet know which port I host the model on isn't horrible. 
# Eventually It'll go back though...
engine_client = AsyncOpenAI(

    base_url="http://127.0.0.1:8081/v1", 
    api_key="sk-no-key-required",
    max_retries=0
)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup Phase: Everything before 'yield' runs when the server boots.
    # We do nothing here because your VramModelManager already runs a zombie sweep on init.
    yield
    
    # Teardown Phase: Everything after 'yield' runs when the server receives a shutdown signal.
    print("\n[Lifecycle] FastAPI shutting down. Executing NPU eviction protocol...")
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

generation_lock = asyncio.Lock()
# ==========================================
# API Endpoints
# ==========================================

@app.get("/models")
@app.get("/v1/models")
async def list_models():
    """Populates model dropdowns in Open WebUI and IDE Extensions."""
    model_data = []
    
    for model in Model_Managed.model_list.MODELS:
        model_data.append({
            "id": model.display_name,
            "object": "model",
            "created": int(time.time()), # <-- This is the missing key the IDE requires
            "owned_by": "local-orchestrator"
        })
        
    # FastAPI automatically handles the JSON serialization
    return {"object": "list", "data": model_data}


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

    async with generation_lock:
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
        async with generation_lock:
            response = await engine_client.chat.completions.create(
                model=matching_model.name,
                messages=initial_history,
                stream=False,
                max_tokens=150
            )
        return response
    if Android_studio:
        print("[LOG] Trimming Android Studio native tools down to save NPU context.")
        inbound_tools = tools.cleaning.filter_android_studio_tools({"tools": inbound_tools})["tools"]
    if is_ide_request:
        print(f"[LOG] Direct IDE Passthrough Route triggered for: {matching_model.name}")
        async def ide_passthrough():
            try:
                async with generation_lock:
                    response_stream = await engine_client.chat.completions.create(
                        model=matching_model.name,
                        messages=initial_history,
                        tools=inbound_tools if inbound_tools else None,
                        stream=True,
                        temperature=0.5,
                        max_tokens=2048
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

    middleware_tool_names = [t["function"]["name"] for t in MIDDLEWARE_TOOLS]
    combined_tools = inbound_tools + MIDDLEWARE_TOOLS

    async def agent_loop(current_messages, android_studio):
        try:
            print("[OUTBOUND] Dispatching to LLM server (Waiting for response...)")

            async with generation_lock:
                response = await engine_client.chat.completions.create(
                    model=matching_model.name,
                    messages=current_messages,
                    stream=True,
                    tools=combined_tools,
                    tool_choice="auto",
                    stop=["<|im_end|>", "<|im_start|>", "<|endoftext|>"],
                    max_tokens=2048,
                    extra_body={"thinking_budget_tokens": 256}
                )

                tool_call_id, function_name, function_args = None, "", ""
                is_tool_call = False
                tool_chunk_buffer = []

                async for chunk in response:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.tool_calls:
                        is_tool_call = True
                        clean_tool_chunk = chunk.model_dump(exclude_none=True)
                        tool_chunk_buffer.append(json.dumps(clean_tool_chunk))
                        tc = delta.tool_calls[0]
                        if tc.id: tool_call_id = tc.id
                        if tc.function.name: function_name += tc.function.name
                        if tc.function.arguments: function_args += tc.function.arguments
                    if delta.content is not None or delta.role is not None:
                        clean_chunk = chunk.model_dump(exclude_none=True)
                        if "tool_calls" in clean_chunk["choices"][0]["delta"]:
                            del clean_chunk["choices"][0]["delta"]["tool_calls"]
                        if clean_chunk["choices"][0]["delta"]:
                            yield f"data: {json.dumps(clean_chunk)}\n\n"
            if is_tool_call:
                print(f"\n[TOOL TRIGGERED] '{function_name}'")

                if function_name not in middleware_tool_names:
                    for buffered_chunk in tool_chunk_buffer:
                        yield f"data: {buffered_chunk}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                print(f"[TOOL ROUTING] Running '{function_name}'")

                ui_msg = f"\n\n<details>\n<summary> <b>Tool called:</b> <code>{function_name}</code></summary>\n\n```json\n{function_args}\n```\n</details>\n\n"
                ui_chunk = {
                    "id": "chatcmpl-middleware",
                    "object": "chat.completion.chunk",
                    "model": "default",
                    "choices": [{"index": 0, "delta": {"content": ui_msg}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(ui_chunk)}\n\n"

                try:
                    args_dict = json.loads(function_args)
                except json.JSONDecodeError:
                    args_dict = {}

                tool_result_content = ""
                if function_name == "search_web":
                    query = args_dict.get("query", "")
                    try:
                        searxng_url = "http://127.0.0.1:8080/search"
                        async with httpx.AsyncClient() as async_client:
                            resp = await async_client.get(searxng_url, params={"q": query, "format": "json"}, timeout=10.0)

                        if resp.status_code == 200:
                            results = resp.json().get("results", [])[:5]
                            if not results:
                                tool_result_content = "Search returned no results. Do not search again. Provide a final answer using your existing knowledge."
                                print("[ACTION WARNING] Empty search results.")
                            else:
                                formatted_text = "Here are the search results:\n\n"
                                for i, r in enumerate(results, 1):
                                    title = r.get('title', 'No Title')
                                    url = r.get('url', 'No URL')
                                    content = r.get('content', 'No summary available.')
                                    formatted_text += f"### {i}. {title}\n"
                                    formatted_text += f"- **Source:** {url}\n"
                                    formatted_text += f"- **Snippet:** {content}\n\n"
                                tool_result_content = formatted_text
                                print(f"[ACTION SUCCESS] Passed {len(results)} formatted results to the LLM.")
                    except Exception as e:
                        tool_result_content = f"Web search failed: {str(e)}"

                elif function_name == "read_webpage":
                    url = args_dict.get("url", "")
                    try:
                        headers = {"User-Agent": "Mozilla/5.0"}
                        async with httpx.AsyncClient() as async_client:
                            resp = await async_client.get(url, headers=headers, timeout=10)
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for s in soup(["script", "style", "nav", "footer"]): s.decompose()
                        tool_result_content = soup.get_text(separator="\n", strip=True)[:15000]
                    except Exception as e:
                        tool_result_content = f"Webpage read failed: {str(e)}"

                elif function_name == "search_Pdfs" and not android_studio:
                    query = args_dict.get("query", "")
                    try:
                        tool_result_content = await asyncio.to_thread(tools.tool_def.search_pdfs, query, pdf_directory)
                    except Exception as e:
                        tool_result_content = f"PDF search failed: {str(e)}"

                elif function_name == "read_Pdf_page" and not android_studio:
                    file_path = pdf_directory + "/" + args_dict.get("file_name", "")
                    page_number = tools.tool_def.sanitize_page_number(args_dict.get("page_number", 0))
                    try:
                        tool_result_content = await asyncio.to_thread(tools.tool_def.read_pdf_page, file_path, page_number)
                    except Exception as e:
                        tool_result_content = f"PDF page read failed: {str(e)}"
                else:
                    tool_result_content = f"Unknown tool: {function_name}"

                ui_result = (
                    f"<details>\n"
                    f"<summary><b>Tool Result: {function_name}</b></summary>\n\n"
                    f"{tool_result_content}\n\n"
                    f"</details>\n\n"
                )
                ui_result_chunk = {
                    "id": "chatcmpl-middleware",
                    "object": "chat.completion.chunk",
                    "model": "default",
                    "choices": [{"index": 0, "delta": {"content": ui_result}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(ui_result_chunk)}\n\n"

                current_messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": tool_call_id, "type": "function", "function": {"name": function_name, "arguments": function_args}}]
                })
                current_messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": tool_result_content})

                async for chunk in agent_loop(current_messages, android_studio):
                    yield chunk
            else:
                yield "data: [DONE]\n\n"

        except Exception as e:
            error_payload = json.dumps({"choices": [{"index": 0, "delta": {"content": f"\n\nPipeline Error: {str(e)}"}}]})
            yield f"data: {error_payload}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(agent_loop(agent_history, Android_studio), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
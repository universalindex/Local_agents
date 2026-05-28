# core_backend/main.py

import json
from datetime import datetime
import requests
from typing import Dict, List, Optional, Any, Union
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn
from openai import AsyncOpenAI
import httpx
from bs4 import BeautifulSoup

from tools.schemas import MIDDLEWARE_TOOLS
# Import your Lemonade client (Ensure you created core_backend/models/clients.py)


AGENT_SYSTEM_PROMPT = """ You are a reasearch assitant your job is to find information and help users
You should reason through problems and whenever possible fetch information from the internt or local files to verify and support your ideas, be consice but thorough.
When searching the internet please search for some pages, then read them to gather more detailed information.

CRITICAL INSTRUCTIONS FOR REASONING:
Always enclose your internal thought process inside <think> and </think> tags. 
Ensure there is a blank line before and after your thinking tags.
Do not put tool calls inside your think tags."""


engine_client = AsyncOpenAI(

    base_url="http://127.0.0.1:8081/v1", 
    api_key="sk-no-key-required",
    max_retries=0
)
app = FastAPI(title="Local AI Orchestrator Sidecar Proxy")
logs = True
# ==========================================
# Data Contracts (OpenAI Spec Pydantic Models)
# ==========================================

class OpenAIMessage(BaseModel):
    role: str
    content: Optional[Union[str, List[Dict[str, Any]]]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

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

@app.get("/models")
@app.get("/v1/models")
async def list_models():
    """Populates model dropdowns in Open WebUI and IDE Extensions."""
    return {
        "object": "list",
        "data": [
            {"id": "Qwen MTP-with tools", "object": "model", "owned_by": "local-orchestrator"}
        ]
    }

@app.post("/chat/completions")
@app.post("/v1/chat/completions")
async def chat_completions(request: OpenAIChatRequest):
    """
    The Universal Proxy Router.
    Combines incoming IDE/UI tools with internal middleware web tools.
    """
    # Handle non-streaming requests (like Open WebUI Title Generation)
    if not request.stream:
        print("[LOG] Title generation (non-streaming) requested. Routing to model.")
        # Convert Pydantic history into native dictionaries
        initial_history = [m.model_dump(exclude_none=True) for m in request.messages]
        
        response = await engine_client.chat.completions.create(
            model="default", 
            messages=initial_history,
            stream=False,
            max_tokens=150
        )
        return response
    # 1. Generate the dynamic temporal context
    current_time = datetime.now().strftime("%A, %B %d, %Y %I:%M %p")
    dynamic_system_prompt = f"{AGENT_SYSTEM_PROMPT}\n\nSystem Note: The current date and time is {current_time}."

    # 2. Inject the dynamic prompt instead of the static one
    if request.messages and request.messages[0].role == "system":
        print("[LOG] Overwriting client system prompt with dynamic Agent Prompt.")
        request.messages[0].content = dynamic_system_prompt
    else:
        print("[LOG] Injecting dynamic Agent Prompt at position 0.")
        request.messages.insert(0, OpenAIMessage(
            role="system",
            content=dynamic_system_prompt
        ))
    if request.messages and request.messages[0].role == "system":
        print("[LOG] Overwriting client system prompt with hardcoded Agent Prompt.")
        request.messages[0].content = AGENT_SYSTEM_PROMPT
    else:
        print("[LOG] Injecting hardcoded Agent Prompt at position 0.")
        request.messages.insert(0, OpenAIMessage(
            role="system",
            content=AGENT_SYSTEM_PROMPT
        ))
    # Merge tools provided by the IDE/Frontend with our local Web tools
    inbound_tools = [t.model_dump(exclude_none=True) for t in request.tools] if request.tools else []
    combined_tools = inbound_tools + MIDDLEWARE_TOOLS
    if logs == True:
        print(f"[LOG] Total Available Tool Registry: {[t['function']['name'] for t in combined_tools]}")
    # Identify which tools our middleware must handle internally instead of passing back
    middleware_tool_names = [t["function"]["name"] for t in MIDDLEWARE_TOOLS]

    # Convert Pydantic history into native dictionaries for recursion safety
    initial_history = [m.model_dump(exclude_none=True) for m in request.messages]

    async def agent_loop(current_messages):
        try:
            print("[OUTBOUND] Dispatching to llama.cpp (Waiting for response...)")
            
            response = await engine_client.chat.completions.create(
                model="default", 
                messages=current_messages,
                stream=True,
                tools=combined_tools if combined_tools else None,
                tool_choice="auto",
                # THE BRAKES: This kills the runaway train. 
                # If it tries to start a new turn (<|im_start|>) or end its thought, we kill the stream instantly.
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
                
                # 1. Capture Tool Data
                if delta.tool_calls:
                    is_tool_call = True
                    tool_chunk_buffer.append(chunk.model_dump_json())
                    
                    tc = delta.tool_calls[0]
                    if tc.id: tool_call_id = tc.id
                    if tc.function.name: function_name += tc.function.name
                    if tc.function.arguments: function_args += tc.function.arguments

                # 2. Safely Stream Text to UI
                if delta.content is not None or delta.role is not None:
                    clean_chunk = chunk.model_dump(exclude_none=True)
                    
                    # Strip raw tool data so Open WebUI doesn't try to execute it
                    if "tool_calls" in clean_chunk["choices"][0]["delta"]:
                        del clean_chunk["choices"][0]["delta"]["tool_calls"]
                    
                    # CRITICAL FIX: Only yield if the delta isn't empty! Prevents UI freezing.
                    if clean_chunk["choices"][0]["delta"]:
                        yield f"data: {json.dumps(clean_chunk)}\n\n"

            # 3. Handle Tool Execution
            if is_tool_call:
                print(f"\n[TOOL TRIGGERED] '{function_name}'")
                
                # IDE Tools (e.g., write_file): Pass raw JSON straight back to the editor
                if function_name not in middleware_tool_names:
                    for buffered_chunk in tool_chunk_buffer:
                        yield f"data: {buffered_chunk}\n\n"
                    yield "data: [DONE]\n\n"
                    return 

                # Local Middleware Tools (e.g., search_web): Run locally & show Collapsible UI!
                print(f"[TOOL ROUTING] Running '{function_name}'")
                
                ui_msg = f"\n\n<details>\n<summary> <b>Tool called:</b> <code>{function_name}</code></summary>\n\n```json\n{function_args}\n```\n</details>\n\n"

                ui_chunk = {
                    "id": "chatcmpl-middleware", # Use a standard-looking ID
                    "object": "chat.completion.chunk",
                    "model": "default",
                    "choices": [{"index": 0, "delta": {"content": ui_msg}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(ui_chunk)}\n\n"

                # Parse and execute
                try:
                    args_dict = json.loads(function_args)
                except json.JSONDecodeError:
                    args_dict = {}
                    
                tool_result_content = ""
                
                if function_name == "search_web":
                    query = args_dict.get("query", "")
                    try:
                        searxng_url = "http://127.0.0.1:8080/search" 
                        resp = requests.get(searxng_url, params={"q": query, "format": "json"}, timeout=10)
                        results = resp.json().get("results", [])[:5] 
                        if resp.status_code == 200:
                            results = resp.json().get("results", [])[:5] 
                            
                            if not results:
                                tool_result_content = "Search returned no results. Do not search again. Provide a final answer using your existing knowledge."
                                print("[ACTION WARNING] Empty search results.")
                            else:
                                # THE FIX: Convert raw JSON into a clean Markdown list for the LLM
                                formatted_text = "Here are the search results:\n\n"
                                for i, r in enumerate(results, 1):
                                    title = r.get('title', 'No Title')
                                    url = r.get('url', 'No URL')
                                    content = r.get('content', 'No summary available.')
                                    
                                    # Create a highly readable Markdown structure
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
                        resp = requests.get(url, headers=headers, timeout=10)
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for s in soup(["script", "style", "nav", "footer"]): s.decompose()
                        tool_result_content = soup.get_text(separator="\n", strip=True)[:15000]
                    except Exception as e:
                        tool_result_content = f"Webpage read failed: {str(e)}"
                else:
                    tool_result_content = f"Unknown tool: {function_name}"
                
                current_messages.append({
                    "role": "assistant", 
                    "content": None, 
                    "tool_calls": [{"id": tool_call_id, "type": "function", "function": {"name": function_name, "arguments": function_args}}]
                })
                current_messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": tool_result_content})

                # Loop recursively to let Qwen read the tool output
                async for chunk in agent_loop(current_messages):
                    yield chunk
            else:
                yield "data: [DONE]\n\n"

        except Exception as e:
            error_payload = json.dumps({"choices": [{"delta": {"content": f"\n\nPipeline Error: {str(e)}"}}]})
            yield f"data: {error_payload}\n\n"

    return StreamingResponse(agent_loop(initial_history), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
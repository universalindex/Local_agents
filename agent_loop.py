import json
import asyncio
import models.clients
import tools.tool_defs
import models.model_switcher
import html
import tools.pdf_tools

def finish_chunk(reason):
    return "data: " + json.dumps({
        "id": "chatcmpl-proxy", "object": "chat.completion.chunk", "model": "default",
        "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]
    }) + "\n\n"
#Some static varibles for the agent loop mostly just setting things to be the same everywhere
pdf_directory = models.model_switcher.AppSettings().pdf_directory
engine_client = models.clients.llama_cpp_client
async def agent_loop(matching_model, combined_tools, middleware_tool_names, current_messages, android_studio, raw_request):
        try:
            print("[OUTBOUND] Dispatching to LLM server (Waiting for response...)")
            print("[DEBUG] to model:", len(current_messages), [
    (m["role"], bool(m.get("tool_calls")),
     (m["content"][:80] if isinstance(m.get("content"), str) else type(m.get("content")).__name__))
    for m in current_messages[-3:]
    ])

            async with models.clients.generation_lock:
                response = await engine_client.chat.completions.create(
                    model=matching_model.name,
                    messages=current_messages,
                    stream=True,
                    tools=combined_tools,
                    tool_choice="auto",
                    stop=["<|im_end|>", "<|im_start|>", "<|endoftext|>"],
                    temperature=0.7,
                    max_tokens=matching_model.context,
                    stream_options={"include_usage": True}
                )

                active_tool_calls = {}
                is_tool_call = False
                last_finish = None
                turn_text = ""
                tool_chunk_buffer = []
                chunk_count = 0

                async for chunk in response:
                    chunk_count += 1
                    if chunk_count % 20 == 0 and await raw_request.is_disconnected():
                       print("[LOG] Client disconnected mid-stream, abandoning generation.")
                       return

                    if not chunk.choices:
                        clean_chunk = chunk.model_dump(exclude_none=True)
                        if "usage" in clean_chunk:
                            yield f"data: {json.dumps(clean_chunk)}\n\n"
                        continue
                    delta = chunk.choices[0].delta
                    if chunk.choices[0].finish_reason:
                        last_finish = chunk.choices[0].finish_reason
                    if delta.tool_calls:
                        is_tool_call = True
                        clean_tool_chunk = chunk.model_dump(exclude_none=True)
                        tool_chunk_buffer.append(json.dumps(clean_tool_chunk))
                        
                        # Process all tool calls present in this chunk
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in active_tool_calls:
                                # Initialize tracking for this specific tool call index
                                active_tool_calls[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": ""
                                }
                            
                            if tc.id: 
                                active_tool_calls[idx]["id"] += tc.id
                            if tc.function.name: 
                                active_tool_calls[idx]["name"] += tc.function.name
                            if tc.function.arguments: 
                                active_tool_calls[idx]["arguments"] += tc.function.arguments

                    if delta.content is not None or delta.role is not None or getattr(delta, "reasoning_content", None) is not None:
                        if delta.content:                 # NEW
                            turn_text += delta.content
                        clean_chunk = chunk.model_dump(exclude_none=True)
                        clean_chunk["choices"][0].pop("finish_reason", None)
                        
                        if "tool_calls" in clean_chunk["choices"][0]["delta"]:
                            del clean_chunk["choices"][0]["delta"]["tool_calls"]
                        if clean_chunk["choices"][0]["delta"]:
                            yield f"data: {json.dumps(clean_chunk)}\n\n"

            if is_tool_call:
                assistant_tool_calls_payload = []
                
                # Process each gathered tool call in order
                for idx, tc_data in sorted(active_tool_calls.items()):
                    f_name = tc_data["name"]
                    f_args = tc_data["arguments"]
                    t_id = tc_data["id"]

                    print(f"\n[TOOL TRIGGERED] Index {idx}: '{f_name}'")

                    # If this is a tool meant for the IDE/VS Code and not our middleware
                    if f_name not in middleware_tool_names:
                        print(f"[PASSTHROUGH] f_name={f_name!r} middleware={middleware_tool_names}")
                        for buffered_chunk in tool_chunk_buffer:
                           yield f"data: {buffered_chunk}\n\n"
                        yield finish_chunk("tool_calls")
                        yield "data: [DONE]\n\n"
                        return

                    print(f"[TOOL ROUTING] Running '{f_name}'")

                    try:
                        args_dict = json.loads(f_args)
                        card_args = f_args
                    except json.JSONDecodeError:
                        args_dict = {}
                        card_args = "{}"

                    try:
                        args_dict = json.loads(f_args)
                    except json.JSONDecodeError:
                        args_dict = {}

                    # Execute the specific tool
                    tool_result_content = ""
                    if f_name == "search_web":
                        query = args_dict.get("query", "")
                        tool_result_content = await tools.tool_defs.search_web(query)
                    
                    elif f_name == "read_webpage":
                        url = args_dict.get("url", "")
                        tool_result_content = await tools.tool_defs.read_webpage(url)
                    elif f_name == "search_Pdfs" and not android_studio:
                        query = args_dict.get("query", "")
                        try:
                            tool_result_content = await asyncio.to_thread(tools.pdf_tools.search_pdfs, query, pdf_directory)
                        except Exception as e:
                            tool_result_content = f"PDF search failed: {str(e)}"

                    elif f_name == "read_Pdf_page" and not android_studio:
                        file_path = pdf_directory + "/" + args_dict.get("file_name", "")
                        page_number = tools.pdf_tools.sanitize_page_number(args_dict.get("page_number", 0))
                        try:
                            tool_result_content = await asyncio.to_thread(tools.pdf_tools.read_pdf_page, file_path, page_number)
                        except Exception as e:
                            tool_result_content = f"PDF page read failed: {str(e)}"
                    else:
                        tool_result_content = f"Unknown tool: {f_name}"

                    # Update Open WebUI with output details
                    details_block = (
                        f'\n<details type="tool_calls" done="true" '
                        f'id="{html.escape(t_id)}" name="{html.escape(f_name)}" '
                        f'arguments="{html.escape(card_args)}">\n'
                        f'<summary>Tool Executed</summary>\n'
                        f'{html.escape(json.dumps(tool_result_content, ensure_ascii=False, default=str))}\n'
                        f'</details>\n'
                    )
                    ui_chunk = {"id": "chatcmpl-middleware", "object": "chat.completion.chunk", "model": "default",
                                "choices": [{"index": 0, "delta": {"content": details_block}, "finish_reason": None}]}
                    yield f"data: {json.dumps(ui_chunk)}\n\n"
                   

                    # Collect the tool metadata to return to the LLM context
                    assistant_tool_calls_payload.append({
                        "id": t_id,
                        "type": "function",
                        "function": {"name": f_name, "arguments": f_args}
                    })
                    
                    # Append the tool message outputs back to the active thread
                    current_messages.append({
                        "role": "tool", 
                        "name": f_name,
                        "tool_call_id": t_id, 
                        "content": tool_result_content
                    })

                # Append the assistant block containing ALL the calls we executed
                current_messages.insert(-len(active_tool_calls), {
                    "role": "assistant",
                    "content": turn_text, 
                    "tool_calls": assistant_tool_calls_payload
                })
                # Recurse to generate the final response or handle follow-up tools
                async for chunk in agent_loop(matching_model, combined_tools, middleware_tool_names, current_messages, android_studio, raw_request):
                    yield chunk
            else:
                yield finish_chunk(last_finish or "stop")
                yield "data: [DONE]\n\n"

        except Exception as e:
            error_payload = json.dumps({"choices": [{"index": 0, "delta": {"content": f"\n\nPipeline Error: {str(e)}"}}]})
            yield f"data: {error_payload}\n\n"
            yield finish_chunk("stop")
            yield "data: [DONE]\n\n"
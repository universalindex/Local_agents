from typing import Dict, List, Any
import re
import html
import json


import tools.schemas

TOOL_BLOCK_RE = re.compile(
    r'<details\s+type="tool_calls"(?P<attrs>[^>]*)>\s*'
    r'<summary>[^<]*</summary>\n?(?P<body>.*?)\n?</details>',
    re.DOTALL,
)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
def _parse_tool_block(m, n):
    attrs = {k: html.unescape(v) for k, v in ATTR_RE.findall(m.group("attrs"))}
    raw = attrs.get("result")
    if raw is None:
        raw = html.unescape(m.group("body"))
    try:
        result = json.loads(raw)
        if not isinstance(result, str):
            result = json.dumps(result, ensure_ascii=False)
    except ValueError:
        result = raw
    return {
        "id": attrs.get("id") or f"call_{n}",
        "name": attrs.get("name", ""),
        "arguments": attrs.get("arguments") or "{}",
        "result": result,
    }


def canonicalize_history(messages: list[dict]) -> list[dict]:
    rebuilt = []
    n = 0
    for msg in messages:
        content = msg.get("content")
        if msg.get("role") != "assistant" or not isinstance(content, str) \
                or 'type="tool_calls"' not in content:
            rebuilt.append(msg)
            continue

        matches = list(TOOL_BLOCK_RE.finditer(content))
        if not matches:
            rebuilt.append(msg)
            continue

        pos, i = 0, 0
        while i < len(matches):
            # Text before this tool group becomes that message's content
            # (no separate assistant message, so no adjacent assistants)
            lead = content[pos:matches[i].start()].strip()

            group = [matches[i]]
            j = i + 1
            while j < len(matches) and \
                    content[matches[j-1].end():matches[j].start()].strip() == "":
                group.append(matches[j])
                j += 1

            parsed = []
            for m in group:
                n += 1
                parsed.append(_parse_tool_block(m, n))

            rebuilt.append({
                "role": "assistant",
                "content": lead,
                "tool_calls": [
                    {"id": p["id"], "type": "function",
                     "function": {"name": p["name"], "arguments": p["arguments"]}}
                    for p in parsed
                ],
            })
            for p in parsed:
                rebuilt.append({
                    "role": "tool",
                    "name": p["name"],
                    "tool_call_id": p["id"],
                    "content": p["result"],
                })
            pos, i = group[-1].end(), j

        trailing = content[pos:].strip()
        orig_calls = msg.get("tool_calls")
        if trailing or orig_calls:
            tail = {"role": "assistant", "content": trailing}
            if orig_calls:
                tail["tool_calls"] = orig_calls
            rebuilt.append(tail)
    return rebuilt


def filter_android_studio_tools(data):
    if "tools" in data and isinstance(data["tools"], list):
        original_tools = data["tools"]
        
        # Keep only the whitelisted development and verification tools
        cleaned_tools = [
            t for t in original_tools 
            if t.get("function", {}).get("name") in tools.schemas.ALLOWED_TOOLS
        ]
        
        removed_count = len(original_tools) - len(cleaned_tools)
        
        if removed_count > 0:
            print(f"[ALERT] Stripped {removed_count} heavy internal tools. {len(cleaned_tools)} core tools passed.")
            data["tools"] = cleaned_tools
            
    return data


def strip_ide_bloat(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Translates Android Studio's unsupported 'developer' role to prevent C++ crashes,
    but allows ALL file dumps and IDE context to pass natively to the LLM.
    """
    clean_history = []
    Android_studio = False
    extracted_ide_instructions = ""
    for msg in history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        
        # 1. INTERCEPT THE CRASH TRIGGER: Catch the bleeding-edge Google role
        if role == "developer" and isinstance(content, str):
            extracted_ide_instructions = (
                "ENVIRONMENT: Android Studio IDE.\n"
                "- Output modern Kotlin and Jetpack Compose code matching project structure.\n"
                "- Do not output full files unless requested; focus strictly on modifications."
            )
            Android_studio = True
            continue # Skip adding the raw 'developer' message to the array
            
        # 2. KEEP ABSOLUTELY EVERYTHING ELSE
        # This naturally preserves your System rules, User questions, automated file dumps, 
        # Assistant memories, and Tool results without needing complex if-statements.
        clean_history.append(msg)
                
    # 3. GLUE IT TOGETHER: Append the safe IDE instructions to the master system prompt
    if extracted_ide_instructions and clean_history and clean_history[0].get("role") == "system":
        current_system_content = clean_history[0].get("content", "")
        
        unified_system_content = (
            f"{current_system_content}\n\n"
            f"=== ADDITIONAL ENVIRONMENT INSTRUCTIONS ===\n"
            f"{extracted_ide_instructions}"
        )
        
        clean_history[0]["content"] = unified_system_content
        
    return clean_history, Android_studio
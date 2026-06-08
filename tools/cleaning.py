from typing import Dict, List, Any

def strip_ide_bloat(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Translates Android Studio's unsupported 'developer' role to prevent C++ crashes,
    but allows ALL file dumps and IDE context to pass natively to the LLM.
    """
    clean_history = []
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
        
    return clean_history
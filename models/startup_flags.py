import time
def ollama_flags(Model_Managed):
        """Mocks the Ollama endpoint for Open WebUI and IDEs expecting an Ollama backend."""
        ollama_models = []
        
        for model in Model_Managed.model_list.MODELS:
            ollama_models.append({
                "name": model.display_name,
                "model": model.display_name,
                "modified_at": "2026-01-01T00:00:00.000000000-00:00",
                "size": 0,
                "digest": "sha256:mock",
                "context_length": model.context,
                "context_window": model.context,
                "max_position_embeddings": model.context,
                "permission": [],    # Official OpenAI spec
                "permissions": [],   # Fallback for strict clients
                "aliases": [], 
                "details": {
                    "parent_model": "",
                    "format": "gguf",
                    "family": "llama",
                    "parameter_size": "unknown",
                    "quantization_level": "unknown",
                    "context_length": model.context,
                    "context_window": model.context
                }
            })
            
        return {"models": ollama_models}

def open_models(Model_Managed):
        #Populates model dropdowns in Open WebUI and IDE Extensions.
        model_data = []
        
        for model in Model_Managed.model_list.MODELS:
            model_data.append({
                "id": model.display_name,
                "object": "model",
                "created": int(time.time()), # <-- This is the missing key the IDE requires
                "owned_by": "local-orchestrator",
                            # --- Injecting context metadata for IDEs ---
                "context_length": model.context,           # Common for Continue/CodeGPT
                "max_position_embeddings": model.context,  # HuggingFace standard
                "context_window": model.context,           # Ollama standard
                "max_tokens": model.context  

            })
        # FastAPI automatically handles the JSON serialization
        return {"object": "list", "data": model_data}


def open_api(Model_Managed):
        #Reports currently-loaded models — drives the 'running' indicator in the dropdown."""
        running = []
        active_name = Model_Managed.current_model_id
        if active_name:
            matching_model = next(
                (m for m in Model_Managed.model_list.MODELS if m.display_name == active_name),
                None
            )
            if matching_model:
                running.append({
                    "name": matching_model.display_name,
                    "model": matching_model.display_name,
                    "size": 0,
                    "digest": "sha256:mock",
                    "details": {
                        "parent_model": "",
                        "format": "gguf",
                        "family": "llama",
                        "parameter_size": "unknown",
                        "quantization_level": "unknown"
                    },
                    "expires_at": "2099-01-01T00:00:00Z",
                    "size_vram": 0
                })
        return {"models": running}
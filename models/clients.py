# core_backend/models/clients.py
from openai import AsyncOpenAI
import asyncio
generation_lock = asyncio.Lock()
# This client points to your local Llama.cpp server.
# The SDK requires an api_key string, but Llama.cpp ignores it.
llama_cpp_client = AsyncOpenAI(
    base_url="http://127.0.0.1:8081/v1",
    api_key="sk-no-key-required",
    max_retries=0
)
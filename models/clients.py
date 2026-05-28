# core_backend/models/clients.py

from openai import AsyncOpenAI

# This client points to your local Lemonade server.
# The SDK requires an api_key string, but Lemonade ignores it.
lemonade_client = AsyncOpenAI(
    base_url="http://localhost:8081/api/v1/",
    api_key="local-lemonade-key",
    max_retries= 0
)
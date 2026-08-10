import httpx
from bs4 import BeautifulSoup

async def search_web(query):
    try:
        searxng_url = "http://127.0.0.1:8080/search"
        async with httpx.AsyncClient() as async_client:
            resp = await async_client.get(searxng_url, params={"q": query, "format": "json"}, timeout=10.0)
        tool_result_content = "Not a 200 response from SearXNG. Tell the user to restart it's docker container or for them to check docker logs searxng --tail 100 for the logs"
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
    return tool_result_content

async def read_webpage(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient() as async_client:
            resp = await async_client.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for s in soup(["script", "style", "nav", "footer"]): s.decompose()
        tool_result_content = soup.get_text(separator="\n", strip=True)[:15000]
        
    except Exception as e:
        tool_result_content = f"Webpage read failed: (probbably an invalid URL) {str(e)}"
    return tool_result_content



"""

Tool schemas formatted to the OpenAI specification.

These dictionaries are passed directly into the `tools` parameter of the API request.

"""


MIDDLEWARE_TOOLS =[

    {

        "type": "function",

        "function": {

            "name": "search_web",

            "description": "Searches the internet for information. Returns a list of titles, URLs, and short snippets.",

            "parameters": {

                "type": "object",

                "properties": {

                    "query": {

                        "type": "string",

                        "description": "The exact search query to submit to the search engine."

                    }

                },

                "required": ["query"]

            }

        }

    },
    {
    "type": "function",
    "function": {
        "name": "search_Pdfs",
        "description": "A keyword search to search the local files for ONE or TWO words. ALWAYS use the read PDF page afterwards to grab more information.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The exact text or keyword to search for."},
            },
            "required": ["query"]
        }
    }
    },
    {
    "type": "function",
    "function": {
        "name": "read_Pdf_page",
        "description": "After searching for relavent pages read the complete text from a single specific page of a the PDFs using this tool.",
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string", "description": "A brief explanation of why you are reading this page. This is for your own reasoning and will not be used by the model."},
                "file_name": {"type": "string", "description": "The name of the PDF you're opening"},
                "page_number": {"type": "integer", "description": "CRITICAL: The single whole number page to read (0-indexed). Do NOT pass anything other than a single whole number"}
            },
            "required": ["file_name", "page_number"]
        }
    }
    },
    {

        "type": "function",

        "function": {

            "name": "read_webpage",

            "description": "Downloads and extracts the full text content from a specific URL. Use this when a search snippet does not contain enough detailed information.",

            "parameters": {

                "type": "object",

                "properties": {

                    "url": {

                        "type": "string",

                        "description": "The full HTTP/HTTPS URL of the webpage to read."

                    }

                },

                "required": ["url"]

            }

        }

    }

] 

ALLOWED_TOOLS = {
    # Core File IO
    "read_file", "write_file", 
    
    # Targeted Navigation
    "find_files", "code_search", 
    
    # Strict Code Intelligence
    "resolve_symbol", "find_usages",
    
    # Live Verification
    "search_web", "read_webpage",
    
    # Runtime Debugging
    "gradle_build", "read_logcat"
}
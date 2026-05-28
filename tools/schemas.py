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
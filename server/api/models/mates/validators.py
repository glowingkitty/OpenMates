def validate_llm_endpoint(v: str) -> str:
    valid_endpoints = [
        '/skills/chatgpt/ask',
        '/skills/claude/ask',
        '/skills/gemini/ask'
    ]

    # Check if the input ends with one of the valid endpoints
    if any(v.endswith(endpoint) for endpoint in valid_endpoints):
        return v

    raise ValueError(f"Invalid LLM endpoint. Must end with one of: {', '.join(valid_endpoints)}")

def validate_llm_model(v: str, endpoint: str) -> str:
    valid_models = {
        '/skills/chatgpt/ask': ['gpt-4o', 'gpt-4o-mini'],
        '/skills/claude/ask': ['claude-3.5-sonnet', 'claude-3-haiku'],
        '/skills/gemini/ask': ['gemini-1.5-pro', 'gemini-1.5-flash']
    }

    # Ensure the endpoint starts with a slash
    if not endpoint.startswith('/'):
        endpoint = '/' + endpoint

    # Extract the relevant part of the endpoint if it's a full path
    if endpoint.startswith('/v1/'):
        endpoint_parts = endpoint.split('/')
        if len(endpoint_parts) >= 5:
            endpoint = '/' + '/'.join(endpoint_parts[-3:])

    if endpoint not in valid_models or v not in valid_models[endpoint]:
        raise ValueError(f"Invalid LLM model for endpoint {endpoint}. Must be one of: {', '.join(valid_models[endpoint])}")
    return v
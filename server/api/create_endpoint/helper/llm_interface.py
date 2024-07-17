import os
import anthropic
from typing import Dict

def send_request_to_llm(prompt: str) -> Dict:
    """
    Send a request to Claude (Anthropic's LLM) and get the response.

    Args:
        prompt (str): The prompt to send to the LLM.

    Returns:
        Dict: The response from the LLM.

    Raises:
        Exception: If there's an error in the API call.
    """
    client = anthropic.Anthropic(
        # Assumes the API key is set in the environment variable
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    # Save prompt as markdown file
    save_dir = "saved_prompts"
    os.makedirs(save_dir, exist_ok=True)
    file_name = f"prompt_{len(os.listdir(save_dir)) + 1}.md"
    file_path = os.path.join(save_dir, file_name)

    with open(file_path, "w") as f:
        f.write(prompt)

    try:
        message = client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=4000,
            temperature=0,
            system="You are a software development expert.",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        )
        return {"content": message.content}
    except Exception as e:
        raise Exception(f"Error in LLM API call: {str(e)}")
import os
from dotenv import load_dotenv
import anthropic
from typing import Dict
import json

# Load environment variables from .env file
load_dotenv()


def extract_json(text):
    """
    Extracts the outermost JSON object from a string.
    """
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and start < end:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            return None
    return None


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

        content = message.content[0].text

        # Try to extract JSON content
        json_content = extract_json(content)

        if json_content:
            # Save as JSON file
            with open('llm_response.json', 'w') as json_file:
                json.dump(json_content, json_file, indent=2)
        else:
            # If no valid JSON found, save as markdown
            with open('llm_response.md', 'w') as md_file:
                md_file.write(content)

        return json_content

    except Exception as e:
        raise Exception(f"Error in LLM API call: {str(e)}")
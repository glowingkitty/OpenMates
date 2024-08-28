import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.skills.messages.skills_send_message import MessagesSendInput, MessagesSendOutput, Target, Attachment

# Load environment variables from .env file
load_dotenv()

@pytest.mark.api_dependent
def test_send_discord_messages():
    # Get the API token and other necessary variables from environment variables
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    discord_channel_name = os.getenv('TEST_DISCORD_CHANNEL_NAME')
    ai_mate_username = os.getenv('TEST_AI_MATE_USERNAME')
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"
    assert discord_channel_name, "TEST_DISCORD_CHANNEL_NAME not found in .env file"
    assert ai_mate_username, "TEST_AI_MATE_USERNAME not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }

    # Test case 1: Simple text message
    simple_message = "Hello, this is a simple test message!"
    simple_payload = MessagesSendInput(
        message=simple_message,
        ai_mate_username=ai_mate_username,
        target=Target(team="Discord | OpenMates Development", channel_name=discord_channel_name)
    )

    # Test case: Comprehensive markdown and Discord formatting
    comprehensive_message = """
    # Welcome to our Discord channel! 🎉

    Here's a showcase of various markdown and Discord formatting options:

    ## Text Formatting
    - **Bold text**
    - *Italic text*
    - ***Bold and italic text***
    - __Underlined text__
    - ~~Strikethrough text~~
    - `Inline code`

    ## Lists
    1. Numbered list item 1
    2. Numbered list item 2
       - Nested bullet point
       - Another nested bullet point
    3. Numbered list item 3

    ## Blockquotes
    > This is a blockquote
    >> Nested blockquote

    ## Code Blocks
    ```python
    def greet(name):
        return f"Hello, {name}! Welcome to our community!"
    ```

    ## Tables
    | Header 1 | Header 2 |
    |----------|----------|
    | Cell 1   | Cell 2   |
    | Cell 3   | Cell 4   |

    ## Links
    [Visit our website](https://example.com)

    ## Discord-specific formatting
    • Bullet point using Unicode character
    ‣ Another bullet point style

    Mention a user: @username
    Mention a role: @role
    Mention a channel: #channel-name

    Custom emoji: :custom_emoji_name:

    Spoiler text: ||This is a spoiler||

    ## Horizontal Rule
    ---

    That's all for now! Enjoy exploring these formatting options! 🚀
    """

    comprehensive_payload = MessagesSendInput(
        message=comprehensive_message,
        ai_mate_username=ai_mate_username,
        target=Target(team="Discord | OpenMates Development", channel_name=discord_channel_name)
    )

    test_cases = [
        ("Simple message", simple_payload),
        ("Comprehensive formatting", comprehensive_payload),
    ]

    for test_name, payload in test_cases:
        response = requests.post(
            f"http://0.0.0.0:8000/v1/{team_slug}/skills/messages/send",
            headers=headers,
            json=payload.model_dump()
        )

        assert response.status_code == 200, f"Unexpected status code: {response.status_code} for test case '{test_name}'"

        json_response = response.json()

        try:
            # Validate the response against the MessagesSendOutput model
            output = MessagesSendOutput.model_validate(json_response)
        except ValidationError as e:
            pytest.fail(f"Response does not match the MessagesSendOutput model for test case '{test_name}': {e}")

        # Additional assertions
        assert output.message_id is not None, f"message_id is None for test case '{test_name}'"
        assert output.channel_id is not None, f"channel_id is None for test case '{test_name}'"
        assert output.error is None, f"Unexpected error for test case '{test_name}': {output.error}"

    print("All Discord message send tests passed successfully!")


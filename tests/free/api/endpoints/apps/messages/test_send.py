import pytest
import requests
import os
import base64
from dotenv import load_dotenv
import time
from pydantic import ValidationError
from server.api.models.apps.messages.skills_send_message import MessagesSendInput, MessagesSendOutput, Target, Attachment

# Load environment variables from .env file
load_dotenv()

def load_file_as_base64(file_path):
    with open(file_path, "rb") as file:
        return base64.b64encode(file.read()).decode('utf-8')

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

    # Get the current directory
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Load file attachments
    image_attachment = Attachment(
        filename="test_image.jpg",
        base64_content=load_file_as_base64(os.path.join(current_dir, "attachments/test_image.jpg"))
    )
    py_attachment = Attachment(
        filename="test_script.py",
        base64_content=load_file_as_base64(os.path.join(current_dir, "attachments/test_script.py"))
    )
    md_attachment = Attachment(
        filename="test_document.md",
        base64_content=load_file_as_base64(os.path.join(current_dir, "attachments/test_document.md"))
    )

    # Test case 1: Simple text message
    simple_message = "Hello, this is a simple test message!"
    simple_payload = MessagesSendInput(
        message=simple_message,
        ai_mate_username=ai_mate_username,
        target=Target(team="Discord | OpenMates Development", channel_name=discord_channel_name)
    )

    # Test case 2: Extensive text message with formatting
    extensive_message = """
    **Welcome to our Discord channel!** 🎉

    Here's a showcase of various Discord formatting options:

    **Text Formatting**
    • **Bold text**
    • *Italic text*
    • ***Bold and italic text***
    • __Underlined text__
    • ~~Strikethrough text~~
    • `Inline code`

    **Lists**
    1. Numbered list item 1
    2. Numbered list item 2
       • Nested bullet point
       • Another nested bullet point
    3. Numbered list item 3

    **Blockquotes**
    > This is a blockquote
    > Another line in the same blockquote

    **Code Blocks**
    ```python
    def greet(name):
        return f"Hello, {name}! Welcome to our community!"
    ```

    **Links**
    [Visit our website](https://example.com)

    **Discord-specific formatting**
    • Bullet point using Unicode character
    ‣ Another bullet point style

    Mention a user: @username
    Mention a role: @role
    Mention a channel: #channel-name

    Custom emoji: :custom_emoji_name:

    Spoiler text: ||This is a spoiler||

    That's all for now! Enjoy exploring these formatting options! 🚀
    """
    extensive_payload = MessagesSendInput(
        message=extensive_message,
        ai_mate_username=ai_mate_username,
        target=Target(team="Discord | OpenMates Development", channel_name=discord_channel_name)
    )

    # Test case 3: Simple text and 5 images
    images_payload = MessagesSendInput(
        message="Here are 5 images:",
        ai_mate_username=ai_mate_username,
        target=Target(team="Discord | OpenMates Development", channel_name=discord_channel_name),
        attachments=[image_attachment] * 5
    )

    # Test case 4: Simple text and 2 .py files
    py_files_payload = MessagesSendInput(
        message="Here are 2 Python files:",
        ai_mate_username=ai_mate_username,
        target=Target(team="Discord | OpenMates Development", channel_name=discord_channel_name),
        attachments=[py_attachment] * 2
    )

    # Test case 5: Simple text and 1 markdown file
    md_file_payload = MessagesSendInput(
        message="Here's a Markdown file:",
        ai_mate_username=ai_mate_username,
        target=Target(team="Discord | OpenMates Development", channel_name=discord_channel_name),
        attachments=[md_attachment]
    )

    # Test case 6: Simple text and mixed attachments
    mixed_attachments_payload = MessagesSendInput(
        message="Here are mixed attachments:",
        ai_mate_username=ai_mate_username,
        target=Target(team="Discord | OpenMates Development", channel_name=discord_channel_name),
        attachments=[image_attachment, image_attachment, py_attachment, md_attachment]
    )

    test_cases = [
        ("Simple text message", simple_payload),
        ("Extensive formatted message", extensive_payload),
        ("Simple text with 5 images", images_payload),
        ("Simple text with 2 Python files", py_files_payload),
        ("Simple text with 1 Markdown file", md_file_payload),
        ("Simple text with mixed attachments", mixed_attachments_payload),
    ]

    for test_name, payload in test_cases:
        response = requests.post(
            f"http://0.0.0.0:8000/v1/{team_slug}/apps/messages/send",
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

        time.sleep(1)

    print("All Discord message send tests passed successfully!")


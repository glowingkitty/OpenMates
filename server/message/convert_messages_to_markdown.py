import re
import traceback

def convert_messages_to_markdown(messages):
    try:
        markdown = ""
        for message in messages:
            markdown += "**@{} ({}):**\n".format(message['message_by_user_name'], message['create_at'])
            markdown += "> {}\n".format(message['message'].replace('\n', '\n> '))
            markdown += "- - - -- - - -- - - -\n"
        return markdown
    
    except Exception:
        print("Error in convert_messages_to_markdown():")
        print(traceback.format_exc())
        return False
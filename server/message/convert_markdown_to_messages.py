import re
import traceback

def convert_markdown_to_messages(markdown):
    try:
        data = []
        blocks = re.split(r'- - - -- - - -- - - -\s*', markdown)
        for block in blocks:
            if not block:
                continue
            lines = block.split("\n")
            user_name_time = re.search(r'\*\*@(.*) \((.*)\):\*\*', lines[0])
            user_name = user_name_time.group(1)
            created_at = int(user_name_time.group(2))
            message = "\n".join([line[2:] for line in lines[1:-1]])
            data.append({"message_by_user_name": user_name, "create_at": created_at, "message": message})
        return data
    
    except Exception:
        # print error and return False if there was an exception
        print("Error in convert_markdown_to_messages():")
        print(traceback.format_exc())
        return False
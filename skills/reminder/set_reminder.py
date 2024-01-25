from datetime import datetime
import os
import json
import re
import random


def set_reminder(channel_id:str, thread_id:str, target_user:str, reminder_time:str) -> str:
    try:

        # extract from reminder_time the format YYYY/MM/DD HH:MM AM/PM
        target_date = datetime.strptime(reminder_time, '%Y/%m/%d %I:%M %p')

        response_messages = [
            f"✅ Ok {target_user}, I've set a reminder for this thread at \n**{reminder_time}**",
            f"✅ All set {target_user}! I will remind you about this thread at \n**{reminder_time}**",
            f"✅ Reminder set for this thread at \n**{reminder_time}**\nI will remind you.",
            f"✅ Got it {target_user}, I will remind you about this thread at \n**{reminder_time}**",
            f"✅ Reminder for this thread has been scheduled for \n**{reminder_time}**\nI will remind you, {target_user}.",
            f"✅ Understood {target_user}, I will remind you about this thread at \n**{reminder_time}**",
            f"✅ Sure thing {target_user}, I will remind you about this thread at \n**{reminder_time}**"
        ]

        output = random.choice(response_messages)

        # save reminder and process it in a separate process
        filename = target_date.strftime("%Y_%m_%d_%H_%M")
        # check if json file already exists
        # if it does, append to it
        # else create it
        # check if directory exists
        # if it does, create it
        full_current_path = os.path.realpath(__file__)
        bot_directory = re.sub('skills.*', 'Bot', full_current_path)

        if not os.path.exists(f"{bot_directory}/temp_data/reminders"):
            os.makedirs(f"{bot_directory}/temp_data/reminders")
        if os.path.isfile(f"{bot_directory}/temp_data/reminders/{filename}.json"):
            with open(f"{bot_directory}/temp_data/reminders/{filename}.json", "r") as f:
                reminders = json.load(f)
        else:
            reminders = []

        reminders.append({"channel_id":channel_id, "thread_id":thread_id, "target_user":target_user})
        
        with open(f"{bot_directory}/temp_data/reminders/{filename}.json", "w") as f:
            json.dump(reminders, f)
    
    except ValueError:
        output = f"Sorry @{target_user}. I could not understand the date and time you gave me. When should I remind you?"

    return output


# Define tool for function calling for ChatGPT
tool__set_reminder = {
    "type": "function",
    "function": {
        "name": "set_reminder",
        "description": "Set a reminder, to be reminded about a thread at a specific time.",
        "parameters": {
            "type": "object",
            "properties": {
                "reminder_time": {
                    "type": "string",
                    "description": "The time for the reminder, in the format YYYY/MM/DD HH:MM AM/PM"
                }
            },
            "required": ["reminder_time"]
        }
    }
}
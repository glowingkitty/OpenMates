import sys
import os
import re
import json
from datetime import datetime
import random
import traceback
import time

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server.queue.write_message_to_outgoing_messages import write_message_to_outgoing_messages
from server.error.process_error import process_error


def check_and_send_reminders():
    try:
        # check if a json file with the current datetime exists in the f"{bot_directory}/temp_data/reminders" directory
        # if the directory exists, check if the file exists
        # if the file exists, read it and send reminders
        if os.path.exists(f"{main_directory}/temp_data/reminders"):
            # get current datetime
            current_datetime = datetime.now()
            current_datetime_as_string = current_datetime.strftime('%Y_%m_%d_%H_%M')

            # check if a json file with the current datetime in its name exists
            if os.path.exists(f"{main_directory}/temp_data/reminders/{current_datetime_as_string}.json"):
                # read the json file
                with open(f"{main_directory}/temp_data/reminders/{current_datetime_as_string}.json", "r") as f:
                    reminders = json.load(f)

                # send reminders
                for reminder in reminders:
                    target_user = reminder["target_user"]

                    # get a randomly selected message
                    reminder_messages = [
                        f"hey @{target_user}, you asked me to remind you about this chat.",
                        f"@{target_user}, is now a good time? You wanted to take look again at this chat.",
                        f"Hello @{target_user}, just a friendly reminder about this chat.",
                        f"Hi @{target_user}, don't forget about this chat.",
                        f"@{target_user}, remember to check out this chat when you have a moment.",
                        f"Quick reminder @{target_user}, you wanted to revisit this chat."
                    ]
                    output = random.choice(reminder_messages)

                    # send reminder message to thread with @target_user
                    write_message_to_outgoing_messages(
                        full_message=output,
                        channel_id=reminder["channel_id"],
                        thread_id=reminder["thread_id"],
                        bot_name="remi"
                    )

                # delete the json file
                os.remove(f"{main_directory}/temp_data/reminders/{current_datetime_as_string}.json")

    except Exception:
        process_error(f"While checking and sending reminders", traceback=traceback.format_exc())


if __name__ == "__main__":
    print("Check for reminders and sending them...")
    while True:
        check_and_send_reminders()
        time.sleep(30)
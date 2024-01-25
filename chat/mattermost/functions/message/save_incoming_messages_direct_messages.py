import traceback
import time
import sys
import os
import re
import random

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from chat.mattermost.functions.channel.get_direct_message_channels_for_bot import get_direct_message_channels_for_bot
from chat.mattermost.functions.message.get_all_messages_for_channel import get_all_messages_for_channel
from chat.mattermost.functions.user.get_user_id import get_user_id
from server.queue.write_message_to_incoming_messages_queue import write_message_to_incoming_messages_queue


def save_incoming_messages_direct_messages(bot_name, minutes=1):
    try:
        add_to_log(
            state="start",file_name=os.path.basename(__file__),
            module_name="Mattermost", color="blue")

        messages = []
        bot_id = get_user_id(username=bot_name)
        messages_since_unix = int(time.time()) - (minutes * 60)

        direct_message_channels = get_direct_message_channels_for_bot(bot_name=bot_name)

        for channel in direct_message_channels:
            direct_messages = get_all_messages_for_channel(
                channel_id=channel["channel_id"],
                messages_since_unix=messages_since_unix
            )
            if direct_messages:
                for message in direct_messages:
                    if message["message_by_user_id"] != bot_id:
                        message["type"] = "direct_message"
                        thread = []
                        thread_messages = get_all_messages_for_channel(
                            channel_id=channel["channel_id"]
                        )
                        for thread_message in thread_messages:
                            thread.append(thread_message)
                        thread.sort(key=lambda x: x["create_at"])
                        message["thread"] = thread
                        messages.append(message)

        for message in messages:
            write_message_to_incoming_messages_queue(bot_name=bot_name, message=message)

        add_to_log(
            message="Successfully saved incoming direct messages",
            state="success",file_name=os.path.basename(__file__)
            )
        return True

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to save incoming direct messages", traceback=traceback.format_exc())
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        bot_name = sys.argv[1]
        add_to_log(message=f"Checking for new direct messages every few seconds for {bot_name}...")
        while True:
            if not save_incoming_messages_direct_messages(bot_name):
                add_to_log(message="An error occurred while checking for new direct messages.")
            waiting_time = round(random.uniform(2, 10), 2)
            time.sleep(waiting_time)
    else:
        add_to_log(state="start", module_name="Bot", color="yellow")
        add_to_log(
            state="error",
            message="Bot name not provided as command line argument.",file_name=os.path.basename(__file__)
            )
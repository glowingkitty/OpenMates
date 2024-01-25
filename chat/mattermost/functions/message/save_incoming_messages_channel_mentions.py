import time
import sys
import os
import re
import random

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from chat.mattermost.functions.message.search_messages import search_messages
from chat.mattermost.functions.user.get_user_id import get_user_id
from server.queue.write_message_to_incoming_messages_queue import write_message_to_incoming_messages_queue
from chat.mattermost.functions.message.get_all_messages_in_thread import get_all_messages_in_thread
from server import *

def save_incoming_messages_channel_mentions(bot_name, minutes=1):
    try:
        add_to_log(state="start", module_name="Bot", color="yellow")

        messages = []

        # get bot_id to filter out messages from the bot
        bot_id = get_user_id(username=bot_name)

        # get unix timestamp for x minutes ago
        messages_since_unix = int(time.time()) - (minutes * 60)

        # add new messages from chat.mattermost (messages where the bot has been mentioned)
        mentioned_messages = search_messages(
            bot_name=bot_name,
            messages_since_unix=messages_since_unix)

        # filter out messages from the bot and add to messages list
        for message in mentioned_messages:
            if message["message_by_user_id"] != bot_id:
                message["type"] = "channel_message"
                messages.append(message)

        # save messages to incoming_messages_queue
        for message in messages:
            # if message is in a thread, get all the messages in the thread as well for context
            if message["root_id"] != "":
                thread = []
                thread_messages = get_all_messages_in_thread(thread_id=message["root_id"])
                for thread_message in thread_messages:
                    thread.append(thread_message)
                thread.sort(key=lambda x: x["create_at"])
                
                message["thread"] = thread

            write_message_to_incoming_messages_queue(bot_name=bot_name, message=message)

        add_to_log(state="success", message="Successfully saved incoming messages with mentions.")
        return True

    except KeyboardInterrupt:
        shutdown()

    except Exception as e:
        process_error("Failed to save incoming messages with mentions", traceback=traceback.format_exc())
        shutdown()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        bot_name = sys.argv[1]  # Access the first command line argument
        while True:
            save_incoming_messages_channel_mentions(bot_name)
            # wait a random amount of time between 2 and 10 seconds
            waiting_time = round(random.uniform(1, 3),2)
            time.sleep(waiting_time)
    else:
        add_to_log(state="start", module_name="Bot", color="yellow")
        add_to_log(state="error",message="No bot name provided as a command line argument.")
import os
import re
import traceback

def load_incoming_messages_queue(bot_name="sophia"):
    try:
        # load the message queue from incomingmessages_queue
        full_current_path = os.path.realpath(__file__)
        incomingmessages_queue_path = re.sub('server.*', 'server/incoming_messages_queue', full_current_path)
        if not os.path.exists(incomingmessages_queue_path):
            return []
        
        # check if directory with the name of the bot exists
        bot_directory = os.path.join(incomingmessages_queue_path, bot_name)
        if os.path.exists(bot_directory):
            # return a list with all the paths for all .md files (but without the extension)
            return [os.path.join(bot_directory, f)[:-3] for f in os.listdir(bot_directory) if f.endswith(".md")]
        else:
            return []

    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return []
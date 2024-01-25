import os
import re

def delete_old_error_messages(delete_after_minutes=120):
    try:
        # get the path with the incoming messages queue for the bot name
        full_current_path = os.path.realpath(__file__)


        # get files in folder log/errors

        error_log_folder = re.sub('OpenMates.*', 'OpenMates/log/errors', full_current_path)
        # if the folder doesn't exist, there is nothing to delete
        if not os.path.exists(error_log_folder):
            return

        # get files in folder
        files = os.listdir(error_log_folder)
        # for file in files:
        #     # get unix timestamp from file name
        #     filename = file.split("__")[1]
        #     # if .{filename} in unix_timestamp, remove it
        #     unix_timestamp = int(str(filename).split(".")[0])
        #     # if the unix timestamp is in milliseconds, convert it to seconds
        #     if unix_timestamp > 1000000000000:
        #         unix_timestamp = int(unix_timestamp / 1000)
        #     # if the file is older than x minutes, delete it
        #     unix_timestamp_limit = int(time.time()) - (delete_after_seconds)
        #     if unix_timestamp < unix_timestamp_limit:
        #         os.remove(incoming_messages_queue_folder+"/"+file)

    except Exception:
        print(traceback.format_exc())
        return False
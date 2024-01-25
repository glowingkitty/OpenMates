import os
import re
import traceback
import time

def delete_old_processed_streams(bot_name="sophia",delete_after_seconds=60):
    try:
        # get folder path

        # Get the full path of the current file
        full_current_path = os.path.realpath(__file__)

        stream_id_json_dir = re.sub('server.*', 'server/currently_processed_streams/'+bot_name, full_current_path)
        
        # for file in the directory, split name by check if the unix timestamp is older than x seconds
        if not os.path.exists(stream_id_json_dir):
            return

        # get files in folder
        files = os.listdir(stream_id_json_dir)
        for file in files:
            # get unix timestamp from file name
            filename = file.split("__")[1]
            # if .{filename} in unix_timestamp, remove it
            unix_timestamp = int(str(filename).split(".")[0])
            # if the unix timestamp is in milliseconds, convert it to seconds
            if unix_timestamp > 1000000000000:
                unix_timestamp = int(unix_timestamp / 1000)
            # if the file is older than x minutes, delete it
            unix_timestamp_limit = int(time.time()) - (delete_after_seconds)
            if unix_timestamp < unix_timestamp_limit:
                os.remove(stream_id_json_dir+"/"+file)

        return True
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return False
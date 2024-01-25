import time
import traceback

def check_if_sending_now(message):
    try:
        # check if message is supposed to be send now or later
        if not "scheduled_for_unix" in message:
            return True
        
        # if not "now", then check if the scheduled time is now or in the past
        if message["scheduled_for_unix"] <= int(time.time()):
            return True
        else:
            return False
        
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return False
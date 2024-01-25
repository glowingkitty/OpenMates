import time

previous_stream_messages = {}

def get_message_id_from_previous_stream_message(stream_id):
    if stream_id in previous_stream_messages:
        return previous_stream_messages[stream_id]["message_id"]
    else:
        return None

    
def add_message_id_to_previous_stream_message(stream_id, message_id, remove_after_sec=20):
    previous_stream_messages[stream_id] = {
        "message_id": message_id,
        "time_added": int(time.time())
    }

    # for every key in previous_stream_messages, check if the time added is more than x minutes ago
    # if it is, remove it from the list
    to_be_removed = []
    for key in previous_stream_messages:
        if int(time.time()) - previous_stream_messages[key]["time_added"] > remove_after_sec:
            to_be_removed.append(key)

    for key in to_be_removed:
        del previous_stream_messages[key]

    return True
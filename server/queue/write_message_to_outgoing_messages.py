import json
import traceback
import time
import pika
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from chat.mattermost.functions.channel.get_channel_id import get_channel_id


def write_message_to_outgoing_messages(
        full_message: str, 
        stream_id: str = None,
        channel_name: str = None,
        channel_id: str = None,
        thread_id: str = None,
        bot_name: str = None,
        error_short_code: str = None,
        file_ids: list = None) -> bool:
    
    try:
        add_to_log(state="start", module_name="Bot", color="yellow")

        if not channel_id and channel_name:
            channel_id = get_channel_id(channel_name=channel_name)
        
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
            channel = connection.channel()

            channel.queue_declare(queue=f'outgoing_messages_{bot_name}')

        except pika.exceptions.AMQPConnectionError:
            add_to_log(state="error", message=f"Cant connect to queue 'outgoing_messages_{bot_name}'. Seems that RabbitMQ is not running. Exiting.")
            shutdown(reason="RabbitMQ not running")

        message_dict = {
            "message": full_message,
            "stream_id": stream_id,
            "channel_name": channel_name,
            "channel_id": channel_id,
            "thread_id": thread_id,
            "scheduled_for": "now",
            "error_short_code": error_short_code,
            "file_ids": file_ids
        }
        message = json.dumps(message_dict)
        while True:
            try:
                channel.basic_publish(exchange='', routing_key=f'outgoing_messages_{bot_name}', body=message)
                add_to_log(state="success", message=f"Message successfully published to queue: 'outgoing_messages_{bot_name}'")
                break
            except pika.exceptions.AMQPConnectionError:
                add_to_log(state="error", message=f"Connection was lost. Trying to reconnect to queue 'outgoing_messages_{bot_name}'...")
                time.sleep(3)
                connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
                channel = connection.channel()
                channel.queue_declare(queue=f'outgoing_messages_{bot_name}')

        connection.close()
        return True

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error(f"Failed to write message to queue 'outgoing_messages_{bot_name}'", traceback=traceback.format_exc())
        return False

if __name__ == "__main__":
    write_message_to_outgoing_messages(full_message="Hello World")
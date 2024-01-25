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

messages_written_to_queue = {}

def write_message_to_incoming_messages_queue(bot_name, message):
    try:
        add_to_log(state="start", module_name="Bot", color="yellow")

        # Check if message_id is already a key in messages_written_to_queue
        message_id = message["id"]
        if message_id in messages_written_to_queue:
            add_to_log(f"Message ID '{message_id}' already in queue.")
            return True
        
        # Add message_id as key to messages_written_to_queue
        messages_written_to_queue[message_id] = int(time.time())

        # Clean old messages from messages_written_to_queue
        current_time = int(time.time())
        do_be_deleted = [msg_id for msg_id, timestamp in messages_written_to_queue.items() if timestamp < current_time - 90]
        for msg_id in do_be_deleted:
            del messages_written_to_queue[msg_id]

        # Establish connection to RabbitMQ
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
            channel = connection.channel()
            channel.queue_declare(queue=f'incoming_messages_{bot_name}')
        except pika.exceptions.AMQPConnectionError:
            add_to_log(state="error",message=f"Cant connect to queue 'incoming_messages_{bot_name}'. Seems that RabbitMQ is not running. Exiting.")
            shutdown(reason="RabbitMQ not running")

        # Prepare message for queue
        if not message.get("thread"):
            message["thread"] = [{key: value for key, value in message.items() if key != "thread"}]
        message = json.dumps(message)

        # Publish message to queue
        while True:
            try:
                channel.basic_publish(exchange='', routing_key=f'incoming_messages_{bot_name}', body=message)
                add_to_log(f"Message published to 'queue incoming_messages_{bot_name}'.")
                break
            except pika.exceptions.AMQPConnectionError:
                add_to_log(f"Connection was lost. Trying to reconnect to 'queue messages_{bot_name}'...")
                time.sleep(3)
                connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
                channel = connection.channel()
                channel.queue_declare(queue=f'incoming_messages_{bot_name}')

        return True

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error(f"Failed to write message to queue 'incoming_messages_{bot_name}'", traceback=traceback.format_exc())
        return False

if __name__ == "__main__":
    test_message = {
        "id": "123", 
        "channel_id":get_channel_id("random"), 
        "message": "Test message",
        "message_by_user_name": "sophia",
        }
    write_message_to_incoming_messages_queue("remi", test_message)
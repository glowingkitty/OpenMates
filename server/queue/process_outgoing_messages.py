import json
import sys
import os
import re
import pika
import time

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from chat.mattermost.functions.message.send_message import send_message
from server.message.check_if_sending_now import check_if_sending_now
from server.queue.currently_processed_streams import get_message_id_from_previous_stream_message, add_message_id_to_previous_stream_message
from chat.mattermost.functions.message.update_message import update_message
from server.error.process_error import get_message_id_from_previous_error_message,add_message_id_to_error_details
from chat.mattermost.functions.channel.get_channel_id import get_channel_id



def process_outgoing_messages(bot_name):
    try:
        add_to_log(state="start", module_name="Bot", color="yellow")

        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
            channel = connection.channel()
            channel.queue_declare(queue=f'outgoing_messages_{bot_name}')
        except pika.exceptions.AMQPConnectionError:
            add_to_log(state="error",message=f"Cant connect to queue 'outgoing_messages_{bot_name}'. Seems that RabbitMQ is not running. Exiting.")
            shutdown(reason="RabbitMQ not running")

        

        def callback(ch, method, properties, body):
            add_to_log(f"Processing message from outgoing messages queue for bot '{bot_name}'...")
            message_dict = json.loads(body.decode('utf-8'))
            channel_name = message_dict["channel_name"]

            if check_if_sending_now(message_dict):
                message_id = None
                stream_id_json_was_saved = False
                message_content = message_dict['message']

                if message_dict.get("error_short_code"):
                    message_id = get_message_id_from_previous_error_message(message_dict["error_short_code"])

                if message_dict.get("stream_id"):
                    message_id = get_message_id_from_previous_stream_message(stream_id=message_dict["stream_id"])
                    stream_id_json_was_saved = bool(message_id)
                    stream_id = message_dict["stream_id"]
                else:
                    stream_id = None

                if message_id:
                    add_to_log(f"Updating message with id '{message_id}'...")
                    update_message(
                        message_id=message_id,
                        message=message_content,
                        bot_name=bot_name
                    )
                else:
                    channel_id = message_dict.get("channel_id") or get_channel_id(channel_name) if channel_name != "server" else None
                    add_to_log(f"Sending new message to channel_id {channel_id}...")
                    message_id = send_message(
                        message=message_content,
                        bot_name=bot_name,
                        channel_id=channel_id,
                        thread_id=message_dict.get("thread_id"),
                        file_ids=message_dict.get("file_ids")
                    )

                    if message_dict.get("error_short_code"):
                        add_message_id_to_error_details(
                            message_id=message_id,
                            error_short_code=message_dict["error_short_code"]
                        )

                if stream_id and not stream_id_json_was_saved:
                    add_message_id_to_previous_stream_message(stream_id=stream_id, message_id=message_id)

            else:
                add_to_log("Skipped message. Message scheduled for: " + str(message_dict["scheduled_for"]))

            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_consume(queue=f'outgoing_messages_{bot_name}', on_message_callback=callback, auto_ack=False)

        add_to_log(f"Waiting for outgoing messages for bot '{bot_name}'...")
        while True:
            try:
                channel.start_consuming()
            except pika.exceptions.AMQPConnectionError:
                add_to_log(f"Connection was lost. Trying to reconnect to 'queue outgoing_messages_{bot_name}'...")
                time.sleep(3)
                connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
                channel = connection.channel()
                channel.queue_declare(queue=f'outgoing_messages_{bot_name}')
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to process outgoing messages for bot {bot_name}", traceback=traceback.format_exc())
        shutdown()

if __name__ == "__main__":
    bot_name = sys.argv[1] if len(sys.argv) > 1 else None
    if bot_name:
        process_outgoing_messages(bot_name)
    else:
        add_to_log(state="start", module_name="Bot", color="yellow")
        add_to_log(state="error",message="No bot name provided. Exiting.")
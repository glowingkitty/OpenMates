import json
import sys
import os
import re
import pika
import asyncio
import time

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from skills.intelligence.process_message import process_message
from chat.mattermost.functions.message.send_typing_indicator import send_typing_indicator

# Load saved incoming messages from incoming_messages folder and send them to the chatbot
def process_incoming_messages(bot_name):
    try:
        add_to_log(state="start", module_name="Bot", color="yellow")

        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
            channel = connection.channel()

            channel.queue_declare(queue=f'incoming_messages_{bot_name}')
        except pika.exceptions.AMQPConnectionError:
            add_to_log(state="error",message=f"Cant connect to queue 'incoming_messages_{bot_name}'. Seems that RabbitMQ is not running. Exiting.")
            shutdown(reason="RabbitMQ not running")

        # load the bots into cache
        load_bots(bot_username=bot_name)

        def callback(ch, method, properties, body):
            add_to_log(f"Received a new message for bot '{bot_name}'...")
            # Load message from body
            message_dict = json.loads(body.decode('utf-8'))
            # add_to_log(message_dict, file_name=os.path.basename(__file__))

            # Send a typing indicator to the channel
            send_typing_indicator(
                bot_name=bot_name, 
                channel_id=message_dict['channel_id'], 
                thread_id=message_dict['root_id'] if message_dict.get('root_id') else None
            )

            bots = load_bots(bot_username=bot_name)
            bot = bots[bot_name]

            # Create a new event loop and run the async function in it
            asyncio.run(process_message(
                sender_username=message_dict["message_by_user_name"],
                bot=bot,
                message_history=message_dict["thread"],
                new_message=message_dict["message"],
                channel_id=message_dict['channel_id'],
                thread_id=message_dict['root_id'] if message_dict.get('root_id') else message_dict['id']
            ))
            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_consume(queue=f'incoming_messages_{bot_name}', on_message_callback=callback, auto_ack=False)

        add_to_log(f"Waiting for incoming messages for bot '{bot_name}'...")
        while True:
            try:
                channel.start_consuming()
            except pika.exceptions.AMQPConnectionError:
                add_to_log(f"Connection was lost. Trying to reconnect to queue 'incoming_messages_{bot_name}'...")
                time.sleep(3)
                connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
                channel = connection.channel()
                channel.queue_declare(queue=f'incoming_messages_{bot_name}')
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to process incoming messages for bot '{bot_name}'", traceback=traceback.format_exc())
        shutdown()

if __name__ == "__main__":
    bot_name = sys.argv[1] if len(sys.argv) > 1 else None
    if bot_name:
        process_incoming_messages(bot_name)
    else:
        add_to_log(state="start", module_name="Bot", color="yellow",
            input_variables={"bot_name": bot_name})
        add_to_log(state="error",message="No bot name provided. Exiting.")
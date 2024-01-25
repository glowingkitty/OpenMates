import random
import pika
import json
import traceback
import time
import sys
import os
import re


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error


def start_generate_image(
        channel_id: str,
        target_user: str,
        thread_id: str,
        bot_name: str,
        prompt: str,
        image_shape: str
    ) -> str:
    try:
        # add the request to the queue of image generation requests and return "Ok, working on it!"
        # and once image is generated, send it to the thread (seperate process)

        connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
        channel = connection.channel()

        channel.queue_declare(queue='generate_image')

        message = {
            "channel_id": channel_id,
            "target_user": target_user,
            "thread_id": thread_id,
            "bot_name": bot_name,
            "prompt": prompt,
            "image_shape": image_shape
        }
        print("Sending message to queue generate_image: ", message)

        message = json.dumps(message)
        while True:
            try:
                channel.basic_publish(exchange='', routing_key='generate_image', body=message)
                break
            except pika.exceptions.AMQPConnectionError:
                print(f"Connection was lost. Trying to reconnect to queue generate_image")
                time.sleep(3)
                connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
                channel = connection.channel()

                channel.queue_declare(queue='generate_image')


        response_messages = [
            f"Ok. I am working on it.",
            f"Alright. Starting to work on your request now.",
            f"Understood. I'm starting to create the image.",
            f"Sure thing. Your image is being worked on.",
            f"Right away. I'm getting started on your image.",
            f"Just one moment. I'm starting to work on your image.",
            f"One second. I don't need long to create your image."
        ]

        output = random.choice(response_messages)

        return output
    
    except Exception:
        process_error("Failed adding an image generation request to the pipeline", traceback=traceback.format_exc())
        return "Sorry, something went wrong. Please try again later."


# Define tool for function calling for ChatGPT
tool__start_generate_image = {
    "type": "function",
    "function": {
        "name": "start_generate_image",
        "description": "Generate an image based on a prompt using Dall-E 3 from OpenAI.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The text prompt to generate images from"
                },
                "image_shape": {
                    "type": "string",
                    "enum": ["square", "horizontal", "vertical"],
                    "description": "The format of the generated images"
                }
            },
            "required": ["prompt"]
        }
    }
}
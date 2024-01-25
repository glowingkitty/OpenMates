import pika
import json
import traceback
import time
import sys
import os
import re
import requests
import uuid

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

from skills.images.text_to_image.open_ai.generate_image import generate_image



def process_generate_image_requests():
    try:
        add_to_log(state="start", module_name="Images | Text to image | OpenAI", color="yellow")
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
            channel = connection.channel()

            channel.queue_declare(queue="generate_image")
        except pika.exceptions.AMQPConnectionError:
            add_to_log(state="error",message="Failed to connect to queue 'generate_image'. Probably RabbitMQ is not running. Exiting...")
            shutdown("RabbitMQ is not running")

        def callback(ch, method, properties, body):
            add_to_log("Received generate image request")
            # load message from body
            message_dict = json.loads(body.decode('utf-8'))

            # generate image
            image_info = generate_image(prompt=message_dict["prompt"], image_shape=message_dict["image_shape"])

            add_to_log("Image generated, downloading image...")
            
            # download image
            response = requests.get(image_info["image_url"])

            # generate a filename with a UUID
            filename = str(uuid.uuid4())

            # save image to file
            if not os.path.exists(f"{main_directory}/temp_data/images"):
                os.makedirs(f"{main_directory}/temp_data/images")
            with open(f"{main_directory}/temp_data/images/{filename}.png", "wb") as f:
                f.write(response.content)

            secrets = load_secrets()
            bot_token = secrets["MATTERMOST_ACCESS_TOKEN_" + message_dict["bot_name"].upper()]
            mattermost_domain = secrets["MATTERMOST_DOMAIN"]

            # First, we upload the file
            url = f"{mattermost_domain}/api/v4/files"
            headers = {'Authorization': f'Bearer {bot_token}'}
            data = {'channel_id': message_dict["channel_id"]}
            files = {'files': open(f"{main_directory}/temp_data/images/{filename}.png", 'rb')}
            
            response = requests.post(url, headers=headers, data=data, files=files)
            file_ids = response.json()['file_infos'][0]['id']

            # remove file
            os.remove(f"{main_directory}/temp_data/images/{filename}.png")

            # Then, we create a post with the uploaded file
            url = f"{mattermost_domain}/api/v4/posts"
            headers.update({'Content-Type': 'application/json'})
            data = {
                "message": f"Here is the image you requested. I think the following description fits it well:\n> {message_dict['prompt']}\n\n@{message_dict['target_user']}",
                "channel_id": message_dict["channel_id"],
                "root_id": message_dict["thread_id"],
                "file_ids": [file_ids]
            }

            response = requests.post(url, headers=headers, data=json.dumps(data))

            # acknowledge the message
            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_consume(queue="generate_image", on_message_callback=callback, auto_ack=False)

        add_to_log(f"Waiting for 'generate image' requests...")
        while True:
            try:
                channel.start_consuming()
            except pika.exceptions.AMQPConnectionError:
                add_to_log("Connection was lost. Trying to reconnect to queue generate_image")
                time.sleep(3)
                connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
                channel = connection.channel()
                channel.queue_declare(queue="generate_image")

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to process generate image request", traceback=traceback.format_exc())

if __name__ == "__main__":
    process_generate_image_requests()
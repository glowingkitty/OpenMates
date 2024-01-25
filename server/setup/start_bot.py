import os
import re
import subprocess
import sys
import signal

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

import pika

def start_bot(bot_name):
    try:
        add_to_log(state="start", module_name="Bot", color="yellow")

        # check if the rabbitmq server is running
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
            channel = connection.channel()
        except pika.exceptions.AMQPConnectionError:
            add_to_log(state="error",message=f"Cant connect to RabbitMQ. Seems that RabbitMQ is not running. Exiting.")
            shutdown(reason="RabbitMQ not running")

        # get the full current path
        full_current_path = os.path.realpath(__file__)
        current_dir = re.sub('skills.*', 'Bot', full_current_path)
        main_dir = re.sub('OpenMates.*', 'OpenMates', full_current_path)

        # Define the list of processes
        processes = [
            {"path": f"{main_dir}/server/queue/process_outgoing_messages.py", "process": None},
            {"path": f"{main_dir}/server/queue/process_incoming_messages.py", "process": None},
            {"path": f"{main_dir}/chat/mattermost/functions/message/save_incoming_messages_channel_mentions.py", "process": None},
            {"path": f"{main_dir}/chat/mattermost/functions/message/save_incoming_messages_direct_messages.py", "process": None}
        ]

        # Start the processes
        for process in processes:
            if not os.path.isfile(process["path"]):
                raise FileNotFoundError(f"File {process['path']} does not exist")
            add_to_log(message=f"Starting process '{process['path']}'", line_number=inspect.currentframe().f_lineno, file_name=os.path.basename(__file__))
            process["process"] = subprocess.Popen(["python", process["path"], bot_name])

        if __name__ == "__main__":
            def stop_bots(signal, frame):
                for process in processes:
                    process["process"].terminate()
                shutdown()

            signal.signal(signal.SIGINT, stop_bots)
            signal.pause()

        add_to_log(line_number=inspect.currentframe().f_lineno, file_name=os.path.basename(__file__), state="success", message=f"Successfully started bot processes for {bot_name}")
        return [process["process"] for process in processes]

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error(f"Failed to start bot processes for {bot_name}", traceback=traceback.format_exc())

if __name__ == "__main__":
    if len(sys.argv) > 1:
        start_bot(sys.argv[1])
    else:
        add_to_log(state="start", module_name="Bot", color="yellow")
        add_to_log(state="error", message="No bot name provided. Usage: python start_bot.py <bot_name>")
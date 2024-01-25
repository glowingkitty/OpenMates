import signal
import sys
import os
import re
import subprocess

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from server.setup.load_bots import load_bots
from server.setup.start_bot import start_bot

# TODO replace this with FastAP + webhooks


def start_all_bots():
    try:
        add_to_log(state="start", module_name="Bot", color="yellow")
        bots = load_bots()

        full_current_path = os.path.realpath(__file__)
        current_dir = re.sub('skills.*', 'Bot', full_current_path)
        main_dir = re.sub('OpenMates.*', 'OpenMates', full_current_path)

            
        bot_processes = {}
        for bot in bots["all_usernames"]:
            bot_processes[bot] = start_bot(bot)
        
        # start another subprocess
        reminder_processing = subprocess.Popen(["python", f"{main_dir}/skills/reminder/check_and_send_reminders.py"])
        generate_image_processing = subprocess.Popen(["python", f"{main_dir}/skills/images/text_to_image/open_ai/process_generate_image_requests.py"])
        
        # automatically stop the bot subprocesses and the other subprocess if the user stops the main.py script
        def stop_bots(signal, frame):
            for bot, processes in bot_processes.items():
                for process in processes:
                    process.terminate()
            reminder_processing.terminate()
            generate_image_processing.terminate()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, stop_bots)
        
        # wait for the signal to be received
        signal.pause()

        add_to_log(state="success",
            message=f"Stopped all bots gracefully")

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to start bots", traceback=traceback.format_exc())

if __name__ == "__main__":
    start_all_bots()
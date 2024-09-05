################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

################

import inspect
from loguru import logger

import fitz

# Remove the default handler to stop loguru from logging to the console
logger.remove(0)

# Configure loguru to log to a file with a specific format
logger.add("logs/full_log.log", format="{time} | {level} | {message}", rotation="10 MB", retention="1 day")

previous_module_name = None
previous_module_color = None
previous_file_name = None
previous_input_variables = None
previous_state = None


def get_ansi_color(color: str) -> str:
    colors = {
        # reserved:
        "white": "\033[97m",
        "grey": "\033[90m",
        "green": "\033[92m",
        "red": "\033[91m",
        "end": "\033[0m",
        # available:
        "blue": "\033[94m",
        "yellow": "\033[93m",
        "cyan": "\033[96m",
        "magenta": "\033[95m",
        "orange": "\033[38;5;208m",
    }
    return colors[color]

def shorten_text(text: str, max_length: int = 30) -> str:
    if len(text) > max_length:
        text = text[:max_length] + " ..."
    return text


def get_colored_text(text: str, color: str) -> str:
    return f"{get_ansi_color(color)}{text}{get_ansi_color('end')}"


def get_formatted_variables(variables: dict, variable_color: str, module_color: str) -> str:
    formatted_variables = ""
    max_key_length = max(len(key) for key in variables.keys())
    for key, value in variables.items():
        value = str(value)
        if len(value) > 30:
            value = value[:30] + " ..."
        padding = ' ' * (max_key_length - len(key))
        formatted_variables += f"    {get_colored_text(key+':', module_color)}{padding} '{get_colored_text(value, variable_color)}'\n"+get_colored_text("█", module_color)
    return formatted_variables


def get_module_header(module_name:str, color: str) -> str:
    module_name_length = len(module_name)
    color_length = 60
    spaces_length = color_length - module_name_length
    spaces_on_each_side = spaces_length // 2
    spaces_on_left_side = spaces_on_each_side
    spaces_on_right_side = spaces_length - spaces_on_left_side
    spaces_on_left_side = "█" * spaces_on_left_side
    spaces_on_right_side = "█" * spaces_on_right_side
    module_header = f"\n\n{spaces_on_left_side} {module_name} {spaces_on_right_side}\n"+get_colored_text("█", color)
    module_header = get_colored_text(module_header, color)
    return module_header

def get_bold_text(text):
    BOLD = '\033[1m'
    END = '\033[0m'
    return f"{BOLD}{text}{END}"


def replace_variables_in_message(message: str, input_variables: dict, text_color: str):
    try:
        start_bracket = "'{"
        end_bracket = "}'"
        message = message.replace(start_bracket, f"{get_ansi_color('white')}{start_bracket}")
        message = message.replace(end_bracket, f"{end_bracket}{get_ansi_color('end')}{get_ansi_color(text_color)}")
        input_variables = {k: shorten_text(str(v)) if not isinstance(v, dict) else shorten_text(str(v)) for k, v in input_variables.items()}
        message = message.format(**input_variables)
        return message
    except:
        return str(message)
    

def shorten_text(text: str, max_length: int = 1000) -> str:
    if len(text) > max_length:
        text = text[:max_length] + " ..."
    return text


def add_to_log(
        message: str = None,
        state: str = "progress", 
        module_name: str = None, 
        file_name: str = None,
        color: str = None,
        input_variables: dict = None, 
        output_variables: dict = None,
        line_number: int = None,
        frame: inspect.FrameInfo = None,
        hide_variables: bool = False) -> bool:
    
    if message:
        message = str(message)
    else:
        message = "None"
    
    # get data from the function that called this function
    if not frame:
        frame = inspect.currentframe()
    try:
        prev_frame = frame.f_back
        line_number = prev_frame.f_lineno
        file_name = os.path.basename(prev_frame.f_code.co_filename)
        if hide_variables:
            input_variables = None
        else:
            fitz_classes = [fitz.Document, fitz.Page, fitz.Pixmap]  # Add other fitz classes if needed
            input_variables = {k: shorten_text(str(v)) for k, v in prev_frame.f_locals.items() 
                            if v is not None and k != 'self' and not any(isinstance(v, cls) for cls in fitz_classes)}
    finally:
        del frame

    global previous_module_name
    global previous_module_color
    global previous_file_name
    global previous_input_variables
    global previous_state

    # see if console output should be disabled
    print_to_console = True
    print_to_console = True

    # if file_name does not end with (), add them
    # if file_name and not file_name.endswith("()"):
    #     file_name += "()"

    # if values are not given, use previous ones
    if not line_number:
        line_number = 0
    if not module_name and previous_module_name:
        module_name = previous_module_name
    
    if not file_name and previous_file_name:
        file_name = previous_file_name

    if not input_variables and file_name == previous_file_name:
        input_variables = previous_input_variables

    if color == None and previous_module_color:
        color = previous_module_color
    elif color == None and previous_module_color == None:
        color = "blue"

    # if the module nane has changed, print the module header
    if module_name != previous_module_name:
        module_header = get_module_header(module_name=module_name, color=color)
        # Use logger.info(), logger.debug(), logger.error(), etc. to log messages to the file
        if print_to_console:
            print(module_header)
        logger.info(module_name)
    

    # default_color_block
    default_color_block = get_colored_text("█", color)
    success_color_block = get_colored_text("█", "green")
    fail_color_block = get_colored_text("█", "red")

    if previous_state!="success" and state=="success":
        if print_to_console:
            print(default_color_block+success_color_block*61+"\n"+default_color_block)

    elif previous_state!="error" and state=="error":
        if print_to_console:
            print(default_color_block+fail_color_block*61+"\n"+default_color_block)

    # replace all newlines with newlines and color block
    modified_message = message
    if message:
        message = str(message)
        modified_message = message.replace("\n", "\n"+default_color_block+" ")

    if state == "start":
        if print_to_console:
            print(default_color_block+get_bold_text(get_colored_text(f" {module_name} | {file_name}:{line_number}", color)))
        logger.info(f"{module_name} | {file_name}:{line_number}")
        if input_variables:
            if print_to_console:
                print(default_color_block+get_formatted_variables(
                    variables=input_variables,
                    variable_color="white",
                    module_color=color
                    ))
            # logger.info(input_variables)
            logger.info(f"{module_name} | {file_name}:{line_number} => {input_variables}")

    elif state == "progress":
        logger.info(f"{module_name} | {file_name}:{line_number} => {message}")
        if input_variables:
            modified_message = replace_variables_in_message(
                message=modified_message, 
                input_variables=input_variables, 
                text_color=color
                )
        
        if print_to_console:
            print(default_color_block+"\n"+default_color_block+get_colored_text(f" {module_name} | {file_name}:{line_number} => {modified_message}", color)+"\n"+default_color_block)
        

    elif state == "success":
        logger.success(f"{module_name} | {file_name}:{line_number} => ✓ {message}")
        if input_variables:
            modified_message = replace_variables_in_message(
                message=modified_message, 
                input_variables=input_variables, 
                text_color="green"
                )
        if print_to_console:
            print(default_color_block+"\n"+default_color_block+get_colored_text(f" {module_name} | {file_name}:{line_number} => ✓ {modified_message}", 'green')+"\n"+default_color_block)
        

    elif state == "error":
        logger.error(f"{module_name} | {file_name}:{line_number} => ❌ {message}")
        if input_variables:
            modified_message = replace_variables_in_message(
                message=modified_message, 
                input_variables=input_variables, 
                text_color="red"
                )
        if print_to_console:
            print(default_color_block+"\n"+default_color_block+get_colored_text(f" {module_name} | {file_name}:{line_number} => ❌ {modified_message}", 'red')+"\n"+default_color_block)


    previous_state = state
    previous_file_name = file_name
    previous_input_variables = input_variables
    previous_module_color = color
    previous_module_name = module_name


if __name__ == "__main__":
    add_to_log(
        state="start",
        file_name="add_user_to_channel.py",
        module_name="Mattermost",
        color="blue",
        input_variables={"user": "burton", "channel_name": "server"},
    )

    add_to_log("Adding user...")

    add_to_log(
        state="success",
        message="Added user.",
    )

    add_to_log(
        state="start",
        file_name="send_message.py",
        module_name="OpenAI",
        color="yellow",
        message="Sending message...",
        input_variables={"user": "burton", "channel_name": "server", "message": "Students from Eindhoven University have created Stella Vita, an off-grid EV camper van powered by the sun. This aerodynamic van is equipped with a 2 kW solar array, expandable to 4 kW, and boasts a range of 600 km on a single charge."}
    )

    add_to_log("Sending message to LLM...")

    add_to_log(
        state="error",
        message="Coudn't send the message..."
    )
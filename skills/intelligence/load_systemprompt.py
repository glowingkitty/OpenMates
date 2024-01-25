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

from server.setup.load_config import load_config
from server.setup.load_profile_details import load_profile_details
from server.error.process_error import process_error
from server.logging.add_to_log import add_to_log
from server.shutdown.shutdown import shutdown

from jinja2 import Environment, FileSystemLoader
from jinja2.exceptions import TemplateNotFound
import tiktoken
import traceback


def replace_variables(systemprompt, env, profile_details, config, bot):
    systemprompt_files_mentioned = re.findall(r'\{ (.*?) \}', systemprompt)
    
    if not systemprompt_files_mentioned:
        return systemprompt

    for file in systemprompt_files_mentioned:
        try:
            file_template = env.get_template(file)
            file_filled = file_template.render(profile_details=profile_details, config=config, bot=bot)
            systemprompt = systemprompt.replace("{ "+file+" }", file_filled)
        except TemplateNotFound:
            add_to_log(state="error", message=f"Template {file} not found")
            pass

    return replace_variables(systemprompt, env, profile_details, config, bot)

def load_systemprompt(
        bot_user_name: str = None,
        bot_description: str = None,
        bot_display_name: str = None,
        bot_tools: list = None,
        bot_product_details: list = None,
        extra_data: dict = None,
        special_usecase: str = None) -> str:
    try:
        add_to_log(state="start", module_name="Setup", color="orange")
        if special_usecase:
            add_to_log(f"Loading special use case system prompt...")
        else:
            add_to_log(f"Loading system prompt for {bot_display_name}...")

        full_current_path = os.path.realpath(__file__)
        systemprompts_folder = re.sub('OpenMates.*', 'OpenMates/my_profile/systemprompts', full_current_path)
        if not os.path.exists(systemprompts_folder):
            raise FileNotFoundError(systemprompts_folder+" not found")
        
        systemprompt = ""
        bot = {
            "user_name": bot_user_name,
            "description": bot_description,
            "display_name": bot_display_name,
            "tools": bot_tools,
            "product_details": bot_product_details
            }
        
        # load the data to fill into the templates
        config = load_config()
        profile_details = load_profile_details()

        # Load your systemprompts template folder
        file_loader = FileSystemLoader(systemprompts_folder)
        env = Environment(loader=file_loader)

        # Load the bot specific systemprompt template or special use case template
        if special_usecase:
            systemprompt_template = env.get_template(f"special_usecases/{special_usecase}.md")
        else:
            systemprompt_template = env.get_template(f"bots/{bot_user_name}.md")
        systemprompt = systemprompt_template.render(profile_details=profile_details, config=config, bot=bot, extra_data=extra_data)

        # Replace the for loop with a call to replace_variables
        systemprompt = replace_variables(systemprompt, env, profile_details, config, bot)

        # replace all multiple newlines with a single newline
        systemprompt = re.sub(r'\n{2,}', '\n', systemprompt)

        # add extra new lines for every heading (## or # or ###)
        systemprompt = re.sub(r'\n(#{1,3})', '\n\n\\1', systemprompt)
        
        # count tokens
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
        tokens = len(encoding.encode(systemprompt))

        # get costs
        costs = tokens*(0.01/1000)

        add_to_log(state="success", message=f"Successfully loaded system prompt ({tokens} tokens, {round(costs,4)} USD)")

        return systemprompt

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to load system prompt", traceback=traceback.format_exc())
        return None


if __name__ == "__main__":
    systemprompt = load_systemprompt(
        bot_user_name="burton",
        bot_description="Business development expert",
        bot_display_name="Burton",
        bot_product_details=[
                "name",
                "type",
                "description",
                "public",
                "look",
                "used_tech",
                "highlights",
                "stage",
                "price",
                "currency",
                "payment_type"
            ])
    # print(systemprompt)
    systemprompt = load_systemprompt(
        special_usecase="bank_transactions_processing/sevdesk_germany/extract_invoice_data"
    )
    print(systemprompt)
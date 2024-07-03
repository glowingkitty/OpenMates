


# TODO check if the user has set their own api key in software settings (in this case ChatGPT), if so, use it
if "software_settings" in user and user["software_settings"] and "api_key" in user["software_settings"]:
    api_key = user["software_settings"]["chatgpt"]["api_key"]
else:
    # TODO else if user does not have key set up, check if the user has enough money to use the skill (and server API key)
    # TODO how to calculate requested skill cost? count tokens in message?
    if user["balance"] >= 0.01: # TODO calculate the cost of the skill
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
    else:
        raise ValueError("User does not have enough money to use the skill.")
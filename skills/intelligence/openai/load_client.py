import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

from openai import AsyncOpenAI


async def load_client():
    try:
        add_to_log(state="start", module_name="Skills | Intelligence | OpenAI | Load Client", color="yellow")

        secrets = load_secrets()
        client = AsyncOpenAI(api_key=secrets["OPENAI_API_KEY"])

        add_to_log("Successfully loaded client.", state="success")

        return client
    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to load client", traceback=traceback.format_exc())


if __name__ == "__main__":
    import asyncio
    asyncio.run(load_client())
import traceback
import sys
import os
import re

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from chat.mattermost.functions.channel.get_all_channels_for_bot import get_all_channels_for_bot
from chat.mattermost.functions.user.get_user_name import get_user_name

def get_direct_message_channels_for_bot(bot_name="sophia"):
    try:
        # get all channels for bot and filter for type "D" (direct message)
        channels = get_all_channels_for_bot(bot_name=bot_name)
        direct_message_channels = []
        if channels:
            for channel in channels:
                if channel["type"] == "D":
                    # add the most important information to the list: channel_id, channel_name, chat_partner_names (list)
                    chat_partner_ids = channel["name"].split("__")
                    chat_partners = []
                    # get the names of the partners based on the ids
                    for partner in chat_partner_ids:
                        chat_partners.append({
                            "name":get_user_name(user_id=partner),
                            "id":partner
                            }
                        )

                    direct_message_channels.append({
                        "channel_id": channel["id"],
                        "chat_partners": chat_partners
                    })

        return direct_message_channels

    except Exception:
        # print error and return False if there was an exception
        print(traceback.format_exc())
        return []
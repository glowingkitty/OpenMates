import os
import re
import json
from datetime import datetime
import traceback
import sys
import os
import re


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('workflows.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error

def update_published_date_for_release(version):
    try:
        # Get the full path of the current file
        full_current_path = os.path.realpath(__file__)

        # Replace "OpenMates" and everything that follows with "GlowOS"
        glowos_dir = re.sub('OpenMates.*', 'GlowOS', full_current_path)

        if not os.path.exists(glowos_dir):
            raise Exception(glowos_dir+" not found")
        
        version = version.replace('_', '.').replace('v','')
        # save release date to releases.json in GlowOS folder

        # read releases.json
        with open(glowos_dir+"/usermods/GlowOS/releases.json") as f:
            releases_json = json.load(f)

        # update the published date for the specified version
        for release in releases_json["releases"]:
            if release["version"] == version:
                release["published"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                break

        else:
            raise Exception(f"Version {version} not found in releases.json")

        # write releases.json
        with open(glowos_dir+"/usermods/GlowOS/releases.json", 'w') as f:
            json.dump(releases_json, f)

        print(f"Updated published date for GlowOS version {version} in releases.json")
    
    except Exception:
        process_error(f"While updating the published date for GlowOS version {version.replace('_', '.')}", traceback=traceback.format_exc())


if __name__ == "__main__":
    update_published_date_for_release("v0_16_1")
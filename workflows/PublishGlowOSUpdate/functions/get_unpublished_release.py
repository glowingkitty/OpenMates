import os
import re
import json
import traceback
import sys
import os
import re


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('workflows.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error

# check the releases.json in GlowOS and then the manifests folder in GlowOS-Webinstaller
# return all new releases

def get_unpublished_release(env):
    try:
        # Get the full path of the current file
        full_current_path = os.path.realpath(__file__)

        # Replace "OpenMates" and everything that follows with "GlowOS"
        glowos_dir = re.sub('OpenMates.*', 'GlowOS', full_current_path)

        if not os.path.exists(glowos_dir):
            raise Exception(glowos_dir+" not found")
            
        # get releases.json from GlowOS folder
        releases_json_path = glowos_dir+"/usermods/GlowOS/releases.json"
        if not os.path.exists(releases_json_path):
            raise Exception(releases_json_path+" not found")
        
        # load releases.json and get the latest release
        with open(releases_json_path) as f:
            releases_json = json.load(f)

        latest_release = releases_json["latest"]

        # get all releases from GlowOS-Webinstaller
        glowos_webinstaller_dir = re.sub('OpenMates.*', 'GlowOS-Webinstaller', full_current_path)
        if not os.path.exists(glowos_webinstaller_dir):
            raise Exception(glowos_webinstaller_dir+"not found")
        
        manifests_dir = glowos_webinstaller_dir+"/manifests"
        if not os.path.exists(manifests_dir):
            raise Exception(manifests_dir+" not found")
        
        manifests = os.listdir(manifests_dir)

        # based on the files in {glowos_webinstaller_dir}/manifests/ (for example glowcore_v3_0__glowos_0_15_1_merged.bin)  
        # and based on the releases.json, check if latest version number (but with "." being replaced by "_") is in the manifests folder as a bin file
        version = latest_release
        if "v" not in version:
            version = "v"+version.replace('.', '_')
        if f"{env}__glowos_{version}_merged.bin" not in manifests:
            print(f"{env}__glowos_{version}_merged.bin not found in manifests folder")
            return version
        else:
            return None
        

    except Exception:
        process_error(f"While checking for unpublished GlowOS releases", traceback=traceback.format_exc())
        return []


if __name__ == "__main__":
    unpublished_release = get_unpublished_release("glowcore_v3_0")

    print(unpublished_release)
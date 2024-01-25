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


def create_webinstaller_manifest_json(env,version,chip_family="ESP32-S3"):
    try:
        # Get the full path of the current file
        full_current_path = os.path.realpath(__file__)

        # Replace "OpenMates" and everything that follows with "GlowOS-Webinstaller"
        glowos_webinstaller_dir = re.sub('OpenMates.*', 'GlowOS-Webinstaller', full_current_path)

        if not os.path.exists(glowos_webinstaller_dir):
            raise Exception(glowos_webinstaller_dir+" not found")
        
        if "v" not in version:
            version = "v"+version

        # create manifest json file for webinstaller
        manifest = {
            "name": "GlowOS",
            "version": version.replace('_', '.'),
            "home_assistant_domain": "glowos",
            "new_install_prompt_erase": False,
            "builds": [
                {
                    "chipFamily": chip_family,
                    "parts": [
                        { "path": f"{env}__glowos_{version}_merged.bin", "offset": 0 }
                    ]
                }
            ]
        }

        # then write to webinstaller manifest folder as {env}__glowos_{version}_merged.json
        with open(os.path.join(glowos_webinstaller_dir, "manifests", f"{env}__glowos_{version}_merged.json"), 'w') as f:
            json.dump(manifest, f, indent=None)

        print(f"Manifest file {env}__glowos_{version}_merged.json created")
    
    except Exception:
        process_error(f"While creating the manifest file for GlowOS version {version}", traceback=traceback.format_exc())
    

if __name__ == "__main__":
    create_webinstaller_manifest_json("glowcore_v3_0","0.16.1")
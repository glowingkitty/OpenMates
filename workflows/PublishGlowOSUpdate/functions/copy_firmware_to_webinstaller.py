import os
import re
import shutil
import traceback
import sys
import os
import re


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('workflows.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error


def copy_firmware_to_webinstaller(env,version):
    try:
        # Get the full path of the current file
        full_current_path = os.path.realpath(__file__)

        # Replace "OpenMates" and everything that follows with "GlowOS-Webinstaller"
        glowos_webinstaller_dir = re.sub('OpenMates.*', 'GlowOS-Webinstaller', full_current_path)

        if not os.path.exists(glowos_webinstaller_dir):
            raise Exception(glowos_webinstaller_dir+" not found")
        
        if "v" not in version:
            version = "v"+version.replace('.', '_')
            
        # take an existing firmware_merged and firmware_update file and copy them to web installer
        merged_file = f"firmware/{env}/{env}__glowos_{version}_merged.bin"
        update_file = f"firmware/{env}/{env}__glowos_{version}_update.bin"
        for file in [merged_file, update_file]:
            if not os.path.exists(file):
                raise Exception(f"File {file} not found")
            filname = os.path.basename(file)
            shutil.copy(file, os.path.join(glowos_webinstaller_dir, "manifests", filname))
    

    except Exception:
        process_error(f"While copying the firmware files for GlowOS version {version} to the web installer", traceback=traceback.format_exc())

if __name__ == "__main__":
    copy_firmware_to_webinstaller("glowcore_v3_0","0.16.1")
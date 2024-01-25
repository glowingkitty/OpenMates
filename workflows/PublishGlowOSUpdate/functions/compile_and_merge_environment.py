import os
import re
import shutil
import subprocess
import traceback
import sys
import os
import re


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('workflows.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error

def compile_and_merge_environment(env,version):
    try:
        # Get the full path of the current file
        full_current_path = os.path.realpath(__file__)

        # Replace "OpenMates" and everything that follows with "GlowOS"
        glowos_dir = re.sub('OpenMates.*', 'GlowOS', full_current_path)

        if not os.path.exists(glowos_dir):
            raise Exception(glowos_dir+" not found")
            
        if "v" not in version:
            version = "v"+version.replace('.', '_')

        # Get current user's home directory
        user_home_dir = os.path.expanduser("~")

        # Define variable for the folder paths of the bootloader
        bootloader_folder = user_home_dir+"/.platformio/packages/framework-arduinoespressif32@3.20004.0/tools/sdk"
        boot_app_folder = user_home_dir+"/.platformio/packages/framework-arduinoespressif32@3.20004.0/tools"

        # Delete temp folder if it exists
        temp_folder = "tmp_flashing_files"
        if os.path.exists(temp_folder):
            shutil.rmtree(temp_folder)

        # Execute terminal command with environment variable
        subprocess.run(["platformio", "run", "--environment", env], cwd=glowos_dir)

        # Copy files to temp folder
        os.makedirs(f"{temp_folder}/{env}")
        shutil.copy(glowos_dir+"/.pio/build/{}/firmware.bin".format(env), f"{temp_folder}/{env}")
        shutil.copy(glowos_dir+"/.pio/build/{}/partitions.bin".format(env), f"{temp_folder}/{env}")

        # Execute terminal command with target and environment
        subprocess.run(["platformio", "run", "--target", "buildfs", "--environment", env],cwd=glowos_dir)

        # Copy spiffs.bin file to temp folder
        shutil.copy(glowos_dir+"/.pio/build/{}/spiffs.bin".format(env), f"{temp_folder}/{env}")

        # Execute merge_bin command
        # TODO: firmware crashes after flashing - filestorage issue, cannot write
        cmd = f"python3 -m esptool --chip ESP32-S3 merge_bin -o {temp_folder}/{env}/{env}__glowos_{version}_merged.bin --flash_mode dio --flash_size 8MB 0x0000 {bootloader_folder}/esp32s3/bin/bootloader_dio_80m.bin 0x8000 {temp_folder}/{env}/partitions.bin 0xe000 {boot_app_folder}/partitions/boot_app0.bin 0x10000 {temp_folder}/{env}/firmware.bin 0x410000 {temp_folder}/{env}/spiffs.bin"
        subprocess.run(cmd.split())

        # Construct the destination directory and file paths
        dest_dir = os.path.join(os.path.dirname(temp_folder), 'firmware', env)

        # Create a subfolder with the name of the env if it doesn't exist
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)

        # Move the file
        shutil.move(f"{temp_folder}/{env}/{env}__glowos_{version}_merged.bin", os.path.join(dest_dir, f'{env}__glowos_{version}_merged.bin'))
        shutil.move(f"{temp_folder}/{env}/firmware.bin", os.path.join(dest_dir, f'{env}__glowos_{version}_update.bin'))

        # Delete temp folder
        shutil.rmtree(temp_folder)
        
    except Exception:
        process_error(f"While compiling and merging the firmware for GlowOS version {version}", traceback=traceback.format_exc())

if __name__ == "__main__":
    compile_and_merge_environment("glowcore_v3_0","0.16.1")
import sys
import os
import re
import traceback
import shutil

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('workflows.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error
from functions.get_unpublished_release import get_unpublished_release
from functions.compile_and_merge_environment import compile_and_merge_environment
from functions.copy_firmware_to_webinstaller import copy_firmware_to_webinstaller
from functions.create_webinstaller_manifest_json import create_webinstaller_manifest_json
from functions.add_to_webinstaller_devices_list import add_to_webinstaller_devices_list
from functions.git_push_webinstaller import git_push_webinstaller
from functions.git_pull_glowos import git_pull_glowos
from functions.git_push_glowos import git_push_glowos
from functions.update_published_date_for_release import update_published_date_for_release



class PublishGlowOSUpdate:
    def __init__(self):
        self.environments = [
            "glowcore_v3_0",
            "glowlight_glowtower_v2_0"
        ]
        self.notification_bot = "sophia"

    def republish_new_update(self,version):
        try:
            # publish latest GlowOS update to GlowOS-Webinstaller, without changing version number

            # compile and update all environments
            for env in self.environments:
                compile_and_merge_environment(env,version)
                copy_firmware_to_webinstaller(env,version)
                create_webinstaller_manifest_json(env,version)
                add_to_webinstaller_devices_list(env,version)

                print(f"Republished {env} with version {version}")

            git_push_webinstaller("New release: "+version.replace('_', '.'))
            update_published_date_for_release(version)
            git_push_glowos("New release: "+version.replace('_', '.'))

            # delete the temp firmware folder
            shutil.rmtree("firmware")

            notify_via_bot(
                    bot_name=self.notification_bot,
                    target_channel="software",
                    message=f"🔄 GlowOS version {version.replace('_', '.')} is republished. \n\
                        Both the webinstaller and the GlowOS releases list have been updated."
                )
        
        except Exception:
            process_error(
                file_name=os.path.basename(__file__),
                when_did_error_occure="While republishing the update",
                traceback=traceback.format_exc(),
                file_path=full_current_path,
                local_variables=locals(),
                global_variables=globals()
            )
            

    def process(self):
        try:
            # publish latest GlowOS update to GlowOS-Webinstaller
            unpublished_release_version = None

            # pull latest GlowOS changes
            git_pull_glowos()
            
            # compile and update all environments
            for env in self.environments:
                unpublished_release_version = get_unpublished_release(env)
                if unpublished_release_version is None:
                    print(f"Environment {env} is already up to date")
                else:
                    compile_and_merge_environment(env,unpublished_release_version)
                    copy_firmware_to_webinstaller(env,unpublished_release_version)
                    create_webinstaller_manifest_json(env,unpublished_release_version)
                    add_to_webinstaller_devices_list(env,unpublished_release_version)

                    print(f"Environment {env} updated to version {unpublished_release_version}")
            
            # delete the temp firmware folder
            shutil.rmtree("firmware")

            if unpublished_release_version is not None:
                git_push_webinstaller("New release: "+unpublished_release_version.replace('_', '.'))
                update_published_date_for_release(unpublished_release_version)
                git_push_glowos("New release: "+unpublished_release_version.replace('_', '.'))

                notify_via_bot(
                    bot_name=self.notification_bot,
                    target_channel="software",
                    message=f"🚀 The new GlowOS update is published: {unpublished_release_version.replace('_', '.')}. \n\
                        Both the webinstaller and the GlowOS releases list have been updated."
                )

        except Exception:
            process_error(
                file_name=os.path.basename(__file__),
                when_did_error_occure="While publishing new GlowOS updates",
                traceback=traceback.format_exc(),
                file_path=full_current_path,
                local_variables=locals(),
                global_variables=globals()
            )


if __name__ == "__main__":
    updater = PublishGlowOSUpdate()
    updater.process()

################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################


from server.api.models.skills.atopile.skills_atopile_create_pcb_schematic import AtopileCreatePcbSchematicOutput


async def create_pcb_schematic(
        token: str,
        datasheet_url: str = None,
        # component_lcsc_id: str = None,
        # component_name: str = None,
        # component_requirements: str = None,
        additional_requirements: str = None,
        ai_model: str = "openai__gpt-4o"
    ) -> AtopileCreatePcbSchematicOutput:
    """
    Create a new PCB schematic
    """
    add_to_log("Create PCB schematic ...", module_name="OpenMates | Skills | Atopile | Create PCB Schematic", color="yellow")

    # TODO find the user with the token and check if the user has enough money to use the skill

    # TODO download datasheet from url
    if datasheet_url:
        add_to_log("Downloading datasheet from URL for processing...", module_name="OpenMates | Skills | Atopile | Create PCB Schematic", color="yellow")

    # if component_lcsc_id:
    #     add_to_log("Checking the LCSC database, finding a match based on the ID, downloading the datasheet for processing...", module_name="OpenMates | Skills | Atopile | Create PCB Schematic", color="yellow")

    # if component_name:
    #     add_to_log("Checking the LCSC database, finding a match based on the name, downloading the datasheet for processing...", module_name="OpenMates | Skills | Atopile | Create PCB Schematic", color="yellow")

    # if component_requirements:
    #     add_to_log("Checking the LCSC database, filtering based on the requirements, selecting a component, downloading the datasheet for processing...", module_name="OpenMates | Skills | Atopile | Create PCB Schematic", color="yellow")


    # TODO make screenshots of all the datasheet pages, to then attach to request to LLM


    # TODO send request to LLM to generate the schematic code based on the datasheet, additional requirements, and atopile guidelines

    return {
        "filename": "bq25713.ato",
        "code": "atopile code here..."
    }
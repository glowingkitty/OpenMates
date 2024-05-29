
################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from pydantic import BaseModel, Field, validator


# POST /api/skills/atopile/create_pcb_schematic (create a new PCB schematic)

class AtopileCreatePcbSchematicInput(BaseModel):
    """
    The input data for the AtopileCreatePcbSchematic API endpoint
    """
    datasheet_url: str = Field(None, title="Datasheet URL", description="If you want to generate a schematic based on a datasheet:  \nThe URL of the datasheet for the PCB schematic")
    component_name: str = Field(None, title="Component Name", description="If you instead want to generate a schematic based on a component name:  \nThe name of the component for the PCB schematic")
    component_requirements: str = Field(None, title="Component Requirements", description="If you instead want to generate a schematic based on component requirements:  \nThe requirements for the component for the PCB schematic")
    additional_requirements: str = Field(None, title="Additional Requirements", description="If no requirements are given, it is assumed you want to generate a development board for evaluation purposes. If you have different requirements, please specify them here.")

    # prevent extra fields from being passed to API
    class Config:
        extra = "forbid"

    @validator('datasheet_url')
    def validate_datasheet_url(cls, v):
        # make sure its a pdf file
        if not v.endswith('.pdf'):
            raise ValueError('Datasheet URL must be a PDF file')
        return v


atopile_create_pcb_schematic_input_example = {
    "datasheet_url": "https://www.ti.com/lit/ds/symlink/bq25713.pdf"
}


class AtopileCreatePcbSchematicOutput(BaseModel):
    """
    The output data for the AtopileCreatePcbSchematic API endpoint
    """
    filename: str = Field(..., title="Atopile Filename", description="The filename of the Atopile schematic file")
    code: str = Field(..., title="Atopile Code", description="The code of the Atopile schematic file")


atopile_create_pcb_schematic_output_example = {
    "filename": "bq25713.ato",
    "code": "atopile code here..."
}
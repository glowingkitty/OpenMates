
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

from typing import Literal
from pydantic import BaseModel, Field, validator, root_validator


# POST /api/skills/atopile/create_pcb_schematic (create a new PCB schematic)

class AtopileCreatePcbSchematicInput(BaseModel):
    """
    The input data for the AtopileCreatePcbSchematic API endpoint
    """
    datasheet_url: str = Field(..., title="Datasheet URL", description="If you want to generate a schematic based on a datasheet:  \nThe URL of the datasheet for the PCB schematic")
    # component_lcsc_id: str = Field(None, title="Component LCSC ID", description="If you instead want to generate a schematic based on a component from LCSC / JLCPCB:  \nThe LCSC ID of the component for the PCB schematic")
    # component_name: str = Field(None, title="Component Name", description="If you instead want to generate a schematic based on a component name:  \nThe name of the component for the PCB schematic")
    # component_requirements: str = Field(None, title="Component Requirements", description="If you instead want to generate a schematic based on component requirements:  \nThe requirements for the component for the PCB schematic")
    additional_requirements: str = Field(None, title="Additional Requirements", description="If no requirements are given, it is assumed you want to generate a development board for evaluation purposes. If you have different requirements, please specify them here.")
    ai_model: Literal["openai__gpt-4o","google__gemini-1.5-pro"] = Field("openai__gpt-4o", title="AI Model", description="The large language model to use for generating the schematic code")

    # prevent extra fields from being passed to API
    class Config:
        extra = "forbid"

    # @root_validator(pre=True, skip_on_failure=True)
    # def check_at_least_one_field(cls, values):
    #     datasheet_url = values.get('datasheet_url')
    #     component_lcsc_id = values.get('component_lcsc_id')
    #     component_name = values.get('component_name')
    #     component_requirements = values.get('component_requirements')
    #     if not any([datasheet_url, component_lcsc_id, component_name, component_requirements]):
    #         raise ValueError('At least one of datasheet_url, component_lcsc_id, component_name or component_requirements must be provided')

    #     # also check that if datasheet_url, component_lcsc_id, or component_name is provided, the other fields are not provided
    #     if datasheet_url:
    #         if any([component_lcsc_id, component_name]):
    #             raise ValueError('If datasheet_url is provided, component_lcsc_id, and component_name must not be provided')
    #     elif component_lcsc_id:
    #         if any([datasheet_url, component_name]):
    #             raise ValueError('If component_lcsc_id is provided, datasheet_url, and component_name must not be provided')
    #     elif component_name:
    #         if any([datasheet_url, component_lcsc_id]):
    #             raise ValueError('If component_name is provided, datasheet_url, and component_lcsc_id must not be provided')
    #     return values

    # @validator('component_lcsc_id')
    # def validate_component_lcsc_id(cls, v):
    #     # make sure it starts with C
    #     if not v.startswith('C'):
    #         raise ValueError('Component LCSC ID must start with C')

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
from server.api.models.skills.atopile.skills_atopile_create_pcb_schematic import AtopileCreatePcbSchematicOutput


def create_pcb_schematic(
        datasheet_url: str = None,
        component_name: str = None,
        component_requirements: str = None,
        additional_requirements: str = None
    ) -> AtopileCreatePcbSchematicOutput:
    """
    Create a new PCB schematic
    """

    # TODO generate the schematic file

    return {
        "filename": "bq25713.ato",
        "code": "atopile code here..."
    }
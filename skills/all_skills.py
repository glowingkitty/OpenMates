
# Here is a list of all the skills that are currently available in the system.

class Intelligence():
    def __init__(self):
        self.name = "Intelligence"
        self.description = "Uses large language models for answering questions and fulfilling requests."
        self.icon = "intelligence"
        self.folder = "intelligence"


class YouTube():
    def __init__(self):
        self.name = "YouTube"
        self.description = "Interact with YouTube, the largest video sharing service in the world."
        self.icon = "youtube"
        self.folder = "youtube"




# And here all the functions used for the skill functions, for adding details and reading them.

def skill_function(
        skill,
        function_name: str, 
        function_icon: str,
        function_cost: float=None,
        function_cost_unit: str=None,
        function_uses_other_functions_with_costs: list=[]
        ):
    def decorator(func):
        func.metadata = {
            "function":{
                "name": function_name,
                "icon": function_icon,
            },
            "skill": {
                "name": skill.name,
                "description": skill.description
            }
        }
        if function_cost is not None:
            func.metadata["function"]["cost"] = function_cost
        if function_cost_unit is not None:
            func.metadata["function"]["cost_unit"] = function_cost_unit
        if function_uses_other_functions_with_costs:
            func.metadata["function"]["uses_other_functions_with_costs"] = function_uses_other_functions_with_costs
        return func
    return decorator

def read_metadata(func):
    return func.metadata
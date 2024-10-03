import os
from jinja2 import Environment, FileSystemLoader, select_autoescape
from jinja2.exceptions import TemplateNotFound


def load_prompt(file_path: str, variables: dict = None) -> str:
    """
    Load a prompt from a markdown file and process it using Jinja2 templating.

    :param file_path: Path to the markdown file (relative to the server directory)
    :param variables: Dictionary of variables to use in the template
    :return: Processed prompt as a string
    """
    # Find the base path (up to '/server')
    current_file = os.path.abspath(__file__)
    base_path = current_file.split('/server')[0]

    # Join the base path with the input file_path
    full_path = os.path.join(base_path, file_path.lstrip('/'))

    if not os.path.exists(full_path):
        raise FileNotFoundError(f"Prompt file '{full_path}' not found.")

    template_dir = os.path.dirname(full_path)
    template_name = os.path.basename(full_path)

    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(['html', 'xml']),
        trim_blocks=True,
        lstrip_blocks=True
    )

    try:
        template = env.get_template(template_name)
        return template.render(variables or {})
    except Exception as e:
        raise RuntimeError(f"Error loading or rendering template: {str(e)}")
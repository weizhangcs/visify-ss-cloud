from pathlib import Path
from typing import Any, Dict, Union
from jinja2 import Environment, FileSystemLoader, select_autoescape

class PromptManager:
    """
    A wrapper around Jinja2 for managing and rendering AI prompts.
    """
    def __init__(self, search_path: Union[str, Path]):
        self.search_path = Path(search_path)
        self.env = Environment(
            loader=FileSystemLoader(str(self.search_path)),
            autoescape=select_autoescape(['html', 'xml', 'j2']),
            trim_blocks=True,
            lstrip_blocks=True
        )

    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """
        Renders a template with the given context.
        """
        template = self.env.get_template(template_name)
        return template.render(**context)
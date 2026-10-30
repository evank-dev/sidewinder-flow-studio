"""Chart templates, kept as plain .py files so they can be linted and tested.

They are read as text and registered with SFS; picking one in a Chart node
copies the code into the editor. They are never imported.
"""
from importlib import resources


def read(name: str) -> str:
    return resources.files(__name__).joinpath(f"{name}.py").read_text(encoding="utf-8")

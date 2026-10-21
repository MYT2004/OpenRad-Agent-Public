"""Checkout compatibility paths and packaged, working-directory independent policies."""
from importlib.resources import files

skills_paths = ["./skills/radiation_physics", "./SKILL.md"]


def load_skill_policies():
    root = files('openrad').joinpath('data/policies')
    return {name: root.joinpath(name + '.md').read_text(encoding='utf-8')
            for name in ('global', 'radiation_physics')}

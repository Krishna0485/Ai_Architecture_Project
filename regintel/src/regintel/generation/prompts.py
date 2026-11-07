"""Versioned prompt registry. Prompts live in ``prompts/<name>.v<N>.md`` and are loaded by ID.

File format::

    ---
    id: answer.v1
    task: answer
    ---
    ## system
    ...
    ## user
    ... {{question}} ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    task: str
    system: str
    user: str

    def variables(self) -> set[str]:
        return set(_VAR.findall(self.system)) | set(_VAR.findall(self.user))


class PromptNotFoundError(KeyError):
    pass


def _parse(path: Path) -> PromptTemplate:
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        raise ValueError(f"{path}: missing front matter")
    meta = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    parts = re.split(r"^## (system|user)\s*$", body, flags=re.M)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if "user" not in sections:
        raise ValueError(f"{path}: missing '## user' section")
    expected_id = path.name.removesuffix(".md")
    if meta.get("id") != expected_id:
        raise ValueError(f"{path}: front-matter id {meta.get('id')!r} != {expected_id!r}")
    return PromptTemplate(
        str(meta["id"]), str(meta.get("task", "")), sections.get("system", ""), sections["user"]
    )


class PromptRegistry:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._cache: dict[str, PromptTemplate] = {}

    def get(self, prompt_id: str) -> PromptTemplate:
        if prompt_id not in self._cache:
            path = self.directory / f"{prompt_id}.md"
            if not path.exists():
                raise PromptNotFoundError(prompt_id)
            self._cache[prompt_id] = _parse(path)
        return self._cache[prompt_id]

    def ids(self) -> list[str]:
        return sorted(p.name.removesuffix(".md") for p in self.directory.glob("*.v*.md"))

    def render(self, prompt_id: str, **variables: object) -> tuple[str, str]:
        tpl = self.get(prompt_id)
        missing = tpl.variables() - variables.keys()
        if missing:
            raise KeyError(f"{prompt_id}: missing variables {sorted(missing)}")

        def sub(text: str) -> str:
            return _VAR.sub(lambda m: str(variables[m.group(1)]), text)

        return sub(tpl.system), sub(tpl.user)

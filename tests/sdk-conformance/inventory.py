#!/usr/bin/env python3
"""Enumerate real npm/Python public APIs without importing either SDK runtime.

This tooling may invoke the TypeScript AST scanner; SDK library code never does.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def python_inventory(package: Path | None = None) -> list[str]:
    package = package or ROOT / "packages/openmates-python/openmates"
    classes: dict[str, tuple[set[str], dict[str, str]]] = {}
    aliases: dict[str, str] = {}
    trees = [
        ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(package.rglob("*.py"))
    ]
    for tree in trees:
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                aliases.update(
                    {item.asname: item.name for item in node.names if item.asname}
                )

    def child_class(expression: ast.expr, identity: str) -> str | None:
        if not isinstance(expression, ast.Call):
            return None
        if isinstance(expression.func, ast.Name):
            return aliases.get(expression.func.id, expression.func.id)
        # Existing plan context/activity facades use type(name, (), {...})().
        factory = expression.func
        if (
            isinstance(factory, ast.Call)
            and isinstance(factory.func, ast.Name)
            and factory.func.id == "type"
            and len(factory.args) == 3
            and isinstance(factory.args[2], ast.Dict)
        ):
            fields: set[str] = set()
            children: dict[str, str] = {}
            for key, value in zip(factory.args[2].keys, factory.args[2].values):
                if (
                    not isinstance(key, ast.Constant)
                    or not isinstance(key.value, str)
                    or key.value.startswith("_")
                ):
                    continue
                fields.add(key.value)
                child = child_class(value, identity + "." + key.value)
                if child:
                    children[key.value] = child
            classes[identity] = fields, children
            return identity
        return None

    for tree in trees:
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            members: set[str] = set()
            children: dict[str, str] = {}
            for member in node.body:
                if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not member.name.startswith("_"):
                    members.add(member.name)
                if member.name == "__init__":
                    for statement in ast.walk(member):
                        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                            continue
                        for target in (
                            statement.targets
                            if isinstance(statement, ast.Assign)
                            else [statement.target]
                        ):
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"
                                and not target.attr.startswith("_")
                            ):
                                members.add(target.attr)
                                child = child_class(
                                    statement.value, node.name + "." + target.attr
                                )
                                if child:
                                    children[target.attr] = child
            classes[node.name] = members, children
    barrel = ast.parse((package / "__init__.py").read_text(encoding="utf-8"))
    exports: set[str] = set()
    for node in barrel.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            exports.update(ast.literal_eval(node.value))
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
        ):
            exports.update(ast.literal_eval(node.value))
    symbols = set(exports)
    # Public SDK class spellings and root exports; helper classes are included
    # only through a public facade. Modules are parsed, never imported.
    for name in set(classes) | exports:
        actual = aliases.get(name, name)
        if actual in classes and (name.startswith("OpenMates") or name in exports):
            members, _ = classes[actual]
            symbols.add(name)
            symbols.update(f"{name}.{member}" for member in members)

    def facade(name: str, prefix: str, ancestry: set[str]) -> None:
        if name in ancestry or name not in classes:
            return
        members, children = classes[name]
        symbols.update(f"{prefix}.{member}" for member in members)
        for field, child in children.items():
            if child in classes:
                facade(child, f"{prefix}.{field}", ancestry | {name})

    for name in set(classes) | exports:
        actual = aliases.get(name, name)
        if actual in classes and (name.startswith("OpenMates") or name in exports):
            facade(actual, name, set())
    return sorted(symbols)


def inventory() -> dict:
    process = subprocess.run(
        ["node", str(Path(__file__).with_name("npm-inventory.mjs"))],
        check=True,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    npm = json.loads(process.stdout)
    sys.path.insert(0, str(ROOT / "scripts"))
    from sdk_rust_inventory import discover

    return {"rust": discover(ROOT), "npm": npm["npm"], "python": python_inventory()}


if __name__ == "__main__":
    print(json.dumps(inventory(), sort_keys=True))

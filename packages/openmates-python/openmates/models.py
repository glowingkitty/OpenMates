"""Decrypted presentation types mirroring the Rust `model` module.

Plain immutable values: credentials and key objects never appear in these fields.
JSON field names follow the Rust serde layout (`snake_case` workspaces, camelCase
item fields are already single words).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Workspace(str, Enum):
    CHATS = "chats"
    APPS = "apps"
    PROJECTS = "projects"
    WORKFLOWS = "workflows"
    TASKS = "tasks"
    SETTINGS = "settings"

    @property
    def label(self) -> str:
        return self.value.capitalize()


WORKSPACES = tuple(Workspace)


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    description: str = ""
    status: str = ""
    category: str = ""
    fields: Any = None

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "Item":
        return cls(
            id=value["id"], title=value["title"],
            description=value.get("description", ""), status=value.get("status", ""),
            category=value.get("category", ""), fields=value.get("fields"),
        )


@dataclass(frozen=True)
class Message:
    id: str
    role: str
    content: str
    sender: str = ""
    thinking: str = ""
    embeds: tuple[Item, ...] = ()

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "Message":
        return cls(
            id=value["id"], role=value["role"], content=value["content"],
            sender=value.get("sender", ""), thinking=value.get("thinking", ""),
            embeds=tuple(Item.from_json(item) for item in value.get("embeds", [])),
        )


@dataclass(frozen=True)
class Chat:
    id: str
    title: str
    category: str = ""
    messages: tuple[Message, ...] = field(default_factory=tuple)

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "Chat":
        return cls(
            id=value["id"], title=value["title"], category=value.get("category", ""),
            messages=tuple(Message.from_json(m) for m in value.get("messages", [])),
        )


@dataclass(frozen=True)
class StreamUpdate:
    """Tagged stream event; `kind` is one of the Rust variant names, snake_case."""

    kind: str
    data: dict[str, Any] = field(default_factory=dict)

    KINDS = ("consent", "started", "submitted", "admitted", "content", "completed", "status")

    def __post_init__(self) -> None:
        if self.kind not in self.KINDS:
            raise ValueError("Unknown stream update kind.")


@dataclass(frozen=True)
class Mutation:
    """Tagged workspace mutation; `kind` is create, update, delete, run_workflow or set_setting."""

    kind: str
    data: dict[str, Any] = field(default_factory=dict)

    KINDS = ("create", "update", "delete", "run_workflow", "set_setting")

    def __post_init__(self) -> None:
        if self.kind not in self.KINDS:
            raise ValueError("Unknown mutation kind.")

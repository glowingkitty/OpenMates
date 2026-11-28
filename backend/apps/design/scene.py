"""Canonical editable scenes accepted by the Design skill before client delivery."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

MAX_SCENE_BYTES = 1024 * 1024
MAX_PAGES = 16
MAX_LAYERS = 250
MAX_DIMENSION = 4096
MAX_EDITS = 64
PATH_OPERANDS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Q": 4, "Z": 0}


def _bounded_utf8(limit: int) -> Callable[[str], str]:
    def check(value: str) -> str:
        if any(ord(char) < 32 and char not in "\t\n\r" for char in value):
            raise ValueError("text includes a control character")
        if len(value.encode()) > limit:
            raise ValueError("text exceeds the design byte limit")
        return value
    return check


def _asset_id(value: str) -> str:
    identifier = UUID(value)
    if identifier.int == 0 or str(identifier) != value:
        raise ValueError("asset references must use canonical UUIDs")
    return value


def _path(value: str) -> str:
    commands = iter(value.split())
    command = next(commands, "")
    if command != "M":
        raise ValueError("a path must begin with M")
    count = 0
    while command:
        operands = PATH_OPERANDS.get(command)
        count += 1
        if operands is None or count > 512:
            raise ValueError("unsupported path command")
        for _ in range(operands):
            operand = next(commands, "")
            if "_" in operand or not -MAX_DIMENSION <= float(operand) <= MAX_DIMENSION:
                raise ValueError("path coordinate is outside the design bounds")
        command = next(commands, "")
    return " ".join(value.split())


Identifier = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]
Name = Annotated[str, Field(min_length=1, max_length=256), AfterValidator(_bounded_utf8(256))]
Copy = Annotated[str, Field(min_length=1, max_length=8192), AfterValidator(_bounded_utf8(8192))]
Color = Annotated[str, Field(pattern=r"^#[A-Fa-f0-9]{6}$")]
Coordinate = Annotated[float, Field(ge=-MAX_DIMENSION, le=MAX_DIMENSION)]
Dimension = Annotated[float, Field(ge=1, le=MAX_DIMENSION)]
Angle = Annotated[float, Field(ge=-360, le=360)]
FontSize = Annotated[float, Field(ge=1, le=512)]
Weight = Annotated[float, Field(ge=100, le=900)]
Font = Literal["Sans", "Serif", "Mono"]
AssetId = Annotated[str, Field(min_length=36, max_length=36), AfterValidator(_asset_id)]
Path = Annotated[str, Field(min_length=1, max_length=16_384), AfterValidator(_bounded_utf8(16_384)), AfterValidator(_path)]


class SceneModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class LayerBase(SceneModel):
    id: Identifier
    name: Name
    x: Coordinate
    y: Coordinate
    width: Dimension
    height: Dimension
    rotation: Angle
    hidden: bool | None = None
    locked: bool | None = None


class ShapeLayer(LayerBase):
    kind: Literal["shape"]
    shape: Literal["rectangle", "ellipse"]
    color: Color
    radius: Annotated[float, Field(ge=0, le=MAX_DIMENSION)] | None = None


class TextLayer(LayerBase):
    kind: Literal["text"]
    text: Copy
    font: Font
    font_size: FontSize = Field(alias="fontSize")
    weight: Weight
    color: Color


class ImageLayer(LayerBase):
    kind: Literal["image"]
    asset_id: AssetId = Field(alias="assetId")


class PathLayer(LayerBase):
    kind: Literal["path"]
    path: Path
    view_width: Dimension = Field(alias="viewWidth")
    view_height: Dimension = Field(alias="viewHeight")
    color: Color


Layer = Annotated[ShapeLayer | TextLayer | ImageLayer | PathLayer, Field(discriminator="kind")]


class DesignPage(SceneModel):
    id: Identifier
    name: Name
    width: Dimension
    height: Dimension
    background: Color
    layers: list[Layer] = Field(max_length=MAX_LAYERS)

    @model_validator(mode="after")
    def _unique_layers(self) -> DesignPage:
        if len({layer.id for layer in self.layers}) != len(self.layers):
            raise ValueError("layer IDs must be unique within their page")
        return self


class DesignScene(SceneModel):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    title: Name
    pages: list[DesignPage] = Field(min_length=1, max_length=MAX_PAGES)

    @model_validator(mode="after")
    def _validate_document(self) -> DesignScene:
        if len({page.id for page in self.pages}) != len(self.pages):
            raise ValueError("page IDs must be unique")
        if len(self.wire_json().encode()) > MAX_SCENE_BYTES:
            raise ValueError("scene is too large")
        return self

    def wire_json(self) -> str:
        """The wire form used by the shared Rust Design validator."""
        return self.model_dump_json(by_alias=True, exclude_none=True)

    def assets(self) -> set[str]:
        """References are document-owned IDs, resolved by the client."""
        return {
            layer.asset_id
            for page in self.pages
            for layer in page.layers
            if isinstance(layer, ImageLayer)
        }


class LayerChanges(SceneModel):
    name: Name | None = None
    x: Coordinate | None = None
    y: Coordinate | None = None
    width: Dimension | None = None
    height: Dimension | None = None
    rotation: Angle | None = None
    text: Copy | None = None
    font: Font | None = None
    font_size: FontSize | None = Field(None, alias="fontSize")
    weight: Weight | None = None
    color: Color | None = None


class UpdateLayer(SceneModel):
    kind: Literal["update_layer"]
    page_id: Identifier = Field(alias="pageId")
    layer_id: Identifier = Field(alias="layerId")
    changes: LayerChanges


class AddLayer(SceneModel):
    kind: Literal["add_layer"]
    page_id: Identifier = Field(alias="pageId")
    layer: Layer


class RemoveLayer(SceneModel):
    kind: Literal["remove_layer"]
    page_id: Identifier = Field(alias="pageId")
    layer_id: Identifier = Field(alias="layerId")


DesignEdit = Annotated[UpdateLayer | AddLayer | RemoveLayer, Field(discriminator="kind")]


class DesignEdits(SceneModel):
    operations: list[DesignEdit] = Field(min_length=1, max_length=MAX_EDITS)

    def apply(self, source: DesignScene) -> DesignScene:
        """Apply a whole edit to a copy. An invalid operation leaves the source untouched."""
        document = source.model_dump(by_alias=True, exclude_none=True)
        by_id = {page["id"]: page for page in document["pages"]}
        for operation in self.operations:
            page = by_id.get(operation.page_id)
            if page is None:
                raise ValueError("edit must name an existing page")
            layers = page["layers"]
            if isinstance(operation, AddLayer):
                layers.append(operation.layer.model_dump(by_alias=True, exclude_none=True))
                continue
            layer = next((entry for entry in layers if entry["id"] == operation.layer_id), None)
            if layer is None or layer.get("locked"):
                raise ValueError("edit must name an unlocked layer")
            if isinstance(operation, RemoveLayer):
                layers.remove(layer)
            else:
                layer.update(operation.changes.model_dump(by_alias=True, exclude_none=True))
        result = DesignScene.model_validate(document)
        if result.assets() - source.assets():
            raise ValueError("edits cannot introduce unauthorized assets")
        return result


def parse_draft(answer: str, source: DesignScene | None) -> DesignScene:
    """Read one JSON answer and apply only typed operations for a follow-up."""
    if len(answer.encode()) > MAX_SCENE_BYTES:
        raise ValueError("draft exceeds the design byte limit")
    text = answer.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    value = json.loads(text)
    if source is not None:
        return DesignEdits.model_validate(value).apply(source)
    scene = DesignScene.model_validate(value)
    if scene.assets():
        raise ValueError("new scenes cannot refer to existing private assets")
    return scene

"""Structural validation contracts for STL and 3MF print derivatives.

These helpers validate completed converter output without selecting a conversion
engine. Geometry/manifold analysis is added with the converter implementation;
malformed containers always fail closed and never become print-ready artifacts.
"""

from __future__ import annotations

import io
import math
import struct
import zipfile
from collections import Counter
from dataclasses import dataclass
from xml.etree import ElementTree


_STL_HEADER_BYTES = 84
_STL_TRIANGLE_BYTES = 50
_ALLOWED_UNITS = {"micron", "millimeter", "centimeter", "inch", "foot", "meter"}
_MAX_3MF_ENTRIES = 64
_MAX_3MF_XML_BYTES = 16 * 1024 * 1024
_MAX_3MF_TOTAL_BYTES = 64 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 100
_MAX_XML_ELEMENTS = 500_000


@dataclass(frozen=True)
class PrintExportValidation:
    """Normalized validation result for a print derivative."""

    is_print_ready: bool
    diagnostics: tuple[str, ...]
    units: str | None = None
    part_count: int = 0
    has_color_or_material: bool = False
    geometry_only: bool = False


def validate_stl_export(payload: bytes, *, declared_units: str) -> PrintExportValidation:
    """Validate binary STL structure and separately declared units."""
    diagnostics: list[str] = []
    if declared_units not in _ALLOWED_UNITS:
        diagnostics.append("Declared STL units are unsupported")
    if len(payload) < _STL_HEADER_BYTES:
        diagnostics.append("Binary STL is truncated")
        triangle_count = 0
    else:
        triangle_count = struct.unpack_from("<I", payload, 80)[0]
        expected_size = _STL_HEADER_BYTES + triangle_count * _STL_TRIANGLE_BYTES
        if triangle_count == 0:
            diagnostics.append("Binary STL contains no triangles")
        if expected_size != len(payload):
            diagnostics.append("Binary STL triangle count does not match file size")
        elif triangle_count:
            triangles = [
                struct.unpack_from("<12fH", payload, _STL_HEADER_BYTES + index * _STL_TRIANGLE_BYTES)[3:12]
                for index in range(triangle_count)
            ]
            geometry_diagnostics = _validate_triangle_soup(
                [
                    (
                        tuple(values[0:3]),
                        tuple(values[3:6]),
                        tuple(values[6:9]),
                    )
                    for values in triangles
                ]
            )
            diagnostics.extend(geometry_diagnostics)
    return PrintExportValidation(
        is_print_ready=not diagnostics,
        diagnostics=tuple(diagnostics),
        units=declared_units,
        part_count=1 if triangle_count else 0,
        geometry_only=True,
    )


def validate_3mf_export(payload: bytes) -> PrintExportValidation:
    """Validate the core 3MF ZIP/XML package and manufacturing metadata."""
    diagnostics: list[str] = []
    units: str | None = None
    part_count = 0
    has_material = False
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_3MF_ENTRIES:
                raise ValueError("3MF entry-count limit exceeded")
            if sum(info.file_size for info in infos) > _MAX_3MF_TOTAL_BYTES:
                raise ValueError("3MF uncompressed-size limit exceeded")
            for info in infos:
                if info.file_size > _MAX_3MF_XML_BYTES and info.filename == "3D/3dmodel.model":
                    raise ValueError("3MF model XML size limit exceeded")
                if info.file_size and info.file_size / max(info.compress_size, 1) > _MAX_COMPRESSION_RATIO:
                    raise ValueError("3MF compression-ratio limit exceeded")
            names = {info.filename for info in infos}
            if "3D/3dmodel.model" not in names:
                raise ValueError("3MF package is missing 3D/3dmodel.model")
            if any(name.startswith("/") or ".." in name.split("/") for name in names):
                raise ValueError("3MF package contains an unsafe path")
            model_data = archive.read("3D/3dmodel.model")
        if b"<!DOCTYPE" in model_data.upper() or b"<!ENTITY" in model_data.upper():
            raise ValueError("3MF model XML contains a forbidden declaration")
        root = ElementTree.fromstring(model_data)
        elements = list(root.iter())
        if len(elements) > _MAX_XML_ELEMENTS:
            raise ValueError("3MF XML element-count limit exceeded")
        units = root.attrib.get("unit")
        if units not in _ALLOWED_UNITS:
            diagnostics.append("3MF unit is missing or unsupported")
        objects = [element for element in elements if _local_name(element.tag) == "object"]
        build_items = [element for element in elements if _local_name(element.tag) == "item"]
        materials = [
            element
            for element in elements
            if _local_name(element.tag)
            in {"basematerials", "colorgroup", "texture2d", "texture2dgroup", "compositematerials"}
        ]
        part_count = len(objects)
        has_material = bool(materials)
        object_ids = {element.attrib.get("id") for element in objects}
        if any(item.attrib.get("objectid") not in object_ids for item in build_items):
            diagnostics.append("3MF build references an unknown object")
        printable_triangles = 0
        for object_element in objects:
            mesh = next((child for child in object_element if _local_name(child.tag) == "mesh"), None)
            if mesh is None:
                continue
            vertices_element = next((child for child in mesh if _local_name(child.tag) == "vertices"), None)
            triangles_element = next((child for child in mesh if _local_name(child.tag) == "triangles"), None)
            if vertices_element is None or triangles_element is None:
                diagnostics.append("3MF mesh is missing vertices or triangles")
                continue
            vertices = [_parse_3mf_vertex(vertex) for vertex in vertices_element]
            faces: list[tuple[int, int, int]] = []
            for triangle in triangles_element:
                try:
                    face = tuple(int(triangle.attrib[key]) for key in ("v1", "v2", "v3"))
                except (KeyError, ValueError):
                    diagnostics.append("3MF triangle has invalid indices")
                    continue
                if any(index < 0 or index >= len(vertices) for index in face):
                    diagnostics.append("3MF triangle references an unknown vertex")
                    continue
                faces.append(face)
            printable_triangles += len(faces)
            diagnostics.extend(
                _validate_triangle_soup([(vertices[a], vertices[b], vertices[c]) for a, b, c in faces])
            )
        if not objects or not printable_triangles:
            diagnostics.append("3MF model contains no printable mesh")
    except (ValueError, zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        diagnostics.append(str(exc) or "Invalid 3MF package")
    return PrintExportValidation(
        is_print_ready=not diagnostics,
        diagnostics=tuple(diagnostics),
        units=units,
        part_count=part_count,
        has_color_or_material=has_material,
        geometry_only=False,
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_3mf_vertex(element: ElementTree.Element) -> tuple[float, float, float]:
    try:
        return tuple(float(element.attrib[key]) for key in ("x", "y", "z"))
    except (KeyError, ValueError) as exc:
        raise ValueError("3MF vertex has invalid coordinates") from exc


def _validate_triangle_soup(
    triangles: list[tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]],
) -> list[str]:
    diagnostics: list[str] = []
    edges: Counter[tuple[tuple[float, ...], tuple[float, ...]]] = Counter()
    directed_edges: Counter[tuple[tuple[float, ...], tuple[float, ...]]] = Counter()
    face_keys: set[tuple[tuple[float, ...], ...]] = set()
    vertex_links: dict[tuple[float, ...], dict[tuple[float, ...], set[tuple[float, ...]]]] = {}
    for first, second, third in triangles:
        if not all(math.isfinite(value) for vertex in (first, second, third) for value in vertex):
            diagnostics.append("Mesh contains non-finite coordinates")
            continue
        ab = tuple(second[index] - first[index] for index in range(3))
        ac = tuple(third[index] - first[index] for index in range(3))
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        if sum(value * value for value in cross) <= 1e-20:
            diagnostics.append("Mesh contains a degenerate triangle")
        face_key = tuple(sorted((first, second, third)))
        if face_key in face_keys:
            diagnostics.append("Mesh contains a duplicate triangle")
        face_keys.add(face_key)
        for start, end in ((first, second), (second, third), (third, first)):
            edges[tuple(sorted((start, end)))] += 1
            directed_edges[(start, end)] += 1
        for vertex, neighbor_a, neighbor_b in (
            (first, second, third),
            (second, third, first),
            (third, first, second),
        ):
            links = vertex_links.setdefault(vertex, {})
            links.setdefault(neighbor_a, set()).add(neighbor_b)
            links.setdefault(neighbor_b, set()).add(neighbor_a)
    if triangles and any(count != 2 for count in edges.values()):
        diagnostics.append("Mesh is not a closed two-manifold surface")
    if any(
        count == 2
        and not (
            directed_edges[(edge[0], edge[1])] == 1
            and directed_edges[(edge[1], edge[0])] == 1
        )
        for edge, count in edges.items()
    ):
        diagnostics.append("Mesh has inconsistent face orientation")
    for links in vertex_links.values():
        if not links:
            continue
        start = next(iter(links))
        visited: set[tuple[float, ...]] = set()
        stack = [start]
        while stack:
            neighbor = stack.pop()
            if neighbor in visited:
                continue
            visited.add(neighbor)
            stack.extend(links.get(neighbor, set()) - visited)
        if len(visited) != len(links) or any(len(adjacent) != 2 for adjacent in links.values()):
            diagnostics.append("Mesh has a non-manifold vertex link")
            break
    return list(dict.fromkeys(diagnostics))

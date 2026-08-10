# backend/tests/test_models3d_print_exports.py
#
# Format-aware contracts for generated 3D-print derivatives.
# STL is geometry-only and receives declared units from OpenMates metadata.
# 3MF carries units, parts, and supported color/material declarations internally.
# Conversion implementation remains independent from these validation contracts.

from __future__ import annotations

import io
import struct
import zipfile

from backend.apps.models3d.tasks.export_print_task import validate_3mf_export, validate_stl_export


def _binary_stl(*, degenerate: bool = False, duplicate_face: bool = False) -> bytes:
    header = b"OpenMates test STL".ljust(80, b"\0")
    vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
    faces = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]
    if degenerate:
        faces[0] = (0, 0, 1)
    if duplicate_face:
        faces[1] = faces[0]
    triangles = b"".join(
        struct.pack("<12fH", 0, 0, 1, *vertices[a], *vertices[b], *vertices[c], 0)
        for a, b, c in faces
    )
    return header + struct.pack("<I", len(faces)) + triangles


def _three_mf() -> bytes:
    model = b'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources><basematerials id="1"><base name="orange" displaycolor="#FF8800"/></basematerials>
  <object id="2" type="model"><mesh><vertices>
    <vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/><vertex x="0" y="1" z="0"/><vertex x="0" y="0" z="1"/>
  </vertices><triangles>
    <triangle v1="0" v2="2" v3="1" pid="1" p1="0"/><triangle v1="0" v2="1" v3="3" pid="1" p1="0"/>
    <triangle v1="1" v2="2" v3="3" pid="1" p1="0"/><triangle v1="2" v2="0" v3="3" pid="1" p1="0"/>
  </triangles></mesh></object></resources>
  <build><item objectid="2"/></build>
</model>'''
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("3D/3dmodel.model", model)
    return buffer.getvalue()


def test_binary_stl_is_geometry_only_and_uses_declared_metadata_units() -> None:
    result = validate_stl_export(_binary_stl(), declared_units="millimeter")

    assert result.is_print_ready is True
    assert result.geometry_only is True
    assert result.units == "millimeter"
    assert result.has_color_or_material is False


def test_3mf_preserves_internal_units_parts_and_color_metadata() -> None:
    result = validate_3mf_export(_three_mf())

    assert result.is_print_ready is True
    assert result.units == "millimeter"
    assert result.part_count == 1
    assert result.has_color_or_material is True


def test_invalid_print_exports_return_diagnostics_not_fake_ready_files() -> None:
    stl = validate_stl_export(b"truncated", declared_units="millimeter")
    three_mf = validate_3mf_export(b"not-a-zip")

    assert stl.is_print_ready is False
    assert stl.diagnostics
    assert three_mf.is_print_ready is False
    assert three_mf.diagnostics


def test_degenerate_stl_is_not_print_ready() -> None:
    result = validate_stl_export(_binary_stl(degenerate=True), declared_units="millimeter")
    assert result.is_print_ready is False
    assert any("degenerate" in diagnostic.lower() for diagnostic in result.diagnostics)


def test_duplicate_or_same_winding_stl_is_not_print_ready() -> None:
    result = validate_stl_export(
        _binary_stl(duplicate_face=True),
        declared_units="millimeter",
    )
    assert result.is_print_ready is False
    assert any(
        term in " ".join(result.diagnostics).lower()
        for term in ("duplicate", "orientation", "manifold")
    )


def test_3mf_rejects_zip_bomb_metadata_before_decompression() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", b" " * (17 * 1024 * 1024))
    result = validate_3mf_export(buffer.getvalue())
    assert result.is_print_ready is False
    assert any("limit" in diagnostic.lower() for diagnostic in result.diagnostics)

"""Entry point run inside the embroidery sandbox: check, prepare, export, report, preview.

Usage (inside the sandbox, from the directory that contains this package):

    python -m embroidery_sandbox.pipeline check   <workdir>
    python -m embroidery_sandbox.pipeline convert <workdir>

``<workdir>`` holds ``input.svg`` and ``options.json``. The run writes
``<workdir>/result.json`` and, for ``convert``, the delivered files in
``<workdir>/out/``. A known failure is written as ``{"ok": false, "error":
{"code", "message"}}`` with exit code 0; anything else exits non-zero and the
provider reports it as ``sandbox_failed``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from .border import BORDER_INDEX, apply_border
from .geometry import Prepared, check, prepare
from .limits import MAX_STITCHES, RUN_LIMIT_SECONDS, Options, PipelineError, hoop_fit, hoop_fit_width
from .prepared_svg import write_prepared_svg
from .presets import fill_params
from .preview import render_dpi, to_transparent_png, to_webp
from .stitch_report import build_report, stitches_json
from .svg_source import SourceScan, findings_from_scan, scan_source

INKSTITCH = "/opt/inkstitch/bin/inkstitch"
MACHINE_FORMATS = ("dst", "pes", "exp", "jef", "vp3")
OUTPUT_NAMES = {
    "dst": "design.dst", "pes": "design.pes", "exp": "design.exp", "jef": "design.jef", "vp3": "design.vp3",
    "preview": "preview.webp", "preview_transparent": "preview-transparent.png",
    "prepared_svg": "prepared.svg", "stitches": "stitches.json",
}
# Stitch estimate used to fail early instead of running Ink/Stitch into the time
# limit. A fill costs stitches for its area (tatami rows incl. underlay,
# AREA_FACTOR / row_spacing per mm^2), for its outline (row ends, edge runs of
# the underlay and travel along the edge, OUTLINE_STITCHES_PER_MM over outer and
# hole outlines) and a little per separate part (locks). Counting the outline is
# what makes narrow bands, spotted and many-island designs come out right: a
# 3 mm sew-on border or a leopard pattern has several times the outline of a
# compact shape of the same area. Fitted on 17 real conversions (fixtures 01-06,
# fox, islands, flame and a spotted ornament; 7,000-47,000 stitches, 90-300 mm,
# with and without a 3 or 6 mm border): every estimate is within 3.1 % of the
# sewn count. The earlier area-only estimate was up to 52 % low on the spotted
# ornament.
# Speed: Ink/Stitch computes 170-1,400 stitches per second on 2 vCPU depending on
# the outline complexity, so besides the 150,000 limit a design whose estimate
# cannot finish in the time left at MIN_STITCHES_PER_SECOND fails as
# too_many_stitches at once instead of running into the time limit.
AREA_FACTOR = 0.36
OUTLINE_STITCHES_PER_MM = 3.09
STITCHES_PER_FILL_PART = 2.2
SATIN_STITCHES_PER_MM = 6.4
RUNNING_STITCHES_PER_MM = 0.97
STITCHES_PER_LINE = 8
MIN_STITCHES_PER_SECOND = 700
# Stretchy fabric sews a second crossed fill underlay: measured 12,653 stitches
# for 03_stars_background at 120 mm against 9,419 estimated without this factor.
FILL_UNDERLAY_EXTRA = {"light": 0.0, "normal": 0.0, "stretchy": 0.4}
# Ink/Stitch start, realistic render and report on top of the stitch planning.
FIXED_CONVERT_SECONDS = 10
TOO_SLOW_MESSAGE = ("The design has too many stitches to convert within the 10 minute limit. "
                    "Try a smaller width.")
# The pipeline stops itself a little before the provider's hard kill so it can
# still report a clean timeout.
DEADLINE_MARGIN_SECONDS = 5
INKSTITCH_RESERVE_SECONDS = 5


def _scan_notes(scan: SourceScan) -> list[dict[str, str]]:
    notes = []
    if scan.text_snippets:
        notes.append({"code": "text_left_out", "text": "Text left out because it is not drawn as shapes"})
    if scan.image_count:
        notes.append({"code": "image_left_out", "text": "Embedded pixel image left out"})
    if scan.uses_filter:
        notes.append({"code": "effects_ignored", "text": "Blur, shadow and mask effects left out"})
    return notes


def _estimate_stitches(prepared: Prepared, fabric: str) -> int:
    density = AREA_FACTOR / float(fill_params(fabric, 0.0)["row_spacing_mm"]) * (1 + FILL_UNDERLAY_EXTRA[fabric])
    total = 0.0
    for shape in prepared.shapes:
        if shape.kind == "fill":
            parts = len(getattr(shape.geom, "geoms", [shape.geom]))
            total += (shape.geom.area * density + shape.geom.length * OUTLINE_STITCHES_PER_MM
                      + parts * STITCHES_PER_FILL_PART)
        elif shape.kind == "satin":
            total += shape.geom.length * SATIN_STITCHES_PER_MM + STITCHES_PER_LINE
        else:
            total += shape.geom.length * RUNNING_STITCHES_PER_MM + STITCHES_PER_LINE
    return int(total)


def _estimate_terms(prepared: Prepared) -> list[list[object]]:
    """Per shape: colour, kind, border flag, area mm2, outline length mm, separate parts."""
    return [[shape.colour, shape.kind, shape.index == BORDER_INDEX, round(shape.geom.area, 1),
             round(shape.geom.length, 1), len(getattr(shape.geom, "geoms", [shape.geom]))]
            for shape in prepared.shapes]


def _run_inkstitch(svg_path: Path, dpi: int, deadline: float) -> tuple[dict[str, bytes], float]:
    args = [INKSTITCH, "--extension=zip", *(f"--format-{fmt}=True" for fmt in MACHINE_FORMATS),
            "--format-threadlist=True", "--format-png-realistic=True", f"--dpi-realistic={dpi}", str(svg_path)]
    timeout = deadline - time.monotonic()
    if timeout <= INKSTITCH_RESERVE_SECONDS:
        raise PipelineError("timeout")
    started = time.monotonic()
    try:
        completed = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise PipelineError("timeout") from exc
    elapsed = time.monotonic() - started
    stderr = completed.stderr.decode("utf-8", "replace")
    if completed.returncode != 0 or not completed.stdout.startswith(b"PK"):
        if "no selected stitchable element" in stderr:
            raise PipelineError("nothing_to_sew")
        raise PipelineError("sandbox_failed", "Ink/Stitch could not convert the prepared graphic: "
                            + (stderr.strip().splitlines() or ["no output"])[-1][:300])
    archive_path = svg_path.with_suffix(".zip")
    archive_path.write_bytes(completed.stdout)
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            if name.endswith("_threadlist.txt"):
                files["threadlist"] = archive.read(name)
            elif name.endswith("_realistic.png"):
                files["png"] = archive.read(name)
            else:
                suffix = name.rsplit(".", 1)[-1].lower()
                if suffix in MACHINE_FORMATS:
                    files[suffix] = archive.read(name)
    missing = [key for key in (*MACHINE_FORMATS, "threadlist", "png") if not files.get(key)]
    if missing:
        raise PipelineError("sandbox_failed", "Ink/Stitch did not produce: " + ", ".join(missing))
    return files, elapsed


def run_check(workdir: Path, options: Options) -> dict[str, object]:
    svg_text = (workdir / "input.svg").read_text(encoding="utf-8")
    scan = scan_source(svg_text)
    geometry_findings, colours, shapes = check(svg_text, scan, options.width_mm)
    return {"ok": True, "findings": findings_from_scan(scan) + geometry_findings,
            "colour_count": colours, "shape_count": shapes}


def run_convert(workdir: Path, options: Options, started: float) -> dict[str, object]:
    deadline = started + RUN_LIMIT_SECONDS - DEADLINE_MARGIN_SECONDS
    timings: dict[str, float] = {}
    mark = time.monotonic()
    svg_text = (workdir / "input.svg").read_text(encoding="utf-8")
    scan = scan_source(svg_text)
    findings = findings_from_scan(scan)
    timings["check"] = round(time.monotonic() - mark, 3)

    mark = time.monotonic()
    bordered = options.border_mm is not None
    start_colour = options.border_colour if bordered else None
    prepared = prepare(svg_text, scan, options.width_mm, start_colour)
    if options.fit_hoop:
        fitted = hoop_fit_width(prepared.width_mm, prepared.height_mm,
                                2 * float(options.border_mm) if bordered else 0.0, options.hoop)
        prepared = prepare(svg_text, scan, fitted, start_colour)
        prepared.notes.append({"code": "sized_to_hoop", "text": "Sized to fill the hoop"})
    if bordered:
        prepared = apply_border(prepared, float(options.border_mm), options.border_colour)
    findings += prepared.findings
    estimate = _estimate_stitches(prepared, options.fabric)
    if estimate > MAX_STITCHES:
        raise PipelineError("too_many_stitches")
    seconds_left = deadline - time.monotonic() - FIXED_CONVERT_SECONDS
    if estimate / MIN_STITCHES_PER_SECOND > seconds_left:
        raise PipelineError("too_many_stitches", TOO_SLOW_MESSAGE)
    prepared_text = write_prepared_svg(prepared, options.fabric)
    out = workdir / "out"
    out.mkdir(exist_ok=True)
    svg_path = out / OUTPUT_NAMES["prepared_svg"]
    svg_path.write_text(prepared_text, encoding="utf-8")
    timings["prepare"] = round(time.monotonic() - mark, 3)

    dpi = render_dpi(prepared.width_mm + 2, prepared.height_mm + 2)
    files, timings["inkstitch"] = _run_inkstitch(svg_path, dpi, deadline)
    timings["inkstitch"] = round(timings["inkstitch"], 3)

    mark = time.monotonic()
    try:
        summary, stitches = build_report(files["dst"], files["threadlist"].decode("utf-8", "replace"))
    except ValueError as exc:
        raise PipelineError("sandbox_failed", f"The stitch file could not be read back ({exc}).") from exc
    if int(summary["stitch_count"]) > MAX_STITCHES:
        raise PipelineError("too_many_stitches")
    jumps = summary.pop("jumps")
    fits, rotate = hoop_fit(float(summary["width_mm"]), float(summary["height_mm"]), options.hoop)
    notes = prepared.notes + _scan_notes(scan)
    if rotate:
        notes.append({"code": "rotate_for_hoop", "text": "Turn the design by 90 degrees to fit the hoop"})
    summary = {
        "width_mm": summary["width_mm"], "height_mm": summary["height_mm"],
        "stitch_count": summary["stitch_count"], "thread_changes": summary["thread_changes"],
        "estimated_minutes": summary["estimated_minutes"], "fits_hoop": fits,
        "threads": summary["threads"], "notes": notes,
        **({"border_mm": options.border_mm} if bordered else {}),
    }
    for fmt in MACHINE_FORMATS:
        (out / OUTPUT_NAMES[fmt]).write_bytes(files[fmt])
    (out / OUTPUT_NAMES["stitches"]).write_bytes(stitches_json(stitches))
    timings["report"] = round(time.monotonic() - mark, 3)

    mark = time.monotonic()
    (out / OUTPUT_NAMES["preview"]).write_bytes(to_webp(files["png"], stitches, dpi))
    (out / OUTPUT_NAMES["preview_transparent"]).write_bytes(to_transparent_png(files["png"], stitches, dpi))
    timings["preview"] = round(time.monotonic() - mark, 3)
    timings["total"] = round(time.monotonic() - started, 3)
    return {"ok": True, "summary": summary, "findings": findings,
            "files": {key: f"out/{name}" for key, name in OUTPUT_NAMES.items()},
            "metrics": {"jumps": jumps, "timings": timings, "render_dpi": dpi,
                        "shapes_sewn": len(prepared.shapes), **prepared.technical, "estimated_stitches": estimate,
                        "estimate_terms": _estimate_terms(prepared),
                        "trims": sum(1 for shape in prepared.shapes if shape.trim_after)}}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("check", "convert"):
        print(__doc__, file=sys.stderr)
        return 2
    started = time.monotonic()
    mode, workdir = argv[0], Path(argv[1])
    raw_options = json.loads((workdir / "options.json").read_text(encoding="utf-8"))
    try:
        options = Options.from_dict(raw_options)
    except ValueError as error:
        options = None
        result = {"ok": False, "error": {"code": "sandbox_failed", "message": f"Invalid options: {error}"}}
    if options is not None:
        try:
            result = run_check(workdir, options) if mode == "check" else run_convert(workdir, options, started)
        except PipelineError as error:
            result = {"ok": False, "error": {"code": error.code, "message": error.user_message}}
    (workdir / "result.json").write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

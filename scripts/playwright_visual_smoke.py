#!/usr/bin/env python3
"""
Worktree-safe Playwright visual smoke helper.

This script intentionally uses the globally installed Python Playwright package
and browser cache instead of per-worktree node_modules. It is for browser
inspection and screenshot evidence only, not local Playwright spec execution.
Browsers and contexts are closed on normal exit and SIGINT/SIGTERM so failed
agent runs do not leave long-lived browser processes or profile directories.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VIEWPORTS = {
    "laptop": {"width": 1440, "height": 1000},
    "mobile": {"width": 390, "height": 844},
}
DEFAULT_KEEP_RUNS = 20
DEFAULT_WAIT_MS = 1000
MAX_URLS = 10
MAX_REPORTED_PROBLEMS = 5
MAX_REPORTED_CONSOLE_ERRORS = 3
MAX_REPORTED_NETWORK_ERRORS = 5
ERROR_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"application error",
        r"internal server error",
        r"implementation error",
        r"cannot read properties of",
        r"traceback \(most recent call last\)",
    )
]
MEDIA_PRELOAD_URL_RE = re.compile(r"\.(?:mp3|m4a|wav|ogg|webm|mp4)(?:[?#]|$)", re.IGNORECASE)

_active_browser: Any = None
_active_playwright: Any = None
_shutting_down = False


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture deployed route screenshots with global Python Playwright")
    parser.add_argument("--url", action="append", required=True, help="URL to inspect; repeat for multiple URLs")
    parser.add_argument("--session", default="", help="sessions.py ID for visual-smoke evidence recording")
    parser.add_argument("--out", default="", help="Output directory; defaults to test-results/visual-smoke/<timestamp>")
    parser.add_argument("--wait-ms", type=int, default=DEFAULT_WAIT_MS, help="Extra milliseconds to wait after navigation")
    parser.add_argument("--keep-runs", type=int, default=DEFAULT_KEEP_RUNS, help="Default-output retention count")
    parser.add_argument("--assert-visible", action="append", default=[], help="CSS selector that must be visible and in viewport")
    parser.add_argument("--reviewed-summary", default="", help="Reviewed pass summary with Defects and Accepted differences")
    args = parser.parse_args(argv)
    if len(args.url) > MAX_URLS:
        parser.error(f"refusing to smoke {len(args.url)} URLs in one run; maximum is {MAX_URLS}")
    if args.wait_ms < 0:
        parser.error("--wait-ms must be non-negative")
    if args.keep_runs < 1:
        parser.error("--keep-runs must be positive")
    return args


def close_browser() -> None:
    global _active_browser, _active_playwright
    browser = _active_browser
    playwright = _active_playwright
    _active_browser = None
    _active_playwright = None
    if browser is not None:
        try:
            if browser.is_connected():
                browser.close()
        except Exception:
            pass
    if playwright is not None:
        try:
            playwright.stop()
        except Exception:
            pass


def install_shutdown_handlers() -> None:
    def shutdown(signum: int, _frame: Any) -> None:
        global _shutting_down
        if _shutting_down:
            raise SystemExit(130 if signum == signal.SIGINT else 143)
        _shutting_down = True
        close_browser()
        raise SystemExit(130 if signum == signal.SIGINT else 143)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def chromium_candidates() -> list[Path]:
    configured = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    cache_root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or Path.home() / ".cache" / "ms-playwright").expanduser()
    for path in sorted(cache_root.glob("chromium-*/chrome-linux/chrome"), key=lambda item: item.stat().st_mtime, reverse=True):
        if (path.parents[1] / "INSTALLATION_COMPLETE").is_file():
            candidates.append(path)
    return [path for path in candidates if path.is_file() and os.access(path, os.X_OK)]


def launch_browser() -> tuple[Any, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError("Python Playwright is not installed; install it globally before using worktree browser helpers") from error

    playwright = sync_playwright().start()
    try:
        candidates = chromium_candidates()
        launch_options: dict[str, Any] = {"headless": True}
        if candidates:
            launch_options["executable_path"] = str(candidates[0])
        browser = playwright.chromium.launch(**launch_options)
        return playwright, browser
    except Exception as error:
        playwright.stop()
        raise RuntimeError(
            "Could not launch Chromium from the global Playwright cache. "
            "If scripts/playwright_visual_smoke.py reports no executable candidates, ask before running "
            "python3 -m playwright install chromium because it downloads large browser artifacts."
        ) from error


def slugify(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9]+", "-", re.sub(r"^https?://", "", value)).strip("-")
    return (result or "route")[:80]


def artifact_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def is_ignorable_request_failure(failure: str, url: str) -> bool:
    # Browsers may abort hidden media metadata/range preloads without breaking playback.
    return "net::ERR_ABORTED" in failure and MEDIA_PRELOAD_URL_RE.search(url) is not None


def cleanup_old_runs(visual_smoke_root: Path, keep_runs: int) -> list[str]:
    if not visual_smoke_root.is_dir():
        return []
    runs: list[tuple[float, Path]] = []
    for entry in visual_smoke_root.iterdir():
        summary = entry / "summary.json"
        if entry.is_dir() and summary.is_file():
            runs.append((summary.stat().st_mtime, entry))
    runs.sort(reverse=True)
    removed: list[str] = []
    for _mtime, run_dir in runs[keep_runs:]:
        for child in sorted(run_dir.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                child.rmdir()
        run_dir.rmdir()
        removed.append(str(run_dir))
    return removed


def collect_layout_signals(page: Any, selectors: list[str]) -> dict[str, Any]:
    return page.evaluate(
        """
        (selectors) => {
          function isVisible(element) {
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none'
              && style.visibility !== 'hidden'
              && Number.parseFloat(style.opacity || '1') > 0.01
              && rect.width > 1
              && rect.height > 1;
          }
          function label(element) {
            const tag = element.tagName.toLowerCase();
            const id = element.id ? `#${element.id}` : '';
            const testId = element.getAttribute('data-testid') ? `[data-testid="${element.getAttribute('data-testid')}"]` : '';
            return `${tag}${id}${testId}`;
          }
          const doc = document.documentElement;
          const body = document.body;
          const horizontalOverflowPx = Math.max(0, Math.max(doc.scrollWidth, body?.scrollWidth || 0) - window.innerWidth);
          const brokenImages = Array.from(document.images)
            .filter((image) => isVisible(image) && image.complete && image.naturalWidth === 0)
            .slice(0, 5)
            .map((image) => ({ label: label(image), src: image.currentSrc || image.src || '' }));
          const assertions = selectors.map((selector) => {
            const element = document.querySelector(selector);
            if (!element) return { selector, ok: false, problem: 'missing' };
            const rect = element.getBoundingClientRect();
            if (!isVisible(element)) return { selector, ok: false, problem: 'not visible', rect };
            const outsideViewport = rect.left < -1 || rect.top < -1 || rect.right > window.innerWidth + 1 || rect.bottom > window.innerHeight + 1;
            if (outsideViewport) return { selector, ok: false, problem: 'outside viewport', rect };
            return { selector, ok: true, rect };
          });
          return { horizontalOverflowPx, brokenImages, assertions };
        }
        """,
        selectors,
    )


def smoke_url(browser: Any, url: str, viewport_name: str, viewport: dict[str, int], out_dir: Path, wait_ms: int, selectors: list[str]) -> dict[str, Any]:
    context = browser.new_context(viewport=viewport)
    context.route("**/v1/analytics/beacon", lambda route: route.fulfill(status=204, body=""))
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    response_errors: list[str] = []
    request_failures: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("response", lambda response: response_errors.append(f"{response.status} {response.url}") if response.status >= 400 else None)
    def record_request_failure(request: Any) -> None:
        failure = request.failure
        if callable(failure):
            failure = failure()
        failure_text = str(failure or "request failed")
        request_url = str(request.url)
        if is_ignorable_request_failure(failure_text, request_url):
            return
        request_failures.append(f"{failure_text} {request_url}")

    page.on("requestfailed", record_request_failure)

    status = 0
    title = ""
    body_text = ""
    screenshot = out_dir / f"{slugify(url)}-{viewport_name}.png"
    problems: list[str] = []
    try:
        try:
            response = page.goto(url, wait_until="networkidle", timeout=45_000)
            status = response.status if response else 0
        except Exception as error:
            problems.append(f"navigation error: {error}")
        if wait_ms:
            page.wait_for_timeout(wait_ms)
        title = page.title()
        try:
            body_text = page.locator("body").inner_text(timeout=5000)
        except Exception:
            body_text = ""
        page.screenshot(path=str(screenshot), full_page=False)
        layout = collect_layout_signals(page, selectors)
        matched_patterns = [pattern.pattern for pattern in ERROR_PATTERNS if pattern.search(body_text)]
        if status >= 400:
            problems.append(f"HTTP {status}")
        if not body_text.strip():
            problems.append("empty body text")
        if matched_patterns:
            problems.append(f"matched error text: {', '.join(matched_patterns)}")
        if page_errors:
            problems.append(f"page errors: {' | '.join(page_errors[:MAX_REPORTED_CONSOLE_ERRORS])}")
        if console_errors:
            problems.append(f"console errors: {' | '.join(console_errors[:MAX_REPORTED_CONSOLE_ERRORS])}")
        if response_errors:
            problems.append(f"HTTP subresource errors: {' | '.join(response_errors[:MAX_REPORTED_NETWORK_ERRORS])}")
        if request_failures:
            problems.append(f"request failures: {' | '.join(request_failures[:MAX_REPORTED_NETWORK_ERRORS])}")
        if layout.get("horizontalOverflowPx", 0) > 2:
            problems.append(f"horizontal overflow: {layout['horizontalOverflowPx']}px")
        if layout.get("brokenImages"):
            labels = ", ".join(image.get("label", "unknown") for image in layout["brokenImages"])
            problems.append(f"broken visible images: {labels}")
        failed_assertions = [assertion for assertion in layout.get("assertions", []) if not assertion.get("ok")]
        if failed_assertions:
            details = ", ".join(f"{item.get('selector')} ({item.get('problem')})" for item in failed_assertions)
            problems.append(f"visible selector assertions failed: {details}")
        return {
            "url": url,
            "viewport": viewport_name,
            "status": status,
            "title": title,
            "screenshot": str(screenshot),
            "layout": layout,
            "consoleErrors": console_errors[:5],
            "pageErrors": page_errors[:5],
            "responseErrors": response_errors[:10],
            "requestFailures": request_failures[:10],
            "problems": problems,
        }
    finally:
        page.close(run_before_unload=False)
        context.close()


def build_evidence_summary(failures: list[dict[str, Any]], needs_review: bool, reviewed_summary: str) -> str:
    if failures:
        problems = [problem for record in failures for problem in record.get("problems", [])][:MAX_REPORTED_PROBLEMS]
        return f"Playwright visual smoke failed before screenshot review: {' | '.join(problems)}"
    if needs_review:
        return "Playwright screenshots captured in laptop and mobile viewports. Manual screenshot review is required before recording a pass. Defects: pending. Accepted differences: pending."
    return reviewed_summary.strip()


def main(argv: list[str]) -> int:
    install_shutdown_handlers()
    args = parse_args(argv)
    root = repo_root()
    timestamp = datetime.now(timezone.utc).isoformat().replace(":", "-").replace(".", "-")
    visual_smoke_root = root / "test-results" / "visual-smoke"
    using_default_out = not args.out
    out_dir = visual_smoke_root / timestamp if using_default_out else Path(args.out).expanduser()
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    global _active_browser, _active_playwright
    _active_playwright, _active_browser = launch_browser()
    records: list[dict[str, Any]] = []
    try:
        for url in args.url:
            for viewport_name, viewport in VIEWPORTS.items():
                records.append(smoke_url(_active_browser, url, viewport_name, viewport, out_dir, args.wait_ms, args.assert_visible))
    finally:
        close_browser()

    summary_path = out_dir / "summary.json"
    failures = [record for record in records if record.get("problems")]
    summary = {
        "method": "playwright",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "urls": args.url,
        "viewports": list(VIEWPORTS.keys()),
        "assertVisible": args.assert_visible,
        "retention": {"keepRuns": args.keep_runs, "removedRuns": []} if using_default_out else {"customOut": True},
        "records": records,
        "result": "failed" if failures else "passed",
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if using_default_out:
        summary["retention"]["removedRuns"] = cleanup_old_runs(visual_smoke_root, args.keep_runs)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    needs_review = not failures and bool(args.session) and not args.reviewed_summary.strip()
    if args.session:
        result = "failed" if failures else "blocked" if needs_review else "passed"
        command = [
            sys.executable,
            "scripts/sessions.py",
            "visual-smoke",
            "--session",
            args.session,
            "--result",
            result,
            "--method",
            "playwright",
            "--run-id",
            artifact_path(root, summary_path),
            "--summary",
            build_evidence_summary(failures, needs_review, args.reviewed_summary),
        ]
        for url in args.url:
            command.extend(["--url", url])
        for viewport_name in VIEWPORTS:
            command.extend(["--viewport", viewport_name])
        for record in records:
            command.extend(["--screenshot", artifact_path(root, Path(record["screenshot"]))])
        recorded = subprocess.run(command, cwd=root, text=True)
        if recorded.returncode != 0:
            return recorded.returncode

    print(f"Visual smoke {summary['result']}: {artifact_path(root, summary_path)}")
    for record in records:
        print(f"- {record['viewport']} {record['status']} {record['url']} screenshot={artifact_path(root, Path(record['screenshot']))}")
        for problem in record.get("problems", []):
            print(f"  problem: {problem}")
    if failures:
        return 1
    if needs_review:
        print("Visual smoke screenshots captured; review the laptop and mobile PNGs, then record a passed visual-smoke summary with defects and accepted differences.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

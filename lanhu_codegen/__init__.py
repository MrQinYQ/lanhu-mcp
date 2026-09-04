"""Python boundary for the pinned Lanhu DDS HTML generator.

The official multi-file output is kept separate from the self-contained MCP
preview. Never use the preview as the expected result of a parity test.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess


class CodeGenerationError(RuntimeError):
    """The official generator could not produce a complete HTML export."""


def generate_design_files(schema: dict, *, rem: float = 37.5) -> dict[str, str]:
    """Return all five official HTML/CSS files without minification/localization."""
    if not isinstance(schema, dict) or not schema:
        raise CodeGenerationError("DDS schema must be a non-empty object")
    if "artboard" in schema or "board" in schema:
        raise CodeGenerationError("Raw Figma/Sketch JSON is not a DDS schema; convert it before HTML generation")
    executable = os.environ.get("LANHU_NODE_BINARY") or shutil.which("node")
    if not executable:
        raise CodeGenerationError("Node.js is required for the official DDS generator; install Node.js or set LANHU_NODE_BINARY")
    runner = Path(__file__).with_name("runner.cjs")
    try:
        result = subprocess.run(
            [executable, str(runner)],
            input=json.dumps({"schema": schema, "options": {"rem": rem, "format": True}}, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CodeGenerationError(f"Official DDS generator failed: {type(exc).__name__}") from exc
    if result.returncode:
        raise CodeGenerationError(f"Official DDS generator exited with {result.returncode}: {result.stderr.strip()[:1000]}")
    try:
        files = json.loads(result.stdout)["files"]
        required = {"index.html", "index.css", "index.rem.css", "index.response.css", "common.css"}
        if not isinstance(files, dict) or set(files) != required or not all(isinstance(v, str) for v in files.values()):
            raise ValueError("incomplete file set")
    except (ValueError, KeyError, TypeError) as exc:
        raise CodeGenerationError("Official DDS generator returned an invalid file set") from exc
    return files


def inline_design_files(files: dict[str, str]) -> str:
    """Embed the official styles for the MCP preview, preserving cascade order."""
    html = files["index.html"]
    for name in ("common.css", "index.css"):
        link = f'<link rel="stylesheet" type="text/css" href="./{name}" />'
        if html.count(link) != 1:
            raise CodeGenerationError(f"Unexpected official stylesheet reference: {name}")
        html = html.replace(link, "<style>\n" + files[name].replace("</style", "<\\/style") + "</style>", 1)
    return html


def convert_lanhu_to_html(schema: dict, *, inline_styles: bool = False) -> str:
    """Return official index.html; optionally embed its companion CSS for MCP."""
    files = generate_design_files(schema)
    return inline_design_files(files) if inline_styles else files["index.html"]

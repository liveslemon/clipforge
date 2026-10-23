"""Runs one module's pytest suite and explains each test (docstring, assertions, source, result)."""
from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict

from .engine import MODULES, ROOT


def describe_tests(test_file: Path) -> Dict[str, Dict[str, Any]]:
    src = test_file.read_text()
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            asserts = [ast.get_source_segment(src, n) for n in ast.walk(node) if isinstance(n, ast.Assert)]
            raises = [ast.get_source_segment(src, n.items[0].context_expr) for n in ast.walk(node)
                      if isinstance(n, (ast.With, ast.AsyncWith)) and "raises" in (ast.get_source_segment(src, n.items[0].context_expr) or "")]
            out[node.name] = {
                "doc": ast.get_docstring(node) or "",
                "asserts": sorted((a for a in asserts if a), key=lambda a: src.find(a))[:25],
                "raises": raises,
                "source": ast.get_source_segment(src, node),
                "line": node.lineno,
            }
    return out


def run_module_tests(n: int) -> Dict[str, Any]:
    tests_dir = ROOT / "modules" / MODULES[n]["folder"] / "tests"
    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "junit.xml"
        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(tests_dir), "-q", "-p", "no:cacheprovider", f"--junitxml={xml_path}"],
            cwd=ROOT, capture_output=True, text=True, timeout=900,
        )
        elapsed = round(time.time() - t0, 2)
        cases = []
        if xml_path.exists():
            for tc in ET.parse(xml_path).getroot().iter("testcase"):
                status, message = "passed", ""
                for tag in ("failure", "error", "skipped"):
                    el = tc.find(tag)
                    if el is not None:
                        status = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                        message = (el.get("message") or "") + "\n" + (el.text or "")
                cases.append({"name": tc.get("name"), "file": (tc.get("file") or tc.get("classname", "")),
                              "time": float(tc.get("time", 0)), "status": status, "message": message.strip()[-4000:]})

    described = {}
    for f in tests_dir.glob("test_*.py"):
        described.update(describe_tests(f))
    for c in cases:
        c.update(described.get(c["name"].split("[")[0], {}))
    return {
        "module": n, "title": MODULES[n]["title"], "elapsed_s": elapsed, "returncode": proc.returncode,
        "passed": sum(c["status"] == "passed" for c in cases), "total": len(cases), "tests": cases,
        "output": (proc.stdout + proc.stderr)[-6000:],
    }

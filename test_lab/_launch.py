"""Shared launcher: `python test_lab/lab_XX_*.py [video]` opens that module's visual test page."""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SYMBOL = {"pass": "\033[32m✔\033[0m", "warn": "\033[33m!\033[0m", "fail": "\033[31m✘\033[0m", "info": "\033[36mi\033[0m"}


def _port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def launch(module: int | None = None) -> None:
    from test_lab.engine import MODULES

    what = f"Module {module}: {MODULES[module]['title']}" if module else "all 10 modules"
    ap = argparse.ArgumentParser(description=f"ClipForge Test Lab — {what}")
    ap.add_argument("video", nargs="?", help="video on your laptop (optional: you can also upload in the browser)")
    ap.add_argument("--chat", help="optional chat log for Module 5 ('[00:01:23] user: msg' lines, or JSON)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--cli", action="store_true", help="no browser: analyse in the terminal and write an HTML report")
    ap.add_argument("--with-unit-tests", action="store_true", help="CLI mode: also run the pytest suites")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    modules = [module] if module else list(MODULES)

    if args.cli:
        if not args.video:
            ap.error("--cli needs a video path")
        sys.exit(run_cli(args.video, modules, args.chat, args.with_unit_tests))

    url = f"http://127.0.0.1:{args.port}/" + (f"#/module/{module}" if module else "")
    if _port_in_use(args.port):
        print(f"Test Lab already running on port {args.port} — opening {url}")
        if args.video:
            req = urllib.request.Request(f"http://127.0.0.1:{args.port}/api/use-path", method="POST",
                                         data=json.dumps({"path": str(Path(args.video).resolve())}).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req).read()
        webbrowser.open(url)
        return

    import uvicorn
    from test_lab.server import STATE, app
    from test_lab.engine import LabSession

    if args.video:
        STATE["session"] = LabSession(args.video, chat_path=args.chat)
    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    print(f"\n  ClipForge Test Lab → {url}\n  (Ctrl+C to stop)\n")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def run_cli(video: str, modules: list[int], chat: str | None, with_tests: bool) -> int:
    from test_lab.engine import MODULES, LabSession
    from test_lab.pytest_runner import run_module_tests

    session = LabSession(video, chat_path=chat)
    print(f"\nAnalysing {session.video.name}  →  {session.dir}\n")
    failed = 0
    tests = {}
    for n in modules:
        print(f"\033[1m[{n:02d}] {MODULES[n]['title']}\033[0m")
        r = session.run(n)
        for c in r["checks"]:
            detail = c["detail"].splitlines()[0][:110] if c["detail"] else ""
            print(f"   {SYMBOL[c['status']]} {c['name']:<40} {detail}")
        print(f"   ({r['elapsed_s']}s)\n")
        failed += r["counts"]["fail"]
        if with_tests:
            t = run_module_tests(n)
            tests[n] = t
            print(f"   unit tests: {t['passed']}/{t['total']} passed\n")
            failed += t["total"] - t["passed"]

    page = (Path(__file__).with_name("page.html")).read_text()
    payload = {"modules": MODULES, "session": session.info(), "results": session.results, "tests": tests}
    blob = json.dumps(payload, default=str).replace("</", "<\\/")
    report = session.dir / "report.html"
    report.write_text(page.replace("/*__STATIC__*/", f"window.LAB_STATIC = {blob};"))
    print(f"Report: {report}")
    return 1 if failed else 0

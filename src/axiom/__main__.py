"""``python -m axiom`` / the ``axiom`` entry point.

The only place in the project where a frontend is selected:

    axiom                → frontends.tui      (Textual workspace)
    axiom --gui          → frontends.gui      (Tauri desktop app, desktop/)
"""

from __future__ import annotations

import json
import sys

from axiom import __version__

_HELP = f"""AXIOM {__version__} — Open Local AI Coding Workspace & Agent Harness

Usage:
  axiom                     Start the TUI workspace
  axiom --gui               Start the desktop GUI (Tauri app in desktop/)
  axiom run "prompt" --json Run one prompt headlessly, print JSON
  axiom serve [--token T]   Start the localhost API with token auth
  axiom --help              Show this help
  axiom benchmark --scenarios FILE --repetitions N --output FILE
"""


def main(argv: list[str] | None = None) -> int:
    """Dispatch to the selected frontend."""
    args = list(sys.argv[1:] if argv is None else argv)

    if any(arg in ("--help", "-h") for arg in args):
        print(_HELP)
        return 0
    if "--version" in args:
        print(f"AXIOM {__version__}")
        return 0

    if args and args[0] in ("run", "serve"):
        from axiom.frontends.headless import main_run, main_serve

        return main_run(args[1:]) if args[0] == "run" else main_serve(args[1:])

    if "--benchmark" in args:
        import asyncio

        from axiom.core.benchmark import BenchmarkRunner, scenarios_from_json
        from axiom.core.chat import ChatSession
        from axiom.core.config import Config

        def _arg(name: str, default: str | None = None) -> str | None:
            try:
                return args[args.index(name) + 1]
            except (ValueError, IndexError):
                return default

        scenario_file = _arg("--scenarios")
        if not scenario_file:
            print("benchmark requires --scenarios FILE", file=sys.stderr)
            return 2
        repetitions = int(_arg("--repetitions", "3") or "3")
        output = _arg("--output", "benchmark.json")
        async def _run() -> None:
            config = Config.load()
            report = await BenchmarkRunner(
                lambda: _session_factory(config), scenarios_from_json(scenario_file),
                repetitions=repetitions, output=output,
            ).run()
            print(json.dumps(report, ensure_ascii=False, indent=2))
        async def _session_factory(config):
            return ChatSession(config=config)
        return asyncio.run(_run())

    if "--gui" in args:
        from axiom.frontends.gui.main import main as gui_main

        return gui_main()

    unknown = [a for a in args if a.startswith("-")]
    if unknown:
        print(f"Unknown option(s): {' '.join(unknown)}\n\n{_HELP}", file=sys.stderr)
        return 2

    from axiom.frontends.tui.app import main as tui_main

    return tui_main()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Open Pythona VSCode, or preview the workbench in a desktop browser."""

import argparse
from pathlib import Path
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="preview outside Pythona")
    parser.add_argument("--port", type=int, default=8879, help="loopback port for browser preview")
    parser.add_argument("--documents", type=Path,
                        help="explicit Documents substitute for browser development and tests")
    parser.add_argument("--state", type=Path, help="preview state file")
    args = parser.parse_args()
    if not args.preview:
        if args.documents or args.state:
            parser.error("--documents and --state are only available with --preview.")
        import builtins
        if not hasattr(builtins, "run_on_ui"):
            parser.error("Run inside Pythona, or add --preview to open a browser preview.")
        from vscode_app.ui import main as present
        return present()

    from vscode_app.server import LocalServer
    from vscode_app.workspace import WorkspaceApp

    with tempfile.TemporaryDirectory(prefix="pythona_vscode_preview_") as temporary:
        documents = args.documents or Path(temporary) / "Documents"
        if args.documents is None:
            project = documents / "Hello Python"
            project.mkdir(parents=True)
            (project / "main.py").write_text(
                '"""A small workspace for trying the editor."""\n\n'
                'def main():\n    print("Hello from Pythona VSCode 🐍")\n\n'
                'if __name__ == "__main__":\n    main()\n', encoding="utf-8")
            (project / "README.md").write_text(
                "# Hello Python\n\nOpen this folder to try editing and saving files.\n",
                encoding="utf-8")
            (documents / "Notes").mkdir()
        app = WorkspaceApp(documents, args.state or Path(temporary) / "state.json")
        server = None
        try:
            server = LocalServer(app, port=args.port)
            print(f"Open {server.url}", flush=True)
            if args.documents is None:
                print("This preview edits a temporary sample workspace. Changes are discarded on exit.", flush=True)
            else:
                print(f"Preview edits files under: {documents.resolve()}", flush=True)
            while not app.closed.wait(0.1):
                pass
        except KeyboardInterrupt:
            pass
        finally:
            if server:
                server.close()
            app.close()


if __name__ == "__main__":
    main()

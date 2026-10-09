"""Verify threaded Python execution in Pythona and its actual WKWebView.

All scripts and workspace state live in temporary directories. Run this file
inside Pythona; the report is written to .local/native-execution.json.
"""

import builtins
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback
import unittest


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tests"))
    report = {"passed": False, "python": sys.version, "cases": []}
    report_path = root / ".local" / "native-execution.json"
    report_path.parent.mkdir(exist_ok=True)
    app = server = host = None
    try:
        import test_execution
        from vscode_app.server import LocalServer
        from vscode_app.ui import WorkbenchWindow
        from vscode_app.workspace import WorkspaceApp

        log = io.StringIO()
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromModule(test_execution))
        report["backend"] = {"passed": result.wasSuccessful(), "tests": result.testsRun, "log": log.getvalue()}
        if not result.wasSuccessful():
            raise RuntimeError("Embedded-interpreter execution tests failed.")

        with tempfile.TemporaryDirectory(prefix="pythona_vscode_execution_") as temporary:
            temporary = Path(temporary)
            documents = temporary / "Documents"
            project = documents / "Run Workspace"
            project.mkdir(parents=True)
            (project / "main.py").write_text('print("native start")\nprint("Hello", input("Name: "))\n', encoding="utf-8")
            (project / "loop.py").write_text('print("native loop")\nwhile True: pass\n')
            (project / "after.py").write_text(
                'import asyncio, math, sqlite3\n'
                'async def answer():\n    await asyncio.sleep(0)\n    return math.factorial(6)\n'
                'db = sqlite3.connect(":memory:")\n'
                'print("native modules", asyncio.run(answer()), db.execute("select 42").fetchone()[0])\n'
                'db.close()\n')
            app = WorkspaceApp(documents, temporary / "state.json")
            workspace = app.open_workspace(project.name)
            completed = threading.Event()
            original = app.dispatch

            def dispatch(action, payload=None):
                if action == "smoke.report":
                    report["frontend"] = payload
                    completed.set()
                    return None
                return original(action, payload)

            app.dispatch = dispatch
            server = LocalServer(app)
            host = WorkbenchWindow(app, server)
            builtins.run_on_ui(host.open).wait()
            deadline = time.monotonic() + 30
            while not host.loaded and time.monotonic() < deadline:
                time.sleep(0.05)
            if not host.loaded:
                raise RuntimeError(f"WebView did not load: {host.navigation_error}")
            script = r"""
            (async () => {
              const request = async (action, payload = {}) => {
                const response = await fetch(new URL('api', location.href), {
                  method: 'POST', headers: {'Content-Type':'application/json',
                    'X-Pythona-Session':location.pathname.split('/')[1]},
                  body: JSON.stringify({action, payload})
                });
                const reply = await response.json();
                if (reply.error) throw new Error(reply.error.message);
                return reply.result;
              };
              const wait = async condition => {
                for (let i = 0; i < 300; i++) {
                  const value = await condition();
                  if (value) return value;
                  await new Promise(resolve => setTimeout(resolve, 100));
                }
                throw new Error('Timed out: ' + document.body.innerText.slice(-3000));
              };
              const status = () => request('run.status', {workspace: WORKSPACE});
              const until = state => wait(async () => {
                const result = await status();
                return result?.state === state ? result : false;
              });
              const cases = [];
              try {
                await wait(() => window.pythonaWorkbench?.ready);
                const command = window.pythonaWorkbench.executeCommand;
                const open = name => command('_workbench.open', {scheme:'file',path:'/Documents/Run Workspace/' + name});
                await open('main.py');
                await command('pythona.runPython');
                await until('input');
                const input = await wait(() => document.querySelector('.python-console-input input:not([readonly])'));
                if (document.activeElement === input) throw new Error('Python input stole keyboard focus.');
                input.value = '你好 🐍';
                input.dispatchEvent(new Event('input', {bubbles:true}));
                input.form.requestSubmit();
                const first = await until('finished');
                if (first.exitCode !== 0 || !first.output.includes('Hello 你好 🐍')) throw new Error(JSON.stringify(first));
                cases.push('threaded Unicode input and output');
                await wait(() => document.body.innerText.replace(/\u00a0/g, ' ').includes('exit code 0'));
                await open('loop.py');
                await command('pythona.runPython');
                await wait(async () => (await status())?.output.includes('native loop'));
                await command('pythona.stopPython');
                const stopped = await until('finished');
                if (stopped.exitCode !== 130) throw new Error(JSON.stringify(stopped));
                cases.push('stop a Python loop');
                await wait(() => document.body.innerText.replace(/\u00a0/g, ' ').includes('Python stopped.'));
                await open('after.py');
                await command('pythona.runPython');
                const after = await until('finished');
                if (after.exitCode !== 0 || !after.output.includes('native modules 720 42')) throw new Error(JSON.stringify(after));
                cases.push('rerun with asyncio and native sqlite3/math modules');
                await command('cursorBottom');
                await command('type', {text:'# editor remains usable 你好\n'});
                await command('workbench.action.files.save');
                cases.push('edit and save after execution');
                await request('smoke.report', {passed:true, cases, output:after.output});
              } catch (error) {
                await request('smoke.report', {passed:false, cases, error:String(error), stack:error.stack});
              }
            })(); void 0;
            """.replace("WORKSPACE", json.dumps(workspace["id"]))
            builtins.run_on_ui(lambda: host.webview.evaluateJavaScript_completionHandler_(script, None)).wait()
            if not completed.wait(90):
                raise RuntimeError("Native workbench execution timed out.")
            report["saved"] = (project / "after.py").read_text()
            report["passed"] = bool(report["frontend"]["passed"] and "editor remains usable 你好" in report["saved"])
            app.close()
            builtins.run_on_ui(host.close).wait()
            server.close()
            app = host = server = None
    except BaseException:
        report["error"] = traceback.format_exc()
    finally:
        if app:
            app.close()
        if host:
            builtins.run_on_ui(host.close).wait()
        if server:
            server.close()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Native execution {'passed' if report['passed'] else 'failed'}: {report_path}")


if __name__ == "__main__":
    main()

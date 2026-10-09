"""Exercise listener recovery, dirty editors, and the actual native close button."""

import builtins
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback


def main():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    report = {"passed": False}
    app = server = host = None
    callback_errors = []
    original_unraisable = sys.unraisablehook

    def callback_error(error):
        callback_errors.append(str(error.exc_value))
        original_unraisable(error)

    sys.unraisablehook = callback_error
    with tempfile.TemporaryDirectory(prefix="pythona_vscode_resume_") as temporary:
        try:
            from vscode_app.server import LocalServer
            from vscode_app.ui import WorkbenchWindow
            from vscode_app.workspace import WorkspaceApp

            documents = Path(temporary) / "Documents"
            project = documents / "Resume Workspace"
            project.mkdir(parents=True)
            file = project / "main.py"
            file.write_text('print("resume")\n')
            (project / "other.py").write_text('print("opened after recovery")\n')
            app = WorkspaceApp(documents, Path(temporary) / "state.json")
            app.open_workspace("Resume Workspace")
            replies = []
            completed = threading.Event()
            original_dispatch = app.dispatch

            def dispatch(action, payload=None):
                if action == "resume.report":
                    replies.append(payload)
                    completed.set()
                    return None
                return original_dispatch(action, payload)

            app.dispatch = dispatch
            server = LocalServer(app)
            host = WorkbenchWindow(app, server)
            builtins.run_on_ui(host.open).wait()

            def evaluate(body):
                completed.clear()
                script = r"""
                (async () => {
                  const wait = async predicate => {
                    for (let i=0; i<300; i++) {
                      if (predicate()) return;
                      await new Promise(resolve=>setTimeout(resolve,100));
                    }
                    throw new Error('Timed out: '+document.body.innerText);
                  };
                  const report = async payload => {
                    for (let i=0; i<50; i++) {
                      try { if ((await fetch(new URL('health',location.href))).ok) break; } catch {}
                      await new Promise(resolve=>setTimeout(resolve,100));
                    }
                    await fetch(new URL('api',location.href),{
                      method:'POST',headers:{'Content-Type':'application/json','X-Pythona-Session':location.pathname.split('/')[1]},
                      body:JSON.stringify({action:'resume.report',payload})
                    });
                  };
                  try {
                    await wait(()=>window.pythonaWorkbench?.ready);
                    const run=window.pythonaWorkbench.executeCommand;
                    BODY
                  } catch(error) { await report({error:String(error)}); }
                })();
                """.replace("BODY", body)
                builtins.run_on_ui(lambda: host.webview.evaluateJavaScript_completionHandler_(script, None)).wait()
                if not completed.wait(35):
                    raise RuntimeError("Native recovery test did not respond.")
                result = replies.pop(0)
                if result.get("error"):
                    raise RuntimeError(result["error"])
                return result

            # Navigation must exist before injecting the asynchronous test driver.
            deadline = time.monotonic() + 30
            while not host.loaded and time.monotonic() < deadline:
                time.sleep(0.05)
            if not host.loaded:
                raise RuntimeError("The workbench did not load.")
            before = evaluate(r"""
                await run('_workbench.open',{scheme:'file',path:'/Documents/Resume Workspace/main.py'});
                await run('cursorBottom');
                await run('type',{text:'# Unsaved across background 你好\n'});
                window.resumeSmokeMarker=crypto.randomUUID();
                await report({marker:window.resumeSmokeMarker,url:location.href});
            """)

            def pause():
                builtins.run_on_ui(lambda: host.handler.pause_(None)).wait()
                deadline = time.monotonic() + 3
                while server.thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.01)
                if server.thread.is_alive():
                    raise RuntimeError("The background callback did not release the listener.")

            pause()
            builtins.run_on_ui(lambda: host.webview.evaluateJavaScript_completionHandler_(
                "window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}))", None)).wait()
            builtins.run_on_ui(lambda: host.handler.resume_(None)).wait()
            after = evaluate(r"""
                await run('_workbench.open',{scheme:'file',path:'/Documents/Resume Workspace/other.py'});
                await wait(()=>document.querySelector('.monaco-editor .view-lines')?.textContent.replaceAll('\u00a0',' ').includes('opened after recovery'));
                await run('_workbench.open',{scheme:'file',path:'/Documents/Resume Workspace/main.py'});
                await run('workbench.action.files.save');
                await run('cursorBottom');
                await run('type',{text:'# Saved from native close\n'});
                await report({marker:window.resumeSmokeMarker,url:location.href});
            """)
            report["sameDocumentAndOrigin"] = before == after
            report["recoveredSave"] = "# Unsaved across background 你好" in file.read_text()

            # The native button itself should recover an unavailable HTTP listener.
            pause()
            builtins.run_on_ui(lambda: host.close_button.sendActionsForControlEvents_(1 << 6)).wait()
            evaluate(r"""
                const cancel=()=>[...document.querySelectorAll('button,[role="button"]')].find(item=>item.textContent==='Cancel');
                await wait(()=>cancel());
                cancel().click();
                await report({cancelled:true});
            """)
            report["cancelKeptWindow"] = not app.closed.is_set()
            builtins.run_on_ui(lambda: host.close_button.sendActionsForControlEvents_(1 << 6)).wait()
            evaluate(r"""
                const save=()=>[...document.querySelectorAll('button,[role="button"]')].find(item=>item.textContent==='Save All');
                await wait(()=>save());
                await report({saveButtonFound:true});
                save().click();
            """)
            report["nativeCloseCompleted"] = app.closed.wait(20)
            report["nativeCloseSaved"] = "# Saved from native close" in file.read_text()
            report["passed"] = all(report[key] for key in (
                "sameDocumentAndOrigin", "recoveredSave", "cancelKeptWindow", "nativeCloseCompleted", "nativeCloseSaved"))
        except Exception:
            report["error"] = traceback.format_exc()
        finally:
            if host:
                builtins.run_on_ui(host.close).wait()
            if server:
                server.close()
            if app:
                app.close()
            sys.unraisablehook = original_unraisable
    report["callbackErrors"] = callback_errors
    report["passed"] = report["passed"] and not callback_errors
    destination = root / ".local" / "native-resume.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    main()

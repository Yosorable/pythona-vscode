"""Exercise the built workbench in Pythona's actual WKWebView with temporary files."""

import builtins
from ctypes import byref, c_double
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
    original_unraisable = sys.unraisablehook

    def record_callback_error(error):
        target = root / ".local" / "native-callback-error.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(traceback.format_exception(error.exc_type, error.exc_value, error.exc_traceback)), encoding="utf-8")
        original_unraisable(error)

    sys.unraisablehook = record_callback_error
    with tempfile.TemporaryDirectory(prefix="pythona_vscode_smoke_") as temporary:
        try:
            from vscode_app.server import LocalServer
            from vscode_app.ui import WorkbenchWindow
            from vscode_app.workspace import WorkspaceApp

            documents = Path(temporary) / "Documents"
            project = documents / "Native Workspace"
            project.mkdir(parents=True)
            file = project / "main.py"
            file.write_text('print("Native workspace")\n', encoding="utf-8")
            app = WorkspaceApp(documents, Path(temporary) / "state.json")
            workspace = app.open_workspace("Native Workspace")
            reports = []
            completed = threading.Event()
            original = app.dispatch

            def dispatch(action, payload=None):
                if action == "smoke.report":
                    reports.append(payload)
                    completed.set()
                    return None
                return original(action, payload)

            app.dispatch = dispatch
            server = LocalServer(app)
            host = WorkbenchWindow(app, server)
            builtins.run_on_ui(host.open).wait()
            transparent_at_start = builtins.run_on_ui(lambda: host.webview.alpha == 0).wait()
            deadline = time.monotonic() + 30
            while not host.loaded and not app.closed.is_set() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not host.loaded:
                raise RuntimeError(f"The native web view did not finish loading: {host.navigation_error}")
            script = r"""
            (async () => {
              const wait = async predicate => {
                for (let i=0; i<300; i++) { if (predicate()) return; await new Promise(r=>setTimeout(r,100)); }
                throw new Error('Timed out: '+document.body.innerText);
              };
              const report = payload => fetch(new URL('api', location.href), {
                method:'POST', headers:{'Content-Type':'application/json','X-Pythona-Session':location.pathname.split('/')[1]},
                body:JSON.stringify({action:'smoke.report',payload})
              });
              try {
                await wait(()=>window.pythonaWorkbench?.ready);
                const run = window.pythonaWorkbench.executeCommand;
                await run('_workbench.open', {scheme:'file',path:FILE_PATH});
                await wait(()=>document.querySelector('.monaco-editor .view-line'));
                await run('cursorBottom');
                await run('type',{text:'# Native save 你好 🐍\n'});
                await run('workbench.action.files.save');
                await run('workbench.action.splitEditorRight');
                const painted = () => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
                await painted();
                const menus = {};
                for (const name of ['File', 'Edit', 'Selection', 'View', 'Go', 'Help']) {
                  const button = [...document.querySelectorAll('.menubar-menu-button')].find(item=>item.textContent===name);
                  if (!button) throw new Error('Missing menu: '+name);
                  for (const type of ['mousedown', 'mouseup']) {
                    button.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,view:window,button:0}));
                  }
                  await painted();
                  const holder = document.querySelector('.menubar-menu-items-holder');
                  if (!holder) throw new Error('Menu did not open: '+name);
                  const items = [...holder.querySelectorAll('.action-item')].filter(item=>item.textContent.trim());
                  menus[name] = items.length > 0 && items.every(item=>{
                    const rect = item.getBoundingClientRect();
                    return item.contains(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2));
                  });
                  window.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,button:0}));
                  await painted();
                }
                await report({passed:Object.values(menus).every(Boolean),menus,width:innerWidth,height:innerHeight,userAgent:navigator.userAgent,
                  editors:document.querySelectorAll('.editor-group-container').length,
                  background:getComputedStyle(document.documentElement).backgroundColor,
                  text:document.body.innerText});
              } catch(error) { await report({passed:false,error:String(error),text:document.body.innerText}); }
            })();
            """.replace("FILE_PATH", json.dumps(f"/Documents/{workspace['path']}/main.py"))
            builtins.run_on_ui(lambda: host.webview.evaluateJavaScript_completionHandler_(script, None)).wait()
            if not completed.wait(40):
                raise RuntimeError("The workbench did not send a native smoke report.")
            report = reports[0]
            report["transparentAtStart"] = transparent_at_start
            report["visibleAfterReady"] = builtins.run_on_ui(lambda: host.webview.alpha == 1).wait()
            def native_colors():
                result = {}
                for name, color in (
                    ("container", host.controller.view.backgroundColor),
                    ("webview", host.webview.backgroundColor),
                    ("page", host.webview.underPageBackgroundColor),
                    ("scroll", host.webview.scrollView.backgroundColor),
                ):
                    components = [c_double() for _ in range(4)]
                    if not color.getRed_green_blue_alpha_(*(byref(item) for item in components)):
                        raise RuntimeError(f"Could not read {name} background color.")
                    result[name] = [item.value for item in components]
                return result

            report["nativeBackgrounds"] = builtins.run_on_ui(native_colors).wait()
            report["nativeBackgroundsMatch"] = all(
                all(abs(actual - expected) < 0.00001 for actual, expected in zip(color, [24 / 255] * 3 + [1]))
                for color in report["nativeBackgrounds"].values())
            report["saved"] = file.read_text(encoding="utf-8")
            builtins.run_on_ui(lambda: host.webview.reload()).wait()
            report["transparentDuringReload"] = False
            report["visibleAfterReload"] = False
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                alpha = builtins.run_on_ui(lambda: host.webview.alpha).wait()
                if alpha == 0:
                    report["transparentDuringReload"] = True
                elif report["transparentDuringReload"] and host.loaded:
                    report["visibleAfterReload"] = True
                    break
                time.sleep(0.02)
            report["passed"] = bool(report.get("passed") and "# Native save 你好 🐍" in report["saved"]
                                    and report["transparentAtStart"] and report["visibleAfterReady"]
                                    and report["transparentDuringReload"] and report["visibleAfterReload"]
                                    and report["nativeBackgroundsMatch"] and report["background"] == "rgb(24, 24, 24)")
            time.sleep(2)
        except Exception:
            report = {"passed": False, "error": traceback.format_exc()}
        finally:
            sys.unraisablehook = original_unraisable
            if host:
                builtins.run_on_ui(host.close).wait()
            if server:
                server.close()
            if app:
                app.close()
    result = root / ".local" / "native-smoke.json"
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    main()

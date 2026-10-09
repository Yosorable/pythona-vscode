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


def native_colors(host):
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


def run_case(scheme):
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    report = {"passed": False}
    app = server = host = None
    theme_requested = threading.Event()
    release_theme = threading.Event()
    callback_errors = []
    original_unraisable = sys.unraisablehook

    def record_callback_error(error):
        callback_errors.append(str(error.exc_value))
        target = root / ".local" / "native-callback-error.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(traceback.format_exception(error.exc_type, error.exc_value, error.exc_traceback)), encoding="utf-8")
        original_unraisable(error)

    sys.unraisablehook = record_callback_error
    with tempfile.TemporaryDirectory(prefix="pythona_vscode_smoke_") as temporary:
        try:
            from vscode_app.server import Handler, LocalServer
            from vscode_app.ui import WorkbenchWindow
            from vscode_app.workspace import WorkspaceApp

            documents = Path(temporary) / "Documents"
            project = documents / "Native Workspace"
            project.mkdir(parents=True)
            file = project / "main.py"
            file.write_text('print("Native workspace")\n', encoding="utf-8")
            app = WorkspaceApp(documents, Path(temporary) / "state.json")
            if scheme == "light":
                app.dispatch("preferences.update", {
                    "settings": '{"workbench.colorTheme": "Light Modern"}',
                    "theme": {"name": "Light Modern", "type": "light", "colors": {
                        "sideBar.background": "#f8f8f8", "editor.background": "#ffffff", "foreground": "#616161"}},
                })
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
            class DelayedThemeHandler(Handler):
                def do_GET(self):
                    if f"/{scheme}_modern-" in self.path:
                        theme_requested.set()
                        release_theme.wait(15)
                    super().do_GET()

            server = LocalServer(app)
            server.http.RequestHandlerClass = DelayedThemeHandler
            host = WorkbenchWindow(app, server)
            builtins.run_on_ui(host.open).wait()
            transparent_at_start = builtins.run_on_ui(lambda: host.webview.alpha == 0).wait()
            if not theme_requested.wait(30):
                raise RuntimeError("The workbench did not request its theme.")
            # Hold the theme across multiple frames to detect premature native reveal.
            time.sleep(0.3)
            transparent_while_loading = builtins.run_on_ui(lambda: host.webview.alpha == 0).wait()
            colors_while_loading = builtins.run_on_ui(lambda: native_colors(host)).wait()
            style_while_loading = builtins.run_on_ui(lambda: host.controller.overrideUserInterfaceStyle).wait()
            release_theme.set()
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
                const menuFailures = {};
                const hit = item => {
                  const rect = item.getBoundingClientRect();
                  return rect.width > 0 && rect.height > 0 &&
                    item.contains(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2));
                };
                let touchID = 0;
                const press = item => {
                  if (!item || !hit(item)) throw new Error('Menu target is not hittable: '+item?.textContent);
                  const rect = item.getBoundingClientRect();
                  const x = rect.x+rect.width/2, y = rect.y+rect.height/2;
                  const target = document.elementFromPoint(x,y);
                  const touch = new Touch({identifier:++touchID,target,clientX:x,clientY:y,pageX:x,pageY:y});
                  for (const type of ['touchstart', 'touchend']) {
                    const touches = type === 'touchstart' ? [touch] : [];
                    target.dispatchEvent(new TouchEvent(type,{bubbles:true,cancelable:true,
                      touches,targetTouches:touches,changedTouches:[touch]}));
                  }
                };
                const openMenu = async name => {
                  const buttons = [...document.querySelectorAll('.menubar-menu-button')];
                  const button = buttons.find(item=>item.textContent===name && hit(item));
                  if (button) {
                    press(button);
                  } else {
                    press(buttons.find(item=>item.querySelector('.toolbar-toggle-more')));
                    await painted();
                    press([...document.querySelectorAll('.monaco-submenu-item')]
                      .find(item=>item.querySelector('.action-label')?.textContent===name));
                  }
                  await painted();
                  // Narrow windows nest menus; a submenu may cover its parent's other entries.
                  const holder = [...document.querySelectorAll('.menubar-menu-items-holder')].at(-1);
                  if (!holder) throw new Error('Menu did not open: '+name);
                  return holder;
                };
                for (const name of ['File', 'Edit', 'Selection', 'View', 'Go', 'Help']) {
                  const holder = await openMenu(name);
                  const items = [...holder.querySelectorAll('.action-item')].filter(item=>item.textContent.trim());
                  menuFailures[name] = items.filter(item=>!hit(item)).map(item=>item.textContent.trim());
                  menus[name] = items.length > 0 && menuFailures[name].length === 0;
                  window.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,button:0}));
                  await painted();
                }
                const go = await openMenu('Go');
                press([...go.querySelectorAll('.action-menu-item')]
                  .find(item=>item.querySelector('.action-label')?.textContent==='Go to File...'));
                await wait(()=>document.querySelector('.quick-input-widget input')===document.activeElement);
                await painted();
                const menuCommandFocused = document.querySelector('.quick-input-widget input')===document.activeElement &&
                  !document.querySelector('.menubar-menu-items-holder');
                await report({passed:Object.values(menus).every(Boolean) && menuCommandFocused,
                  menus,menuFailures,menuCommandFocused,width:innerWidth,height:innerHeight,userAgent:navigator.userAgent,
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
            report["transparentWhileThemeLoads"] = transparent_while_loading
            report["backgroundsWhileThemeLoads"] = colors_while_loading
            report["interfaceStyleWhileThemeLoads"] = style_while_loading
            report["visibleAfterReady"] = builtins.run_on_ui(lambda: host.webview.alpha == 1).wait()
            report["nativeBackgrounds"] = builtins.run_on_ui(lambda: native_colors(host)).wait()
            expected_component = 248 if scheme == "light" else 24
            report["nativeBackgroundsMatch"] = all(
                all(abs(actual - expected) < 0.00001 for actual, expected in zip(color, [expected_component / 255] * 3 + [1]))
                for colors in (colors_while_loading, report["nativeBackgrounds"]) for color in colors.values())
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
                                    and report["transparentWhileThemeLoads"]
                                    and report["interfaceStyleWhileThemeLoads"] == (1 if scheme == "light" else 2)
                                    and report["transparentDuringReload"] and report["visibleAfterReload"]
                                    and report["nativeBackgroundsMatch"]
                                    and report["background"] == f"rgb({expected_component}, {expected_component}, {expected_component})")
        except Exception:
            report = {"passed": False, "error": traceback.format_exc()}
        finally:
            release_theme.set()
            sys.unraisablehook = original_unraisable
            if host:
                builtins.run_on_ui(host.close).wait()
            if server:
                server.close()
            if app:
                app.close()
    report["scheme"] = scheme
    report["callbackErrors"] = callback_errors
    report["passed"] = report["passed"] and not callback_errors
    return report


def main():
    cases = [run_case(scheme) for scheme in ("dark", "light")]
    report = {"passed": all(case["passed"] for case in cases), "themes": cases}
    root = Path(__file__).resolve().parents[1]
    result = root / ".local" / "native-smoke.json"
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    main()

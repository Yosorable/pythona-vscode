"""Present the local workbench in a keyboard-sized UIKit web view."""

import builtins
from ctypes import c_long, c_void_p
import json
from pathlib import Path
import weakref

from rubicon.objc import NSObject, ObjCBlock, ObjCClass, SEL, objc_method
from rubicon.objc.runtime import load_library

from .server import LocalServer
from .workspace import WorkspaceApp
from .filesystem import WorkspaceError
from .preferences import validate_theme


_WEBKIT = load_library("WebKit")


def value(receiver, name):
    item = getattr(receiver, name)
    return item() if callable(item) else item


def presenter():
    application = value(ObjCClass("UIApplication"), "sharedApplication")
    for scene in value(application.connectedScenes, "allObjects"):
        if not scene.isKindOfClass_(ObjCClass("UIWindowScene")) or scene.activationState != 0:
            continue
        for window in scene.windows:
            if value(window, "isKeyWindow"):
                controller = window.rootViewController
                while controller.presentedViewController is not None:
                    controller = controller.presentedViewController
                return controller
    raise RuntimeError("No active Pythona window is available.")


class WorkbenchHandler(NSObject, auto_rename=True):
    @objc_method
    def userContentController_didReceiveScriptMessage_(self, controller, message):
        host = self.host_ref()
        if not (host and host.webview is not None and value(message.frameInfo, "isMainFrame")):
            return
        if str(message.name) == "workbenchReady" and str(message.body) == "ready":
            host.webview.alpha = 1
        elif str(message.name) == "workbenchTheme":
            try:
                host.apply_theme(validate_theme(json.loads(str(message.body))))
            except (ValueError, WorkspaceError):
                pass

    @objc_method
    def webView_didStartProvisionalNavigation_(self, webview, navigation):
        host = self.host_ref()
        if host:
            host.loaded = False
            if host.webview is not None:
                host.webview.alpha = 0

    @objc_method
    def webView_decidePolicyForNavigationAction_decisionHandler_(self, webview, action, decision: c_void_p) -> None:
        host = self.host_ref()
        allow = external = False
        url = None
        try:
            url = value(value(action, "request"), "URL")
            address = str(value(url, "absoluteString")) if url is not None else ""
            allow = host is not None and (address.startswith(host.server.url) or address == "about:blank")
            external = (not allow and value(action, "navigationType") == 0
                        and address.startswith(("https://", "http://")))
        except Exception as error:
            if host:
                host.navigation_error = str(error)
                host.app.closed.set()
            print(f"Unable to open the workbench: {error}")
        finally:
            # WebKit requires the completion on every path, including bridge errors.
            # WebKit may pass a block without an Objective-C type signature.
            # Keep its argument raw and supply the void(NSInteger) ABI explicitly.
            ObjCBlock(decision, None, c_long)(1 if allow else 0)
        if external:
            application = value(ObjCClass("UIApplication"), "sharedApplication")
            application.openURL_options_completionHandler_(url, {}, None)

    @objc_method
    def closeTap(self):
        host = self.host_ref()
        if host is None:
            return
        if host.loaded:
            host.webview.evaluateJavaScript_completionHandler_(
                "window.pythonaWorkbench?.requestClose()", None)
        else:
            host.app.closed.set()

    @objc_method
    def webView_didFinishNavigation_(self, webview, navigation):
        host = self.host_ref()
        if host:
            host.loaded = True

    @objc_method
    def webViewWebContentProcessDidTerminate_(self, webview):
        host = self.host_ref()
        if host:
            print("iPadOS closed the workbench. Run main.py to reopen the workspace.")
            host.app.closed.set()


class WorkbenchWindow:
    def __init__(self, app, server):
        self.app, self.server = app, server
        self.controller = self.webview = self.handler = None
        self.close_button = None
        self.loaded = False
        self.navigation_error = None

    def open(self):
        self.controller = ObjCClass("UIViewController").alloc().init()
        self.controller.modalPresentationStyle = 0
        self.controller.modalInPresentation = True
        view = self.controller.view
        self.apply_theme(self.app.preferences.snapshot()["theme"])
        configuration = ObjCClass("WKWebViewConfiguration").alloc().init()
        # The desktop content mode gives iPad keyboards the Mac command bindings.
        configuration.defaultWebpagePreferences.preferredContentMode = 2
        configuration.suppressesIncrementalRendering = True
        configuration.websiteDataStore = value(ObjCClass("WKWebsiteDataStore"), "nonPersistentDataStore")
        self.handler = WorkbenchHandler.alloc().init()
        self.handler.host_ref = weakref.ref(self)
        configuration.userContentController.addScriptMessageHandler_name_(self.handler, "workbenchReady")
        configuration.userContentController.addScriptMessageHandler_name_(self.handler, "workbenchTheme")
        self.webview = ObjCClass("WKWebView").alloc().initWithFrame_configuration_(view.bounds, configuration)
        self.webview.alpha = 0
        self.webview.opaque = False
        self.webview.backgroundColor = view.backgroundColor
        self.webview.underPageBackgroundColor = view.backgroundColor
        self.webview.scrollView.backgroundColor = view.backgroundColor
        self.webview.navigationDelegate = self.handler
        self.webview.translatesAutoresizingMaskIntoConstraints = False
        self.webview.scrollView.contentInsetAdjustmentBehavior = 2
        self.webview.scrollView.bounces = False
        view.addSubview_(self.webview)

        close = ObjCClass("UIButton").buttonWithType_(1)
        self.close_button = close
        close.translatesAutoresizingMaskIntoConstraints = False
        close.setImage_forState_(ObjCClass("UIImage").systemImageNamed_("xmark"), 0)
        self.apply_theme(self.app.preferences.snapshot()["theme"])
        close.addTarget_action_forControlEvents_(self.handler, SEL("closeTap"), 1 << 6)
        view.addSubview_(close)
        ObjCClass("NSLayoutConstraint").activateConstraints_([
            self.webview.topAnchor.constraintEqualToAnchor_(view.safeAreaLayoutGuide.topAnchor),
            self.webview.leadingAnchor.constraintEqualToAnchor_(view.safeAreaLayoutGuide.leadingAnchor),
            self.webview.trailingAnchor.constraintEqualToAnchor_(view.safeAreaLayoutGuide.trailingAnchor),
            self.webview.bottomAnchor.constraintEqualToAnchor_(view.keyboardLayoutGuide.topAnchor),
            close.topAnchor.constraintEqualToAnchor_constant_(view.safeAreaLayoutGuide.topAnchor, 1),
            close.trailingAnchor.constraintEqualToAnchor_constant_(view.safeAreaLayoutGuide.trailingAnchor, -2),
            close.widthAnchor.constraintEqualToConstant_(32),
            close.heightAnchor.constraintEqualToConstant_(32),
        ])
        url = ObjCClass("NSURL").URLWithString_(self.server.url)
        self.webview.loadRequest_(ObjCClass("NSURLRequest").requestWithURL_(url))
        presenter().presentViewController_animated_completion_(self.controller, True, None)

    def apply_theme(self, theme):
        def color(key):
            hex_value = theme["colors"][key]
            rgb = [int(hex_value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            return ObjCClass("UIColor").colorWithRed_green_blue_alpha_(*rgb, 1)

        background = color("sideBar.background")
        self.controller.overrideUserInterfaceStyle = 1 if theme["type"] in ("light", "hcLight") else 2
        self.controller.view.backgroundColor = background
        if self.webview:
            self.webview.backgroundColor = background
            self.webview.underPageBackgroundColor = background
            self.webview.scrollView.backgroundColor = background
        if self.close_button:
            self.close_button.tintColor = color("foreground")

    def close(self):
        if self.webview:
            self.webview.configuration.userContentController.removeScriptMessageHandlerForName_("workbenchReady")
            self.webview.configuration.userContentController.removeScriptMessageHandlerForName_("workbenchTheme")
            self.webview.navigationDelegate = None
            self.webview.stopLoading()
        if self.controller and self.controller.presentingViewController is not None:
            self.controller.dismissViewControllerAnimated_completion_(False, None)
        self.controller = self.webview = self.handler = None
        self.close_button = None


def main():
    def environment():
        manager = value(ObjCClass("NSFileManager"), "defaultManager")
        documents = manager.URLsForDirectory_inDomains_(9, 1)[0]
        bundle = value(ObjCClass("NSBundle"), "mainBundle")
        languages = value(bundle, "preferredLocalizations")
        return Path(str(value(documents, "path"))), str(languages[0]) if len(languages) else "en"

    documents, language = builtins.run_on_ui(environment).wait()
    app = WorkspaceApp(documents, Path(__file__).resolve().parents[1] / ".local" / "state.json",
                       language=language)
    server = host = None
    try:
        server = LocalServer(app)
        host = WorkbenchWindow(app, server)
        builtins.run_on_ui(host.open).wait()
        while not app.closed.wait(0.05):
            pass
    finally:
        if host:
            builtins.run_on_ui(host.close).wait()
        if server:
            server.close()
        app.close()

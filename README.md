# Pythona VSCode

An iPad-first, local code workspace for [Pythona](https://pythona.app), built with
the VS Code workbench through [monaco-vscode-api](https://github.com/CodinGame/monaco-vscode-api).

Clone this project into Pythona and run **`main.py`**. The compiled frontend is
included; using the app needs no Node.js, CDN, account, or remote server.

This is an independent open-source project, not a Microsoft product.

## First version

- A VS Code workbench with the Explorer, editor tabs, split editors, breadcrumbs,
  command palette, quick open, and workspace text search.
- Open one project folder inside Pythona's local **Documents**. The first launch
  is an empty workbench; Documents is a folder-selection boundary, not the workspace.
- Edit and save real files, and create, rename, or delete files and folders.
- Syntax highlighting for Python, JSON, and Markdown.
- Save, discard, or cancel when switching or closing a workspace with unsaved edits.
- Reopen the last workspace and retain a list of recently opened projects.
- English, Simplified Chinese, and Traditional Chinese, following Pythona's language.
- A keyboard-sized native viewport and a workbench readiness handshake that prevents
  a white WebView from appearing while the page starts or reloads.

This initial version focuses on editing. Python execution, a REPL or SSH terminal,
Git integration, AI assistance, and an extension marketplace are not implemented.

## Run in Pythona

1. Clone or copy the entire repository, including `frontend/dist`, into local Documents.
2. Run `main.py` from the project root.
3. Select **Open Folder**, navigate to a project, and choose **Open This Folder**.
   **New Folder…** creates a project folder if needed.
4. Open a file in the Explorer. Use **File → Save** or the keyboard save shortcut.
5. Use **Pythona: Open Folder…** in the command palette to switch projects.
   The native **×** button closes the window after offering to save dirty files.

The last selected folder reopens next time. **Pythona: Close Folder** returns to
the empty workbench. Single-folder workspaces are supported; `.code-workspace`
multi-root files, iCloud, and external folders are outside this version's scope.

Files larger than 16 MiB are rejected. Symlinks are not followed, including links
to other locations inside Documents. Deletion requires the workbench's confirmation
and permanently removes the selected files; this version does not provide a trash.
Changes made by another editor may require **Refresh Explorer** or reopening a file.
Saves reject a detected conflicting on-disk edit.

Save before stopping the hosting Python script or closing Pythona. Unsaved buffers
are held in WebKit memory and cannot be recovered after an iPadOS process termination.

## Browser preview

On macOS or Linux with Python 3.11 or newer:

```sh
python3 main.py --preview
```

Open the loopback URL printed in the terminal. The default preview creates a
temporary Documents directory with sample projects and removes it on exit.

To work with a specific local directory during development:

```sh
python3 main.py --preview --documents /path/to/development-projects --state .local/preview.json
```

Here, **Open Folder** lists child projects beneath that directory. Editing and
saving changes those real files. The directory itself cannot be opened as a workspace.

## Development

The Python host uses the standard library and Pythona's bundled Rubicon. Use
Node.js 26 and npm to develop the frontend:

```sh
cd frontend
npm ci
npm run build
cd ..
python3 main.py --preview
```

Keep the built `frontend/dist` directory and the generated third-party notices
in the same change as their frontend sources. All workbench packages are pinned
to the same release. Dependency overrides apply patched DOMPurify and KaTeX versions.

```text
main.py                    Pythona entry point and browser preview
vscode_app/
  ui.py                    UIKit / WKWebView presentation and readiness
  server.py                Loopback static assets and JSON API
  workspace.py             Workspace selection, recent folders, and state
  filesystem.py            Descriptor-relative file operations and atomic saves
frontend/
  src/workbench.ts          VS Code services, commands, and folder picker
  src/filesystem.ts         Workbench filesystem provider
  src/bridge.ts             Local request transport
  src/storage.ts            Workbench storage adapter
  src/strings.ts            Product translations
  dist/                    Offline production bundle
tests/                     Python integration and native smoke tests
.local/                    Local workspace/UI state; ignored by Git
```

Node.js is a build tool only. At runtime a Python HTTP server binds an ephemeral
port on `127.0.0.1` and serves the local bundle. This supplies the origin needed
by ES modules, workers, and WebAssembly. File requests are handled by Python
threads and translated through a workspace filesystem provider. No code execution
endpoint is exposed.

The native host starts WKWebView at `alpha = 0`. The frontend signals readiness
after initialization and two animation frames; the host then sets `alpha = 1`.
Native and HTML backgrounds use the same dark color during startup and reload.

## Validation

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
cd frontend
npm ci
npx playwright install webkit
npm run build
npm test
```

Local browser checks use an installed Google Chrome and Playwright WebKit with an
iPad viewport. The tests use temporary
projects and cover actual saves, workspace switching, dirty-file choices, split
editors, menu actions, nested-file search, offline loading, and the pre-JavaScript background.
Python checks cover filesystem boundaries, symlinks, conflicting writes, persistence,
HTTP request validation, and shutdown.

Run **`tests/native_smoke.py`** inside Pythona to exercise the real UIKit container,
WebKit readiness, Unicode saves, split editors, and menu hit testing. It uses temporary files, closes
its own window/server, and writes a report to `.local/native-smoke.json`.
Automated smoke tests do not substitute for hands-on Chinese IME, touch-selection,
and physical keyboard checks on an iPad.

## Storage and network behavior

Workspace files remain in the selected project. `.local/state.json` beside
`main.py` stores Documents-relative recent paths and the last workspace.
`.local/workbench` stores workbench UI state. The WebView uses a nonpersistent
website data store. Browser preview data is temporary unless `--state` is supplied.

The runtime serves assets and file operations only on loopback, with an unguessable
session path/header and Host/Origin checks. Frontend resources are bundled locally;
there is no analytics, account service, or remote workspace service. Explicitly
opening an external help link uses the system browser. Installing frontend build
dependencies and cloning the repository use the normal npm/Git network services.

## License and acknowledgments

Pythona VSCode is released under the [MIT License](LICENSE).

- [monaco-vscode-api](https://github.com/CodinGame/monaco-vscode-api) supplies the
  browser workbench, extension APIs, and service adapters.
- [Code - OSS](https://github.com/microsoft/vscode) and
  [Monaco Editor](https://github.com/microsoft/monaco-editor) provide the editor
  and workbench implementation.
- [Pythona SSH](https://github.com/Yosorable/pythona-ssh) provided a starting point
  for the Python / UIKit host structure.

Upstream license files are retained in [licenses](licenses), and bundled dependency
notices are generated in [frontend/THIRD_PARTY_NOTICES.txt](frontend/THIRD_PARTY_NOTICES.txt).

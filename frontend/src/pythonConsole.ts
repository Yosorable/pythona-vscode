import { getService, IViewsService } from '@codingame/monaco-vscode-api';
import { createConfiguredEditor } from '@codingame/monaco-vscode-api/monaco';
import { registerCustomView, ViewContainerLocation } from '@codingame/monaco-vscode-api/service-override/tools/views';
import { Gesture } from '@codingame/monaco-vscode-api/vscode/vs/base/browser/touch';
import { editor, Uri } from 'monaco-editor';
import { t } from './strings';

export const pythonConsoleID = 'pythona.pythonConsole';

export function createPythonConsole(workspace: string | undefined) {
  // Register the view before workbench layout restoration; create its model only
  // after the editor services exist.
  let textModel: editor.ITextModel | undefined;
  const getModel = () => textModel ??= editor.createModel('', 'plaintext', Uri.parse('pythona-output:/Python'));
  let submit: (text: string) => Promise<unknown> = async () => {};
  const storageKey = `pythona.pythonInput:${workspace ?? ''}`;
  let output: editor.IStandaloneCodeEditor | undefined;
  let field: HTMLInputElement | undefined;
  let send: HTMLButtonElement | undefined;
  let request: string | null = null;
  let draft = '';
  let accepting = false;
  let busy = false;

  function saveDraft(): void {
    try {
      if (request && draft) sessionStorage.setItem(storageKey, JSON.stringify({ request, draft }));
      else sessionStorage.removeItem(storageKey);
    } catch { /* Storage failures must not prevent interactive input. */ }
  }

  function updateInput(): void {
    if (field) field.readOnly = !accepting || busy;
    if (send) send.disabled = !accepting || busy;
  }

  function append(text: string): void {
    if (!text) return;
    const model = getModel();
    const follow = !output || output.getScrollTop() + output.getLayoutInfo().height >= output.getScrollHeight() - 24;
    const end = model.getFullModelRange().getEndPosition();
    model.applyEdits([{ range: { startLineNumber: end.lineNumber, startColumn: end.column,
      endLineNumber: end.lineNumber, endColumn: end.column }, text }]);
    // Bound the visible transcript as well as the host's retained output.
    if (model.getValueLength() > 1_048_576) {
      const trim = model.getPositionAt(model.getValueLength() - 1_048_576);
      model.applyEdits([{ range: { startLineNumber: 1, startColumn: 1,
        endLineNumber: trim.lineNumber, endColumn: trim.column }, text: '' }]);
    }
    if (follow) output?.revealLine(model.getLineCount());
  }

  const registration = registerCustomView({
    id: pythonConsoleID, name: 'Python', location: ViewContainerLocation.Panel,
    order: 3, canMoveView: false,
    renderBody(container) {
      container.classList.add('python-console');
      const transcript = document.createElement('div');
      transcript.className = 'python-console-output';
      const form = document.createElement('form');
      form.className = 'python-console-input';
      // As with upstream InputBox, let native touches reach the form instead
      // of the enclosing workbench pane's synthesized scroll/tap gestures.
      const gesture = Gesture.ignoreTarget(form);
      field = document.createElement('input');
      field.type = 'text';
      field.placeholder = t('pythonInputHint');
      field.autocomplete = 'off';
      field.spellcheck = false;
      field.setAttribute('autocapitalize', 'off');
      field.setAttribute('autocorrect', 'off');
      field.maxLength = 65_536;
      field.value = draft;
      field.addEventListener('input', () => { draft = field!.value; saveDraft(); });
      // Enter confirms an IME candidate before it may submit an input line.
      let composing = false;
      let confirmingComposition = false;
      field.addEventListener('compositionstart', () => { composing = true; });
      field.addEventListener('compositionend', () => { composing = false; });
      field.addEventListener('keydown', event => {
        confirmingComposition = event.isComposing || composing || event.keyCode === 229;
      });
      field.addEventListener('keyup', () => { confirmingComposition = false; });
      send = document.createElement('button');
      send.type = 'submit';
      send.textContent = t('pythonSendInput');
      form.append(field, send);
      form.addEventListener('submit', event => {
        event.preventDefault();
        if (accepting && !busy && !composing && !confirmingComposition) void submit(draft);
      });
      container.append(transcript, form);
      const model = getModel();
      const consoleEditor = createConfiguredEditor(transcript, {
        model, readOnly: true, domReadOnly: true, automaticLayout: true,
        lineNumbers: 'off', glyphMargin: false, folding: false,
        minimap: { enabled: false }, scrollBeyondLastLine: false,
        wordWrap: 'on', renderLineHighlight: 'none', stickyScroll: { enabled: false },
        overviewRulerLanes: 0, lineDecorationsWidth: 8, padding: { top: 8, bottom: 8 },
      }) as editor.IStandaloneCodeEditor;
      output = consoleEditor;
      consoleEditor.revealLine(model.getLineCount());
      updateInput();
      return { dispose() {
        gesture.dispose(); consoleEditor.dispose(); output = undefined; field = undefined; send = undefined;
      } };
    },
  });

  return {
    append,
    appendLine: (text: string) => append(text + '\n'),
    clear: () => getModel().setValue(''),
    onInput(handler: (text: string) => Promise<unknown>) { submit = handler; },
    async show() {
      // Opening the panel, including when Python requests input, never focuses it.
      await (await getService(IViewsService)).openView(pythonConsoleID, false);
    },
    setInput(identity: string | null, available: boolean, submitting = false) {
      if (identity !== request) {
        request = identity;
        draft = '';
        try {
          const saved = JSON.parse(sessionStorage.getItem(storageKey) ?? 'null');
          if (saved?.request === identity && typeof saved.draft === 'string') draft = saved.draft.slice(0, 65_536);
        } catch { /* The live field remains usable if draft restoration fails. */ }
        if (field) field.value = draft;
        saveDraft();
      }
      accepting = available;
      busy = submitting;
      updateInput();
    },
    dispose() { registration.dispose(); textModel?.dispose(); },
  };
}

export type PythonConsole = ReturnType<typeof createPythonConsole>;

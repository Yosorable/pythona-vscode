import { call, type Bootstrap } from './bridge';
import { languageCode, setLanguage, t } from './strings';
import './style.css';

declare global {
  interface Window {
    webkit?: { messageHandlers?: {
      workbenchReady?: { postMessage(message: string): void };
      workbenchTheme?: { postMessage(message: string): void };
      workbenchFocus?: { postMessage(message: string): void };
    } };
    pythonaWorkbench: {
      ready: boolean;
      requestClose(): Promise<void>;
      activateInput(): void;
      executeCommand?(command: string, ...args: unknown[]): Promise<unknown>;
    };
  }
}

function activeTextInput(): HTMLInputElement | HTMLTextAreaElement | null {
  const element = document.activeElement;
  if ((element instanceof HTMLTextAreaElement || (element instanceof HTMLInputElement
      && /^(text|search|url|email|password|number|tel)$/.test(element.type)))
      && !element.disabled && !element.readOnly) return element;
  return null;
}

let nativeReady = false;
let inputActivated = false;
function activateFirstInput(): void {
  const handler = window.webkit?.messageHandlers?.workbenchFocus;
  if (!handler || !nativeReady || inputActivated || !activeTextInput()) return;
  inputActivated = true;
  handler.postMessage('focus');
}
document.addEventListener('focusin', activateFirstInput);

if (window.webkit?.messageHandlers?.workbenchReady) {
  document.documentElement.classList.add('pythona-webview');
}

window.pythonaWorkbench = {
  ready: false,
  requestClose: async () => { await call('host.close'); },
  activateInput() {
    const element = activeTextInput();
    if (!element) return;
    const start = element.selectionStart;
    const end = element.selectionEnd;
    const direction = element.selectionDirection;
    // Re-enter the existing field from a native JavaScript invocation so WebKit
    // starts its text-input session, preserving the current caret/selection.
    element.blur();
    element.focus({ preventScroll: true });
    if (start !== null && end !== null) element.setSelectionRange(start, end, direction ?? 'none');
  },
};

try {
  const bootstrap = await call<Bootstrap>('bootstrap');
  setLanguage(bootstrap.language);
  document.documentElement.lang = languageCode(bootstrap.language);
  document.querySelector('#startup')!.textContent = t('opening');
  if (languageCode(bootstrap.language) === 'zh-Hans') {
    await import('@codingame/monaco-vscode-language-pack-zh-hans');
  } else if (languageCode(bootstrap.language) === 'zh-Hant') {
    await import('@codingame/monaco-vscode-language-pack-zh-hant');
  }
  const { start } = await import('./workbench');
  await start(bootstrap);
  document.querySelector('#startup')?.remove();
  window.pythonaWorkbench.ready = true;
} catch (error) {
  const startup = document.querySelector('#startup')!;
  startup.textContent = `${t('failed')} ${error instanceof Error ? error.message : String(error)}`;
  console.error(error);
} finally {
  // Reveal the native surface only after styles, layout, and a paint opportunity.
  await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  window.webkit?.messageHandlers?.workbenchReady?.postMessage('ready');
  nativeReady = true;
  activateFirstInput();
}

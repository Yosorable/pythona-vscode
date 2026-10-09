import { call, type Bootstrap } from './bridge';
import { installEditorInput } from './editorInput';
import { languageCode, setLanguage, t, type LanguageCode } from './strings';
import './style.css';

const languagePacks: Record<Exclude<LanguageCode, 'en'>, () => Promise<unknown>> = {
  de: () => import('@codingame/monaco-vscode-language-pack-de'),
  es: () => import('@codingame/monaco-vscode-language-pack-es'),
  fr: () => import('@codingame/monaco-vscode-language-pack-fr'),
  ja: () => import('@codingame/monaco-vscode-language-pack-ja'),
  ko: () => import('@codingame/monaco-vscode-language-pack-ko'),
  'pt-BR': () => import('@codingame/monaco-vscode-language-pack-pt-br'),
  ru: () => import('@codingame/monaco-vscode-language-pack-ru'),
  'zh-Hans': () => import('@codingame/monaco-vscode-language-pack-zh-hans'),
  'zh-Hant': () => import('@codingame/monaco-vscode-language-pack-zh-hant'),
};

declare global {
  interface Window {
    webkit?: { messageHandlers?: {
      workbenchReady?: { postMessage(message: string): void };
      workbenchTheme?: { postMessage(message: string): void };
      workbenchInput?: { postMessage(message: string): void };
    } };
    pythonaWorkbench: {
      ready: boolean;
      requestClose(): Promise<void>;
      activateInput(id: string): void;
      executeCommand?(command: string, ...args: unknown[]): Promise<unknown>;
    };
  }
}

if (window.webkit?.messageHandlers?.workbenchReady) {
  document.documentElement.classList.add('pythona-webview');
}

window.pythonaWorkbench = {
  ready: false,
  requestClose: async () => { await call('host.close'); },
  activateInput: installEditorInput(),
};

try {
  const bootstrap = await call<Bootstrap>('bootstrap');
  const language = languageCode(bootstrap.language);
  setLanguage(language);
  document.documentElement.lang = language;
  document.querySelector('#startup')!.textContent = t('opening');
  if (language !== 'en') await languagePacks[language]();
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
}

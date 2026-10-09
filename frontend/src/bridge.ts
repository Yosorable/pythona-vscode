import { t } from './strings';

export interface Workspace {
  id: string;
  name: string;
  path: string;
}

export interface Bootstrap {
  workspace: Workspace | null;
  recent: string[];
  language: string;
  maxFileBytes: number;
  preferences: Preferences;
}

export interface ThemeSnapshot {
  name: string;
  type: 'dark' | 'light' | 'hcDark' | 'hcLight';
  colors: Record<string, string>;
}

export interface Preferences {
  settings: string;
  theme: ThemeSnapshot;
}

export class HostError extends Error {
  constructor(public code: string, message: string) {
    super(message);
    this.name = 'HostError';
  }
}

let unloading = false;
window.addEventListener('pagehide', () => { unloading = true; });
let recovery: Promise<void> | null = null;

declare global {
  interface Window {
    pythonaConnection: { resume(): void };
  }
}

async function probeConnection(): Promise<void> {
  const deadline = performance.now() + 8000;
  do {
    if (unloading) throw cancelled();
    try {
      const response = await fetch(new URL('health', window.location.href), {
        cache: 'no-store', signal: AbortSignal.timeout(750),
      });
      if (response.ok && await response.text() === window.location.pathname.split('/')[1]) return;
    } catch {
      if (unloading) throw cancelled();
    }
    await new Promise(resolve => setTimeout(resolve, 150));
  } while (performance.now() < deadline);
  throw new HostError('Unavailable', t('connectionUnavailable'));
}

function reconnect(): Promise<void> {
  if (recovery) return recovery;
  const pending = probeConnection();
  recovery = pending;
  void pending.finally(() => { if (recovery === pending) recovery = null; }).catch(() => {});
  return pending;
}

window.pythonaConnection = {
  resume() {
    if (unloading) recovery = null;
    unloading = false;
    void reconnect().catch(() => {});
  },
};
window.addEventListener('pageshow', () => window.pythonaConnection.resume());
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') window.pythonaConnection.resume();
});

const repeatableReads = new Set(['bootstrap', 'folders.list', 'storage.read', 'fs.stat', 'fs.list', 'fs.read']);

function cancelled(): Error {
  const error = new Error('Canceled');
  error.name = 'Canceled';
  return error;
}

export async function call<T>(action: string, payload: Record<string, unknown> = {}): Promise<T> {
  const token = window.location.pathname.split('/')[1];
  if (unloading) throw cancelled();
  if (recovery) await recovery;
  if (unloading) throw cancelled();
  const fileTransfer = action === 'fs.read' || action === 'fs.write';
  const headers: Record<string, string> = {
    'Content-Type': fileTransfer ? 'application/octet-stream' : 'application/json',
    'X-Pythona-Session': token,
  };
  let body: BodyInit | undefined;
  if (fileTransfer) {
    const { data, ...metadata } = payload;
    headers['X-Pythona-Request'] = encodeURIComponent(JSON.stringify({ action, payload: metadata }));
    if (action === 'fs.write') {
      const bytes = data as Uint8Array;
      body = bytes.buffer instanceof ArrayBuffer ? bytes as Uint8Array<ArrayBuffer> : bytes.slice();
    }
  } else body = JSON.stringify({ action, payload });
  const request = async (): Promise<T> => {
    const response = await fetch(new URL(fileTransfer ? 'file' : 'api', window.location.href), {
      method: 'POST', headers, body, signal: AbortSignal.timeout(30000), cache: 'no-store',
    });
    if (!response.ok) throw new HostError('Unavailable', t('connectionUnavailable'));
    if (action === 'fs.read' && response.headers.get('Content-Type') === 'application/octet-stream') {
      const data = new Uint8Array(await response.arrayBuffer());
      const revision = response.headers.get('X-Pythona-Revision');
      if (!revision || !/^[0-9a-f]{64}$/.test(revision)) {
        throw new HostError('Unavailable', t('connectionUnavailable'));
      }
      return { data, revision } as T;
    }
    const reply = await response.json();
    if (reply.error) throw new HostError(reply.error.code, reply.error.message);
    if (action === 'fs.read') throw new HostError('Unavailable', t('connectionUnavailable'));
    return reply.result as T;
  };
  try {
    return await request();
  } catch (error) {
    if (unloading) throw cancelled();
    if (error instanceof HostError) throw error;
    if (!repeatableReads.has(action)) {
      // A lost reply does not prove that a write or deletion was never executed.
      throw new HostError('Unavailable', t('connectionUnavailable'));
    }
    await reconnect();
    if (unloading) throw cancelled();
    try { return await request(); }
    catch (error) {
      if (unloading) throw cancelled();
      throw error instanceof HostError ? error : new HostError('Unavailable', t('connectionUnavailable'));
    }
  }
}

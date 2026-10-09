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
  const request = () => fetch(new URL('api', window.location.href), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Pythona-Session': token },
    body: JSON.stringify({ action, payload }),
    signal: AbortSignal.timeout(30000),
    cache: 'no-store',
  });
  let response: Response;
  try {
    response = await request();
  } catch {
    if (unloading) throw cancelled();
    if (!repeatableReads.has(action)) {
      // A lost reply does not prove that a write or deletion was never executed.
      throw new HostError('Unavailable', t('connectionUnavailable'));
    }
    await reconnect();
    if (unloading) throw cancelled();
    try { response = await request(); }
    catch { throw unloading ? cancelled() : new HostError('Unavailable', t('connectionUnavailable')); }
  }
  if (!response.ok) throw new HostError('Unavailable', t('connectionUnavailable'));
  const reply = await response.json();
  if (reply.error) throw new HostError(reply.error.code, reply.error.message);
  return reply.result as T;
}

export function encodeBytes(bytes: Uint8Array): string {
  let binary = '';
  for (let start = 0; start < bytes.length; start += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
  }
  return btoa(binary);
}

export function decodeBytes(encoded: string): Uint8Array {
  return Uint8Array.from(atob(encoded), char => char.charCodeAt(0));
}

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
}

export class HostError extends Error {
  constructor(public code: string, message: string) {
    super(message);
    this.name = 'HostError';
  }
}

let unloading = false;
window.addEventListener('pagehide', () => { unloading = true; });

function cancelled(): Error {
  const error = new Error('Canceled');
  error.name = 'Canceled';
  return error;
}

export async function call<T>(action: string, payload: Record<string, unknown> = {}): Promise<T> {
  const token = window.location.pathname.split('/')[1];
  if (unloading) throw cancelled();
  let response: Response;
  try {
    response = await fetch(new URL('api', window.location.href), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Pythona-Session': token },
      body: JSON.stringify({ action, payload }),
      signal: AbortSignal.timeout(30000),
      cache: 'no-store',
    });
  } catch {
    if (unloading) throw cancelled();
    throw new HostError('Unavailable', 'The local workspace connection is unavailable.');
  }
  if (!response.ok) throw new HostError('Unavailable', 'The local workspace connection is unavailable.');
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

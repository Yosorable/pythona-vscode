import { Event } from '@codingame/monaco-vscode-api/vscode/vs/base/common/event';
import type { IStorageDatabase, IUpdateRequest } from '@codingame/monaco-vscode-api/vscode/vs/base/parts/storage/common/storage';
import { call } from './bridge';

export class HostStorage implements IStorageDatabase {
  readonly onDidChangeItemsExternal = Event.None;
  constructor(private key: string) {}

  async getItems(): Promise<Map<string, string>> {
    return new Map(Object.entries(await call<Record<string, string>>('storage.read', { key: this.key })));
  }

  async updateItems(request: IUpdateRequest): Promise<void> {
    await call('storage.update', {
      key: this.key, insert: Object.fromEntries(request.insert ?? []), delete: [...(request.delete ?? [])],
    });
  }

  async optimize(): Promise<void> {}
  async close(): Promise<void> {}
}

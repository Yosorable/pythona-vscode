import {
  FileChangeType,
  FileSystemProviderCapabilities,
  FileSystemProviderError,
  FileSystemProviderErrorCode,
  type FileType,
  type IFileChange,
  type IFileDeleteOptions,
  type IFileOverwriteOptions,
  type IFileSystemProviderWithFileReadWriteCapability,
  type IFileWriteOptions,
  type IStat,
} from '@codingame/monaco-vscode-files-service-override';
import { Emitter, Event } from '@codingame/monaco-vscode-api/vscode/vs/base/common/event';
import { URI } from '@codingame/monaco-vscode-api/vscode/vs/base/common/uri';
import { call, HostError, type Workspace } from './bridge';

export function workspaceURI(workspace: Workspace): URI {
  return URI.file(`/Documents/${workspace.path}`);
}

export class WorkspaceFiles implements IFileSystemProviderWithFileReadWriteCapability {
  readonly capabilities = FileSystemProviderCapabilities.FileReadWrite | FileSystemProviderCapabilities.PathCaseSensitive;
  readonly onDidChangeCapabilities = Event.None;
  private readonly changes = new Emitter<readonly IFileChange[]>();
  readonly onDidChangeFile = this.changes.event;
  private readonly revisions = new Map<string, string>();

  constructor(private workspace: Workspace | null) {}

  private path(uri: URI): string {
    const root = this.workspace && workspaceURI(this.workspace);
    if (!root || uri.scheme !== root.scheme || uri.authority !== root.authority ||
        (uri.path !== root.path && !uri.path.startsWith(root.path + '/'))) {
      throw FileSystemProviderError.create('Open a project folder first.', FileSystemProviderErrorCode.NoPermissions);
    }
    return uri.path.slice(root.path.length + 1);
  }

  private async request<T>(action: string, uri: URI, extra: Record<string, unknown> = {}): Promise<T> {
    try {
      return await call<T>(action, { workspace: this.workspace?.id, path: this.path(uri), ...extra });
    } catch (error) {
      if (error instanceof HostError) {
        const codes = FileSystemProviderErrorCode as Record<string, FileSystemProviderErrorCode>;
        throw FileSystemProviderError.create(error.message, codes[error.code] ?? FileSystemProviderErrorCode.Unknown);
      }
      throw error;
    }
  }

  stat(uri: URI): Promise<IStat> { return this.request('fs.stat', uri); }
  readdir(uri: URI): Promise<[string, FileType][]> { return this.request('fs.list', uri); }
  watch() { return { dispose() {} }; }

  async readFile(uri: URI): Promise<Uint8Array> {
    const result = await this.request<{ data: Uint8Array; revision: string }>('fs.read', uri);
    this.revisions.set(uri.toString(), result.revision);
    return result.data;
  }

  async writeFile(uri: URI, content: Uint8Array, options: IFileWriteOptions): Promise<void> {
    const result = await this.request<{ revision: string }>('fs.write', uri, {
      data: content, create: options.create, overwrite: options.overwrite,
      expected: this.revisions.get(uri.toString()) ?? null,
    });
    this.revisions.set(uri.toString(), result.revision);
    this.changes.fire([{ resource: uri, type: FileChangeType.UPDATED }]);
  }

  async mkdir(uri: URI): Promise<void> {
    await this.request('fs.mkdir', uri);
    this.changes.fire([{ resource: uri, type: FileChangeType.ADDED }]);
  }

  async rename(source: URI, target: URI, options: IFileOverwriteOptions): Promise<void> {
    await this.request('fs.rename', source, { target: this.path(target), overwrite: options.overwrite });
    this.revisions.clear();
    this.changes.fire([
      { resource: source, type: FileChangeType.DELETED },
      { resource: target, type: FileChangeType.ADDED },
    ]);
  }

  async delete(uri: URI, options: IFileDeleteOptions): Promise<void> {
    await this.request('fs.delete', uri, { recursive: options.recursive });
    this.revisions.delete(uri.toString());
    this.changes.fire([{ resource: uri, type: FileChangeType.DELETED }]);
  }
}

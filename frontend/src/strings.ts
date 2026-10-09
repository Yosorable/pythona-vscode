const en = {
  opening: 'Opening Pythona VSCode…',
  failed: 'Unable to open the workbench.',
  preferencesFailed: 'Unable to save workbench settings.',
  themeFailed: 'Unable to load the selected color theme.',
  connectionUnavailable: 'The local workspace connection is unavailable.',
  openFolder: 'Open Folder…',
  folderTitle: 'Open Folder',
  openThis: 'Open This Folder',
  parentFolder: 'Parent Folder',
  recent: 'Recently opened',
  chooseProject: 'Choose a project folder in Documents',
  newFolder: 'New Folder…',
  folderName: 'Folder name',
  invalidName: 'Enter a visible folder name without a slash.',
  closeFolder: 'Close Folder',
  closeWindow: 'Close Window',
  localWorkspace: 'Local workspace',
  saveChanges: 'Save your changes before leaving this workspace?',
  saveAll: 'Save All',
  discard: "Don't Save",
  closed: 'Workspace closed. You can close this window.',
} as const;

type Strings = { [K in keyof typeof en]: string };
const hans: Strings = {
  opening: '正在打开 Pythona VSCode…', failed: '无法打开工作台。',
  preferencesFailed: '无法保存工作台设置。',
  themeFailed: '无法加载所选颜色主题。',
  connectionUnavailable: '本地工作区连接不可用。',
  openFolder: '打开文件夹…', folderTitle: '打开文件夹', openThis: '打开此文件夹',
  parentFolder: '上级文件夹', recent: '最近打开', chooseProject: '选择 Documents 中的项目文件夹',
  newFolder: '新建文件夹…', folderName: '文件夹名称', invalidName: '输入不以点开头且不包含斜杠的文件夹名称。',
  closeFolder: '关闭文件夹', closeWindow: '关闭窗口', localWorkspace: '本地工作区',
  saveChanges: '离开此工作区前是否保存更改？', saveAll: '全部保存', discard: '不保存',
  closed: '工作区已关闭。可以关闭此窗口。',
};
const hant: Strings = {
  opening: '正在開啟 Pythona VSCode…', failed: '無法開啟工作台。',
  preferencesFailed: '無法儲存工作台設定。',
  themeFailed: '無法載入選取的色彩佈景主題。',
  connectionUnavailable: '本機工作區連線無法使用。',
  openFolder: '開啟資料夾…', folderTitle: '開啟資料夾', openThis: '開啟此資料夾',
  parentFolder: '上層資料夾', recent: '最近開啟', chooseProject: '選取 Documents 中的專案資料夾',
  newFolder: '新增資料夾…', folderName: '資料夾名稱', invalidName: '輸入不以點開頭且不包含斜線的資料夾名稱。',
  closeFolder: '關閉資料夾', closeWindow: '關閉視窗', localWorkspace: '本機工作區',
  saveChanges: '離開此工作區前是否儲存變更？', saveAll: '全部儲存', discard: '不要儲存',
  closed: '工作區已關閉。可以關閉此視窗。',
};

let strings: Strings = en;
export function languageCode(language: string): 'en' | 'zh-Hans' | 'zh-Hant' {
  if (/^zh-(Hant|TW|HK|MO)/i.test(language)) return 'zh-Hant';
  return /^zh/i.test(language) ? 'zh-Hans' : 'en';
}
export function setLanguage(language: string): void {
  strings = { en, 'zh-Hans': hans, 'zh-Hant': hant }[languageCode(language)];
}
export function t(key: keyof Strings): string { return strings[key]; }

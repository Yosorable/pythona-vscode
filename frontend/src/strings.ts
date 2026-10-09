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

const de: Strings = {
  opening: 'Pythona VSCode wird geöffnet…',
  failed: 'Die Workbench konnte nicht geöffnet werden.',
  preferencesFailed: 'Die Workbench-Einstellungen konnten nicht gespeichert werden.',
  themeFailed: 'Das ausgewählte Farbdesign konnte nicht geladen werden.',
  connectionUnavailable: 'Die Verbindung zum lokalen Arbeitsbereich ist nicht verfügbar.',
  openFolder: 'Ordner öffnen…',
  folderTitle: 'Ordner öffnen',
  openThis: 'Diesen Ordner öffnen',
  parentFolder: 'Übergeordneter Ordner',
  recent: 'Zuletzt geöffnet',
  chooseProject: 'Projektordner in Documents auswählen',
  newFolder: 'Neuer Ordner…',
  folderName: 'Ordnername',
  invalidName: 'Gib einen Ordnernamen ohne führenden Punkt und ohne Schrägstrich ein.',
  closeFolder: 'Ordner schließen',
  closeWindow: 'Fenster schließen',
  localWorkspace: 'Lokaler Arbeitsbereich',
  saveChanges: 'Änderungen vor dem Verlassen dieses Arbeitsbereichs speichern?',
  saveAll: 'Alle speichern',
  discard: 'Nicht speichern',
  closed: 'Der Arbeitsbereich wurde geschlossen. Du kannst dieses Fenster schließen.',
};

const fr: Strings = {
  opening: 'Ouverture de Pythona VSCode…',
  failed: 'Impossible d’ouvrir le banc d’essai.',
  preferencesFailed: 'Impossible d’enregistrer les paramètres du banc d’essai.',
  themeFailed: 'Impossible de charger le thème de couleur sélectionné.',
  connectionUnavailable: 'La connexion à l’espace de travail local est indisponible.',
  openFolder: 'Ouvrir un dossier…',
  folderTitle: 'Ouvrir un dossier',
  openThis: 'Ouvrir ce dossier',
  parentFolder: 'Dossier parent',
  recent: 'Ouverts récemment',
  chooseProject: 'Choisissez un dossier de projet dans Documents',
  newFolder: 'Nouveau dossier…',
  folderName: 'Nom du dossier',
  invalidName: 'Indiquez un nom de dossier qui ne commence pas par un point et ne contient pas de barre oblique.',
  closeFolder: 'Fermer le dossier',
  closeWindow: 'Fermer la fenêtre',
  localWorkspace: 'Espace de travail local',
  saveChanges: 'Enregistrer les modifications avant de quitter cet espace de travail ?',
  saveAll: 'Tout enregistrer',
  discard: 'Ne pas enregistrer',
  closed: 'L’espace de travail est fermé. Vous pouvez fermer cette fenêtre.',
};

const es: Strings = {
  opening: 'Abriendo Pythona VSCode…',
  failed: 'No se pudo abrir el Workbench.',
  preferencesFailed: 'No se pudo guardar la configuración del Workbench.',
  themeFailed: 'No se pudo cargar el tema de color seleccionado.',
  connectionUnavailable: 'La conexión al área de trabajo local no está disponible.',
  openFolder: 'Abrir carpeta…',
  folderTitle: 'Abrir carpeta',
  openThis: 'Abrir esta carpeta',
  parentFolder: 'Carpeta superior',
  recent: 'Abiertos recientemente',
  chooseProject: 'Elige una carpeta de proyecto en Documents',
  newFolder: 'Nueva carpeta…',
  folderName: 'Nombre de la carpeta',
  invalidName: 'Introduce un nombre de carpeta que no empiece por un punto ni contenga barras.',
  closeFolder: 'Cerrar carpeta',
  closeWindow: 'Cerrar ventana',
  localWorkspace: 'Área de trabajo local',
  saveChanges: '¿Quieres guardar los cambios antes de salir de esta área de trabajo?',
  saveAll: 'Guardar todo',
  discard: 'No guardar',
  closed: 'El área de trabajo está cerrada. Puedes cerrar esta ventana.',
};

const ru: Strings = {
  opening: 'Открытие Pythona VSCode…',
  failed: 'Не удалось открыть рабочее место.',
  preferencesFailed: 'Не удалось сохранить параметры рабочего места.',
  themeFailed: 'Не удалось загрузить выбранную цветовую тему.',
  connectionUnavailable: 'Подключение к локальной рабочей области недоступно.',
  openFolder: 'Открыть папку…',
  folderTitle: 'Открыть папку',
  openThis: 'Открыть эту папку',
  parentFolder: 'Родительская папка',
  recent: 'Недавно открытые',
  chooseProject: 'Выберите папку проекта в Documents',
  newFolder: 'Создать папку…',
  folderName: 'Имя папки',
  invalidName: 'Введите имя папки без косой черты и точки в начале.',
  closeFolder: 'Закрыть папку',
  closeWindow: 'Закрыть окно',
  localWorkspace: 'Локальная рабочая область',
  saveChanges: 'Сохранить изменения перед выходом из этой рабочей области?',
  saveAll: 'Сохранить все',
  discard: 'Не сохранять',
  closed: 'Рабочая область закрыта. Это окно можно закрыть.',
};

const ja: Strings = {
  opening: 'Pythona VSCode を開いています…',
  failed: 'ワークベンチを開けませんでした。',
  preferencesFailed: 'ワークベンチの設定を保存できませんでした。',
  themeFailed: '選択した配色テーマを読み込めませんでした。',
  connectionUnavailable: 'ローカル ワークスペースに接続できません。',
  openFolder: 'フォルダーを開く…',
  folderTitle: 'フォルダーを開く',
  openThis: 'このフォルダーを開く',
  parentFolder: '親フォルダー',
  recent: '最近開いた項目',
  chooseProject: 'Documents 内のプロジェクトフォルダーを選択',
  newFolder: '新しいフォルダー…',
  folderName: 'フォルダー名',
  invalidName: '先頭にピリオドを付けず、スラッシュを含まないフォルダー名を入力してください。',
  closeFolder: 'フォルダーを閉じる',
  closeWindow: 'ウィンドウを閉じる',
  localWorkspace: 'ローカル ワークスペース',
  saveChanges: 'このワークスペースを離れる前に変更を保存しますか？',
  saveAll: 'すべて保存',
  discard: '保存しない',
  closed: 'ワークスペースを閉じました。このウィンドウを閉じることができます。',
};

const ko: Strings = {
  opening: 'Pythona VSCode 여는 중…',
  failed: '워크벤치를 열 수 없습니다.',
  preferencesFailed: '워크벤치 설정을 저장할 수 없습니다.',
  themeFailed: '선택한 색 테마를 불러올 수 없습니다.',
  connectionUnavailable: '로컬 작업 영역에 연결할 수 없습니다.',
  openFolder: '폴더 열기…',
  folderTitle: '폴더 열기',
  openThis: '이 폴더 열기',
  parentFolder: '상위 폴더',
  recent: '최근에 연 항목',
  chooseProject: 'Documents에서 프로젝트 폴더 선택',
  newFolder: '새 폴더…',
  folderName: '폴더 이름',
  invalidName: '점으로 시작하지 않고 슬래시가 없는 폴더 이름을 입력하세요.',
  closeFolder: '폴더 닫기',
  closeWindow: '창 닫기',
  localWorkspace: '로컬 작업 영역',
  saveChanges: '이 작업 영역을 나가기 전에 변경 내용을 저장하시겠습니까?',
  saveAll: '모두 저장',
  discard: '저장 안 함',
  closed: '작업 영역이 닫혔습니다. 이 창을 닫아도 됩니다.',
};

const ptBR: Strings = {
  opening: 'Abrindo Pythona VSCode…',
  failed: 'Não foi possível abrir o Workbench.',
  preferencesFailed: 'Não foi possível salvar as configurações do Workbench.',
  themeFailed: 'Não foi possível carregar o tema de cores selecionado.',
  connectionUnavailable: 'A conexão com o workspace local não está disponível.',
  openFolder: 'Abrir Pasta…',
  folderTitle: 'Abrir Pasta',
  openThis: 'Abrir Esta Pasta',
  parentFolder: 'Pasta Superior',
  recent: 'Abertos Recentemente',
  chooseProject: 'Escolha uma pasta de projeto em Documents',
  newFolder: 'Nova Pasta…',
  folderName: 'Nome da pasta',
  invalidName: 'Insira um nome de pasta que não comece com ponto nem contenha barras.',
  closeFolder: 'Fechar Pasta',
  closeWindow: 'Fechar Janela',
  localWorkspace: 'Workspace local',
  saveChanges: 'Deseja salvar as alterações antes de sair deste workspace?',
  saveAll: 'Salvar Tudo',
  discard: 'Não Salvar',
  closed: 'O workspace foi fechado. Você pode fechar esta janela.',
};

const translations = { en, de, es, fr, ja, ko, 'pt-BR': ptBR, ru, 'zh-Hans': hans, 'zh-Hant': hant };
export type LanguageCode = keyof typeof translations;

let strings: Strings = en;
export function languageCode(language: string): LanguageCode {
  const normalized = language.trim().replaceAll('_', '-').toLowerCase();
  if (/^zh-(hant|tw|hk|mo)(?:-|$)/.test(normalized)) return 'zh-Hant';
  if (/^zh(?:-|$)/.test(normalized)) return 'zh-Hans';
  const base = normalized.split('-')[0];
  if (base === 'pt') return 'pt-BR';
  return Object.hasOwn(translations, base) ? base as LanguageCode : 'en';
}
export function setLanguage(language: string): void {
  strings = translations[languageCode(language)];
}
export function t(key: keyof Strings): string { return strings[key]; }

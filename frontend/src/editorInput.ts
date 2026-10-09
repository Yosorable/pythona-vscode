type Tap = {
  pointerID: number;
  field: HTMLTextAreaElement;
  x: number;
  y: number;
  time: number;
  generation: number;
};

type Activation = { id: string; field: HTMLTextAreaElement; previousFocus: Element | null; time: number };

export function installEditorInput(): (id: string) => void {
  const handler = window.webkit?.messageHandlers?.workbenchInput;
  if (!handler) return () => {};

  const pageID = crypto.randomUUID();
  let generation = 0;
  let pointer: Tap | undefined;
  let pending: Activation | undefined;
  let composing = false;

  function cancel(): void {
    generation++;
    pointer = pending = undefined;
  }

  function fieldAt(target: EventTarget | null): HTMLTextAreaElement | undefined {
    if (!(target instanceof Element)
        || target.closest('a,button,input,select,.iPadShowKeyboard,[role="button"]')
        || !target.closest('.view-lines,.view-overlays,.cursors-layer,textarea.inputarea')) return;
    const field = target.closest('.monaco-editor')?.querySelector('textarea.inputarea');
    if (field instanceof HTMLTextAreaElement && !field.readOnly && !field.disabled) return field;
  }

  document.addEventListener('compositionstart', () => { composing = true; cancel(); }, true);
  document.addEventListener('compositionend', () => { composing = false; }, true);
  window.addEventListener('pagehide', cancel);
  window.addEventListener('blur', cancel);
  document.addEventListener('pointerdown', event => {
    cancel();
    if (!event.isTrusted || !event.isPrimary || event.button !== 0 || composing) return;
    const field = fieldAt(event.target);
    if (field) pointer = {
      pointerID: event.pointerId, field, x: event.clientX, y: event.clientY,
      time: performance.now(), generation,
    };
  }, true);
  document.addEventListener('pointermove', event => {
    if (pointer?.pointerID === event.pointerId
        && Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) > 10) pointer = undefined;
  }, true);
  document.addEventListener('pointercancel', cancel, true);
  document.addEventListener('pointerup', event => {
    const tap = pointer;
    pointer = undefined;
    if (!tap || event.pointerId !== tap.pointerID || !event.isTrusted
        || performance.now() - tap.time > 500) return;
    // Let Monaco apply the tapped position before starting WebKit's input session.
    setTimeout(() => {
      if (generation !== tap.generation || composing || !tap.field.isConnected) return;
      const id = `${pageID}:${tap.generation}`;
      pending = { id, field: tap.field, previousFocus: document.activeElement, time: performance.now() };
      handler.postMessage(id);
    }, 0);
  }, true);

  return id => {
    if (!pending || pending.id !== id) return;
    const { field, previousFocus, time } = pending;
    pending = undefined;
    if (!field.isConnected || field.readOnly || field.disabled || composing
        || performance.now() - time > 1000) return;
    const active = document.activeElement;
    if (active !== field && active !== previousFocus
        && (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement)) return;
    // Native code has made this web view a responder. Focus the tapped editor,
    // which may differ from the current DOM focus or another split editor.
    field.focus({ preventScroll: true });
  };
}

// Shared helpers: translations, DOM building, API calls, clipboard, dialogs.

const i18nData = JSON.parse(document.getElementById('i18n-data')?.textContent || '{}');
export const LANG = i18nData.lang || 'en';
export const DIR = i18nData.dir || 'ltr';
const STRINGS = i18nData.strings || {};
const LABEL_WORDS = i18nData.labelWords || {};
const UPPER_WORDS = i18nData.upperWords || {};
const numberFormat = new Intl.NumberFormat(LANG === 'fa' ? 'fa-IR' : 'en-US');

/** Translate a key, replacing {name} placeholders that have a matching param. */
export function t(key, params = {}) {
  const text = STRINGS[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
}

/** Plural-aware translation: tn('inputs', 2) -> "2 inputs". */
export function tn(base, n, params = {}) {
  return t(`${base}_${n === 1 ? 'one' : 'other'}`, { n: fmtNum(n), ...params });
}

export const fmtNum = (n) => numberFormat.format(n);

/** Readable default label for an input name — mirrors i18n.auto_label on the server. */
export function autoLabel(name) {
  const words = name.replace(/([a-z0-9])([A-Z])/g, '$1_$2').split(/[_-]+/).filter(Boolean);
  if (!words.length) return name;
  const ascii = /^[A-Za-z0-9_]+$/.test(name);
  if (LANG === 'fa' && ascii) {
    const lower = words.map((w) => w.toLowerCase());
    if (lower.every((w) => Object.hasOwn(LABEL_WORDS, w))) return lower.reverse().map((w) => LABEL_WORDS[w]).join(' ');
  }
  if (!ascii) return words.join(' ');
  const pretty = words.map((w) => UPPER_WORDS[w.toLowerCase()] || w.toLowerCase());
  if (!Object.values(UPPER_WORDS).includes(pretty[0])) pretty[0] = pretty[0][0].toUpperCase() + pretty[0].slice(1);
  return pretty.join(' ');
}

/* ------------------------------------------------------------------ DOM */

const SVG_NS = 'http://www.w3.org/2000/svg';

export function icon(name, cls = '') {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', `icon ${cls}`.trim());
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

/**
 * Tiny element builder. Strings become text nodes (never HTML), so user content is always escaped.
 *   h('button', { class: 'btn', type: 'button', onclick: fn }, icon('copy'), 'Copy')
 */
export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key === 'value') node.value = value;
    else if (key === 'checked') node.checked = Boolean(value);
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

let uid = 0;
export const nextId = (prefix = 'id') => `${prefix}-${++uid}`;

/** Show (or clear) an inline error inside a .field container. */
export function setFieldError(container, messages) {
  if (!container) return;
  const list = (Array.isArray(messages) ? messages : [messages]).filter(Boolean);
  let error = container.querySelector(':scope > .field-error');
  if (!error) {
    error = h('p', { class: 'field-error' });
    container.append(error);
  }
  if (!error.id) error.id = nextId('err');
  const controls = container.querySelectorAll(':scope input:not([type=hidden]), :scope textarea, :scope select');
  error.replaceChildren();
  if (list.length) {
    error.append(icon('alert'), h('span', { class: 'field-error__lines' }, list.map((m) => h('span', {}, m))));
    error.hidden = false;
  } else {
    error.hidden = true;
  }
  controls.forEach((control) => {
    if (control.closest('.field') !== container && control.closest('fieldset') !== container) return;
    const describedBy = new Set((control.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
    if (list.length) {
      control.setAttribute('aria-invalid', 'true');
      describedBy.add(error.id);
    } else {
      control.removeAttribute('aria-invalid');
      describedBy.delete(error.id);
    }
    if (describedBy.size) control.setAttribute('aria-describedby', [...describedBy].join(' '));
    else control.removeAttribute('aria-describedby');
  });
}

/* ------------------------------------------------------------------ search */

const FOLD = { 'ي': 'ی', 'ى': 'ی', 'ك': 'ک', '‌': ' ' };

/** Same normalization as the server: case-insensitive, Arabic/Persian letter variants unified. */
export function normalizeSearch(text) {
  return String(text || '')
    .replace(/[يىك‌]/g, (c) => FOLD[c])
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(' ');
}

/* ------------------------------------------------------------------ API */

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'network', fields = [] } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

/** JSON fetch wrapper. Resolves with parsed JSON (or null), rejects with ApiError. */
export async function api(method, url, body, { signal } = {}) {
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      signal,
    });
  } catch (error) {
    if (error?.name === 'AbortError') throw new ApiError('', { code: 'aborted' });
    throw new ApiError(t('network_error'));
  }
  if (response.status === 204) return null;
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const err = data?.error || {};
    throw new ApiError(err.message || t('err_server_error'), {
      status: response.status,
      code: err.code || 'server_error',
      fields: err.fields || [],
    });
  }
  return data;
}

/* ------------------------------------------------------------------ clipboard */

function legacyCopy(text) {
  const host = document.querySelector('dialog[open]') || document.body;
  const active = document.activeElement;
  const area = h('textarea', { readonly: true, 'aria-hidden': 'true', tabindex: '-1' });
  area.value = text;
  Object.assign(area.style, { position: 'fixed', top: '0', left: '0', width: '1px', height: '1px', opacity: '0' });
  host.append(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  area.remove();
  if (active instanceof HTMLElement) active.focus({ preventScroll: true });
  return ok;
}

/**
 * Copy text to the clipboard. Resolves true only once the browser confirms the copy.
 * Uses the async Clipboard API, falling back to execCommand('copy').
 */
export async function copyText(text) {
  if (!text) return false;
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      /* fall through to the legacy path */
    }
  }
  return legacyCopy(text);
}

/** Select an element's text so the user can copy it by hand. */
export function selectContents(element) {
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.selectNodeContents(element);
  selection.removeAllRanges();
  selection.addRange(range);
  element.focus?.({ preventScroll: false });
}

/* ------------------------------------------------------------------ dialogs */

/**
 * Wire a native <dialog> with focus restore, backdrop click and close callbacks.
 * Returns { open(trigger), close(), isOpen() }.
 */
export function setupDialog(dialog, { onClose, initialFocus } = {}) {
  let returnFocus = null;
  let pressedOnBackdrop = false;

  dialog.addEventListener('mousedown', (event) => {
    pressedOnBackdrop = event.target === dialog;
  });
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog && pressedOnBackdrop) dialog.close('cancel');
    pressedOnBackdrop = false;
  });
  dialog.querySelectorAll('[data-close]').forEach((button) => {
    button.addEventListener('click', () => dialog.close('cancel'));
  });
  dialog.addEventListener('close', () => {
    // The close event arrives asynchronously; ignore it if the dialog was already reopened.
    if (dialog.open) return;
    // Keep any visible toasts on screen after the dialog disappears.
    const modalRegion = dialog.querySelector('.toast-region--modal');
    const pageRegion = document.getElementById('toast-region');
    if (modalRegion && pageRegion) pageRegion.append(...modalRegion.children);
    onClose?.(dialog.returnValue);
    if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
    returnFocus = null;
  });

  return {
    open(trigger = document.activeElement) {
      returnFocus = trigger instanceof HTMLElement ? trigger : null;
      dialog.returnValue = '';
      if (!dialog.open) dialog.showModal();
      const target = typeof initialFocus === 'function' ? initialFocus() : null;
      (target || dialog.querySelector('[autofocus]') || dialog.querySelector('.modal__close'))?.focus();
    },
    close(value = 'cancel') {
      if (dialog.open) dialog.close(value);
    },
    isOpen: () => dialog.open,
  };
}

let confirmApi = null;

/** Promise-based confirmation dialog. Resolves true when the user confirms. */
export function confirmDialog({ title, body, confirmText, cancelText = t('cancel'), danger = true }) {
  const dialog = document.getElementById('confirm-dialog');
  const confirmBtn = dialog.querySelector('[data-confirm]');
  const cancelBtn = dialog.querySelector('[data-cancel]');
  if (!confirmApi) {
    confirmApi = setupDialog(dialog, { initialFocus: () => cancelBtn });
    confirmBtn.addEventListener('click', () => dialog.close('confirm'));
    cancelBtn.addEventListener('click', () => dialog.close('cancel'));
  }
  dialog.querySelector('#confirm-title').textContent = title;
  dialog.querySelector('#confirm-body').textContent = body;
  confirmBtn.textContent = confirmText;
  confirmBtn.className = `btn ${danger ? 'btn-danger' : 'btn-primary'}`;
  cancelBtn.textContent = cancelText;

  return new Promise((resolve) => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true });
    confirmApi.open();
  });
}

/* ------------------------------------------------------------------ cross-page flash */

const FLASH_KEY = 'idc:flash';

export function setFlash(value) {
  try {
    sessionStorage.setItem(FLASH_KEY, JSON.stringify(value));
  } catch {
    /* storage unavailable: the toast is simply skipped */
  }
}

export function takeFlash() {
  try {
    const raw = sessionStorage.getItem(FLASH_KEY);
    sessionStorage.removeItem(FLASH_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/** True when the user is typing in a field (so global shortcuts should stay quiet). */
export function isTypingTarget(target) {
  return target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
}

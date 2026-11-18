// Small, non-blocking toast notifications.
import { h, icon, t } from './app.js';

const MAX_TOASTS = 3;
const DURATION = { success: 2600, info: 3500, error: 6500 };

function regionFor() {
  // While a modal dialog is open everything else is inert, so toasts go inside the dialog.
  const openDialog = document.querySelector('dialog[open]');
  return openDialog?.querySelector('.toast-region--modal') || document.getElementById('toast-region');
}

function dismiss(node) {
  if (!node.isConnected || node.classList.contains('is-leaving')) return;
  clearTimeout(node._timer);
  node.classList.add('is-leaving');
  const remove = () => node.remove();
  node.addEventListener('animationend', remove, { once: true });
  setTimeout(remove, 400);
}

function show(type, message, duration = DURATION[type]) {
  const region = regionFor();
  if (!region) return null;
  const iconName = type === 'success' ? 'check' : type === 'error' ? 'alert' : 'info';
  const node = h(
    'div',
    { class: `toast toast--${type}`, role: type === 'error' ? 'alert' : 'status' },
    h('span', { class: 'toast__icon' }, icon(iconName)),
    h('span', { class: 'toast__msg' }, message),
    h('button', { type: 'button', class: 'toast__close', 'aria-label': t('dismiss'), onclick: () => dismiss(node) }, icon('x')),
  );

  const start = () => {
    clearTimeout(node._timer);
    node._timer = setTimeout(() => dismiss(node), duration);
  };
  node.addEventListener('mouseenter', () => clearTimeout(node._timer));
  node.addEventListener('mouseleave', start);
  node.addEventListener('focusin', () => clearTimeout(node._timer));
  node.addEventListener('focusout', start);

  region.append(node);
  const live = [...region.querySelectorAll('.toast:not(.is-leaving)')];
  live.slice(0, Math.max(0, live.length - MAX_TOASTS)).forEach(dismiss);
  start();
  return node;
}

export const toast = {
  success: (message) => show('success', message),
  error: (message) => show('error', message),
  info: (message) => show('info', message),
};

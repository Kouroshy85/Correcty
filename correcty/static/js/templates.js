// Manage Templates page: search, pin/unpin, delete, use.
import { api, confirmDialog, fmtNum, isTypingTarget, normalizeSearch, t, takeFlash, tn } from './app.js';
import { generator } from './generator.js';
import { toast } from './notifications.js';

const list = document.getElementById('tpl-list');
const search = document.getElementById('tpl-search');
const countEl = document.getElementById('tpl-count');
const card = document.getElementById('tpl-card');
const toolbar = document.getElementById('tpl-toolbar');
const emptyState = document.getElementById('tpl-empty');
const noResults = document.getElementById('tpl-noresults');
const noResultsTitle = document.getElementById('tpl-noresults-title');

const rows = () => [...list.querySelectorAll('.tpl-row')];

function applySearch() {
  const all = rows();
  const total = all.length;
  const raw = search.value.trim();
  const query = normalizeSearch(raw);
  let shown = 0;
  for (const row of all) {
    const match = !query || row.dataset.search.includes(query);
    row.hidden = !match;
    if (match) shown += 1;
  }
  countEl.textContent = query ? t('count_filtered', { shown: fmtNum(shown), total: fmtNum(total) }) : tn('count', total);
  toolbar.hidden = total === 0;
  emptyState.hidden = total !== 0;
  card.hidden = total === 0 || shown === 0;
  noResults.hidden = !(total > 0 && shown === 0);
  noResultsTitle.textContent = t('no_results_title', { q: raw });
}

search.addEventListener('input', applySearch);
search.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && search.value) {
    event.stopPropagation();
    search.value = '';
    applySearch();
  }
});
document.getElementById('tpl-clear-search').addEventListener('click', () => {
  search.value = '';
  applySearch();
  search.focus();
});
document.addEventListener('keydown', (event) => {
  if (event.key === '/' && !isTypingTarget(event.target) && !document.querySelector('dialog[open]')) {
    event.preventDefault();
    search.focus();
  }
});

function removeRow(row) {
  const next = row.nextElementSibling || row.previousElementSibling;
  row.remove();
  applySearch();
  (next?.querySelector('.tpl-row__title') || search).focus({ preventScroll: true });
}

async function togglePin(row, button) {
  const pinned = button.getAttribute('aria-pressed') !== 'true';
  button.disabled = true;
  try {
    await api('PATCH', `/api/templates/${row.dataset.id}/pin`, { pinned });
    button.setAttribute('aria-pressed', String(pinned));
    button.title = pinned ? t('unpin') : t('pin');
    row.classList.toggle('is-pinned', pinned);
    row.querySelector('[data-pin-badge]').hidden = !pinned;
    toast.success(pinned ? t('toast_pinned') : t('toast_unpinned'));
  } catch (error) {
    toast.error(error.message);
    if (error.status === 404) removeRow(row);
  } finally {
    button.disabled = false;
  }
}

async function deleteTemplate(row) {
  const confirmed = await confirmDialog({
    title: t('delete_title', { title: row.dataset.title }),
    body: t('delete_body'),
    confirmText: t('delete'),
  });
  if (!confirmed) return;
  row.classList.add('is-busy');
  try {
    await api('DELETE', `/api/templates/${row.dataset.id}`);
    removeRow(row);
    toast.success(t('toast_deleted'));
  } catch (error) {
    row.classList.remove('is-busy');
    if (error.status === 404) {
      removeRow(row);
      toast.info(error.message);
    } else {
      toast.error(error.message);
    }
  }
}

list.addEventListener('click', (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const row = button.closest('.tpl-row');
  const action = button.dataset.action;
  if (action === 'use') generator.open({ kind: 'saved', id: Number(row.dataset.id), title: row.dataset.title }, button);
  else if (action === 'pin') togglePin(row, button);
  else if (action === 'delete') deleteTemplate(row);
});

applySearch();

const flash = takeFlash();
if (flash?.message) toast.success(flash.message);
if (flash?.id) {
  const row = list.querySelector(`.tpl-row[data-id="${Number(flash.id)}"]`);
  if (row) {
    row.scrollIntoView({ block: 'nearest' });
    row.classList.add('is-flash');
    row.addEventListener('animationend', () => row.classList.remove('is-flash'), { once: true });
  }
}

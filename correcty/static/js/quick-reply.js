// Quick Reply page: draft box, Polish Text (local AI), polished output, pinned templates.
import { api, copyText, isTypingTarget, normalizeSearch, selectContents, t, tn } from './app.js';
import { generator } from './generator.js';
import { toast } from './notifications.js';

const draft = document.getElementById('draft');
const count = document.getElementById('draft-count');
const clearBtn = document.getElementById('clear-draft');
const polishBtn = document.getElementById('polish-btn');
const polishBtnText = document.getElementById('polish-btn-text');
const polishCancel = document.getElementById('polish-cancel');
const polishNote = document.getElementById('polish-note');
const polished = document.getElementById('polished-text');
const polishedBox = polished.closest('.output');
const copyPolished = document.getElementById('copy-polished');
let polishing = null; // AbortController while a request is running

function updateDraft() {
  const length = [...draft.value].length;
  count.textContent = tn('chars', length);
  clearBtn.disabled = length === 0;
  polishBtn.disabled = length === 0 || Boolean(polishing);
}
draft.addEventListener('input', updateDraft);
clearBtn.addEventListener('click', () => {
  draft.value = '';
  updateDraft();
  draft.focus();
});
updateDraft();

function setPolished(text) {
  polished.textContent = text;
  polishedBox.classList.toggle('is-empty', !text);
  polishedBox.classList.toggle('is-ready', Boolean(text));
  copyPolished.disabled = !text;
}

function setPolishing(busy) {
  polishBtn.classList.toggle('is-busy', busy);
  polishBtnText.textContent = busy ? t('polishing') : t('polish');
  polishCancel.hidden = !busy;
  polishNote.textContent = busy ? t('polish_wait') : t('polish_shortcut');
  polishedBox.setAttribute('aria-busy', String(busy));
  updateDraft();
}

async function polishText() {
  const text = draft.value.trim();
  if (!text || polishing) return;
  polishing = new AbortController();
  setPolishing(true);
  try {
    const result = await api('POST', '/api/polish', { text }, { signal: polishing.signal });
    setPolished(result.text);
    toast.success(t('toast_polished'));
  } catch (error) {
    if (error.code !== 'aborted') toast.error(error.message);
  } finally {
    polishing = null;
    setPolishing(false);
  }
}

polishBtn.addEventListener('click', polishText);
polishCancel.addEventListener('click', () => polishing?.abort());
draft.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    polishText();
  }
});

// Polished output: copied with the same path as generated messages.
document.getElementById('copy-polished').addEventListener('click', async () => {
  const text = polished.textContent.trim();
  if (!text) {
    toast.info(t('nothing_to_copy'));
    return;
  }
  if (await copyText(text)) {
    toast.success(t('copied'));
  } else {
    selectContents(polished);
    toast.error(t('copy_failed'));
  }
});

// Pinned replies
const grid = document.getElementById('pinned-grid');
grid?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-template-id]');
  if (!button) return;
  generator.open({ kind: 'saved', id: Number(button.dataset.templateId), title: button.textContent.trim() }, button);
});

const filter = document.getElementById('pinned-filter');
if (filter && grid) {
  const items = [...grid.children];
  const noResults = document.getElementById('pinned-noresults');
  const apply = () => {
    const query = normalizeSearch(filter.value);
    let shown = 0;
    for (const item of items) {
      const match = !query || item.dataset.search.includes(query);
      item.hidden = !match;
      if (match) shown += 1;
    }
    noResults.textContent = t('filter_no_results', { q: filter.value.trim() });
    noResults.hidden = shown > 0;
  };
  filter.addEventListener('input', apply);
  filter.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      items.find((item) => !item.hidden)?.querySelector('button')?.click();
    } else if (event.key === 'Escape' && filter.value) {
      event.stopPropagation();
      filter.value = '';
      apply();
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === '/' && !isTypingTarget(event.target) && !document.querySelector('dialog[open]')) {
      event.preventDefault();
      filter.focus();
    }
  });
}

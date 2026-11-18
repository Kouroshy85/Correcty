// Settings: Polish prompts (create, edit, activate, delete) and the local AI model connection.
import { api, confirmDialog, h, icon, nextId, setFieldError, t } from './app.js';
import { toast } from './notifications.js';

const data = JSON.parse(document.getElementById('settings-data').textContent);

/* ------------------------------------------------------------------ tabs */

const tabs = [...document.querySelectorAll('[role="tab"]')];

function selectTab(tab, focus = false) {
  for (const other of tabs) {
    const selected = other === tab;
    other.setAttribute('aria-selected', String(selected));
    other.tabIndex = selected ? 0 : -1;
    document.getElementById(other.getAttribute('aria-controls')).hidden = !selected;
  }
  if (focus) tab.focus();
  try {
    history.replaceState(null, '', `?tab=${tab.dataset.tab}`);
  } catch {
    /* ignore */
  }
  if (tab.dataset.tab === 'ai') refreshStatus();
}

tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectTab(tab));
  tab.addEventListener('keydown', (event) => {
    const step = { ArrowRight: 1, ArrowLeft: -1, Home: -index, End: tabs.length - 1 - index }[event.key];
    if (step === undefined) return;
    event.preventDefault();
    const rtl = document.documentElement.dir === 'rtl' && (event.key === 'ArrowRight' || event.key === 'ArrowLeft');
    selectTab(tabs[(index + (rtl ? -step : step) + tabs.length) % tabs.length], true);
  });
});

/* ------------------------------------------------------------------ prompts */

const list = document.getElementById('prompt-list');
const empty = document.getElementById('prompts-empty');
const noActive = document.getElementById('no-active');
let prompts = data.prompts.map((p) => ({ ...p, draft: false }));

const isDirty = (card) =>
  card.dataset.draft === 'true' ||
  card.querySelector('[data-input="name"]').value !== card._saved.name ||
  card.querySelector('[data-input="prompt"]').value !== card._saved.prompt;

function refreshMeta() {
  const cards = [...list.children];
  empty.hidden = cards.length > 0;
  noActive.hidden = cards.length === 0 || prompts.some((p) => p.active);
  for (const card of cards) {
    const prompt = prompts.find((p) => String(p.id) === card.dataset.id);
    const active = Boolean(prompt?.active);
    card.classList.toggle('is-active', active);
    card.querySelector('[data-role="active-badge"]').hidden = !active;
    card.querySelector('[data-act="activate"]').hidden = active;
    card.querySelector('[data-role="dirty"]').hidden = !isDirty(card);
  }
}

function buildCard(prompt) {
  const nameId = nextId('prompt-name');
  const textId = nextId('prompt-text');
  const card = h(
    'li',
    { class: 'card prompt-card', dataset: { id: prompt.id ?? '', draft: String(prompt.draft) } },
    h(
      'div',
      { class: 'prompt-card__head' },
      h('span', { class: 'badge badge--pin', dataset: { role: 'active-badge' }, hidden: true }, icon('check'), t('active')),
      h('button', { type: 'button', class: 'btn btn-secondary btn-sm', dataset: { act: 'activate' } }, icon('bolt'), h('span', {}, t('activate'))),
      h('span', { class: 'prompt-card__dirty', dataset: { role: 'dirty' }, hidden: true }, t('unsaved')),
      h(
        'button',
        { type: 'button', class: 'btn-icon btn-icon--danger', dataset: { act: 'delete' }, 'aria-label': t('delete'), title: t('delete') },
        icon('trash'),
      ),
    ),
    h(
      'div',
      { class: 'field', dataset: { field: 'name' } },
      h('label', { class: 'label', for: nameId }, t('prompt_name')),
      h('input', { class: 'input', id: nameId, value: prompt.name, placeholder: t('prompt_name_ph'), maxlength: 80, dir: 'auto', dataset: { input: 'name' } }),
    ),
    h(
      'div',
      { class: 'field', dataset: { field: 'prompt' } },
      h('label', { class: 'label', for: textId }, t('prompt_text')),
      h('textarea', { class: 'textarea', id: textId, rows: 5, value: prompt.prompt, placeholder: t('prompt_text_ph'), maxlength: 4000, dir: 'auto', dataset: { input: 'prompt' } }),
    ),
    h(
      'div',
      { class: 'prompt-card__foot' },
      h('button', { type: 'button', class: 'btn btn-primary btn-sm', dataset: { act: 'save' } }, icon('check'), h('span', {}, t('save_prompt'))),
    ),
  );
  card._saved = { name: prompt.name, prompt: prompt.prompt };
  return card;
}

function render() {
  list.replaceChildren(...prompts.map(buildCard));
  refreshMeta();
}

function showErrors(card, fields) {
  for (const field of ['name', 'prompt']) {
    const messages = fields.filter((f) => f.field === field).map((f) => f.message);
    setFieldError(card.querySelector(`[data-field="${field}"]`), messages);
  }
  card.querySelector('[aria-invalid="true"]')?.focus();
}

/** Save one card. Returns the saved prompt, or null if it failed. */
async function saveCard(card, { activate = false } = {}) {
  const body = {
    name: card.querySelector('[data-input="name"]').value,
    prompt: card.querySelector('[data-input="prompt"]').value,
  };
  const isNew = card.dataset.draft === 'true';
  try {
    const result = isNew
      ? await api('POST', '/api/prompts', { ...body, active: activate || !prompts.some((p) => p.active && !p.draft) })
      : await api('PUT', `/api/prompts/${card.dataset.id}`, body);
    const saved = result.prompt;
    const index = prompts.findIndex((p) => (isNew ? p === card._draft : String(p.id) === card.dataset.id));
    if (saved.active) prompts.forEach((p) => (p.active = false));
    prompts[index] = { ...saved, draft: false };
    card.dataset.id = saved.id;
    card.dataset.draft = 'false';
    card._saved = { name: saved.name, prompt: saved.prompt };
    showErrors(card, []);
    refreshMeta();
    return saved;
  } catch (error) {
    if (error.status === 422) showErrors(card, error.fields);
    toast.error(error.message);
    return null;
  }
}

async function activateCard(card) {
  if (isDirty(card) && !(await saveCard(card, { activate: card.dataset.draft === 'true' }))) return;
  try {
    const result = await api('POST', `/api/prompts/${card.dataset.id}/activate`, {});
    const activeIds = new Set(result.prompts.filter((p) => p.active).map((p) => p.id));
    prompts.forEach((p) => (p.active = activeIds.has(p.id)));
    refreshMeta();
    toast.success(t('toast_prompt_activated'));
  } catch (error) {
    toast.error(error.message);
  }
}

async function deleteCard(card) {
  const name = card.querySelector('[data-input="name"]').value.trim() || t('new_prompt');
  if (card.dataset.draft !== 'true') {
    const confirmed = await confirmDialog({
      title: t('delete_prompt_title', { name }),
      body: t('delete_prompt_body'),
      confirmText: t('delete'),
    });
    if (!confirmed) return;
    try {
      await api('DELETE', `/api/prompts/${card.dataset.id}`);
    } catch (error) {
      if (error.status !== 404) {
        toast.error(error.message);
        return;
      }
    }
    toast.success(t('toast_prompt_deleted'));
  }
  prompts = prompts.filter((p) => (card.dataset.draft === 'true' ? p !== card._draft : String(p.id) !== card.dataset.id));
  const next = card.nextElementSibling || card.previousElementSibling;
  card.remove();
  refreshMeta();
  (next?.querySelector('input') || document.getElementById('new-prompt')).focus();
}

list.addEventListener('input', (event) => {
  const card = event.target.closest('.prompt-card');
  if (!card) return;
  const container = event.target.closest('[data-field]');
  if (container?.querySelector('.field-error:not([hidden])')) setFieldError(container, null);
  refreshMeta();
});

list.addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-act]');
  if (!button || button.disabled) return;
  const card = button.closest('.prompt-card');
  button.disabled = true;
  try {
    if (button.dataset.act === 'save') {
      if (await saveCard(card)) toast.success(t('toast_prompt_saved'));
    } else if (button.dataset.act === 'activate') {
      await activateCard(card);
    } else if (button.dataset.act === 'delete') {
      await deleteCard(card);
    }
  } finally {
    button.disabled = false;
  }
});

document.getElementById('new-prompt').addEventListener('click', () => {
  const draft = { id: null, name: '', prompt: '', active: false, draft: true };
  prompts.unshift(draft);
  const card = buildCard(draft);
  card._draft = draft;
  list.prepend(card);
  refreshMeta();
  card.querySelector('input').focus();
});

window.addEventListener('beforeunload', (event) => {
  if ([...list.children].some(isDirty)) {
    event.preventDefault();
    event.returnValue = '';
  }
});

render();

/* ------------------------------------------------------------------ AI model */

const statusBox = document.getElementById('ai-status');
const statusText = document.getElementById('ai-status-text');
const modelInput = document.getElementById('ai-model');
const urlInput = document.getElementById('ai-url');
const modelList = document.getElementById('ai-model-list');
const modelHint = document.getElementById('ai-model-hint');
const aiForm = document.getElementById('ai-form');

function showStatus(status) {
  let state = 'error';
  let text = t('ai_offline');
  if (status.reachable && status.model_installed && status.thinking_only) {
    state = 'warn';
    text = t('err_model_thinks', { model: status.model });
  } else if (status.reachable && status.model_installed) {
    state = 'ok';
    text = t('ai_ready', { version: status.version || '?', model: status.model });
  } else if (status.reachable) {
    state = 'warn';
    text = t('ai_no_model', { model: status.model });
  }
  statusBox.dataset.state = state;
  statusText.textContent = text;
  modelList.replaceChildren(...status.models.map((name) => h('option', { value: name })));
  modelHint.textContent = status.models.length ? t('ai_model_hint', { models: status.models.join(', ') }) : '';
}

async function refreshStatus() {
  statusBox.dataset.state = 'checking';
  statusText.textContent = t('ai_checking');
  try {
    showStatus(await api('GET', '/api/ai/status'));
  } catch (error) {
    statusBox.dataset.state = 'error';
    statusText.textContent = error.message;
  }
}

document.getElementById('ai-recheck').addEventListener('click', refreshStatus);

aiForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const save = document.getElementById('ai-save');
  save.disabled = true;
  for (const field of ['model', 'ollama_url']) setFieldError(aiForm.querySelector(`[data-field="${field}"]`), null);
  try {
    showStatus(await api('PUT', '/api/ai/settings', { model: modelInput.value, ollama_url: urlInput.value }));
    toast.success(t('toast_settings_saved'));
  } catch (error) {
    for (const field of error.fields || []) {
      setFieldError(aiForm.querySelector(`[data-field="${field.field}"]`), field.message);
    }
    toast.error(error.message);
  } finally {
    save.disabled = false;
  }
});

if (!document.getElementById('panel-ai').hidden) refreshStatus();

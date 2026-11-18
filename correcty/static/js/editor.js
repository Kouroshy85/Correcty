// Template editor: basics, message, optional sections, inputs, preview and save.
import { DIR, LANG, api, autoLabel, confirmDialog, fmtNum, h, icon, nextId, setFieldError, setFlash, t } from './app.js';
import { generator } from './generator.js';
import { toast } from './notifications.js';

const TOKEN_RE = /\{\{([^{}\n]*)\}\}/g;
const NAME_RE = /^[\p{L}_][\p{L}\p{N}_]*$/u;
const MAX_NAME = 40;
const SNIPPET = 28;
const LIMITS = { sections: 10, choicesMin: 2, choicesMax: 8 };
const VAR_TYPES = ['text', 'number', 'multiline'];

const data = JSON.parse(document.getElementById('editor-data').textContent);
const templateId = data.template.id;

const form = document.getElementById('editor');
const fields = {
  title: document.getElementById('f-title'),
  description: document.getElementById('f-desc'),
  pinned: document.getElementById('f-pinned'),
  body: document.getElementById('f-body'),
  closing: document.getElementById('f-closing'),
};
const sectionList = document.getElementById('section-list');
const sectionsEmpty = document.getElementById('sections-empty');
const addSectionBtn = document.getElementById('add-section');
const varList = document.getElementById('var-list');
const varsEmpty = document.getElementById('vars-empty');
const inputsCount = document.getElementById('inputs-count');
const dirtyStatus = document.getElementById('dirty-status');
const saveBtn = document.getElementById('save-btn');
const previewBtn = document.getElementById('preview-btn');

const state = {
  sections: data.template.sections.map((s) => ({
    id: s.id,
    question: s.question,
    choices: s.choices.map((c) => ({ id: c.id, label: c.label, text: c.text })),
  })),
  // Input settings are kept even if an input is removed from the text, so retyping it restores them.
  variables: new Map(
    data.template.variables.map((v) => [
      v.name,
      { label: v.label || '', type: v.type || 'text', required: v.required !== false, placeholder: v.placeholder || '' },
    ]),
  ),
};

let snapshot = '';
let saving = false;
let leaving = false;

/* ------------------------------------------------------------------ parsing (mirrors template_engine.py) */

const clip = (text) => {
  const flat = text.replace(/\n/g, ' ');
  return flat.length <= SNIPPET ? flat : `${flat.slice(0, SNIPPET)}…`;
};
const isValidName = (name) => name.length > 0 && name.length <= MAX_NAME && NAME_RE.test(name);

function parse(text) {
  const names = [];
  const issues = [];
  let pos = 0;
  const literal = (chunk) => {
    const open = chunk.indexOf('{{');
    const close = chunk.indexOf('}}');
    if (open !== -1) issues.push({ code: 'var_unclosed', snippet: clip(chunk.slice(open)) });
    else if (close !== -1) issues.push({ code: 'var_stray', snippet: clip(chunk.slice(Math.max(0, close - SNIPPET + 2), close + 2)) });
  };
  for (const match of text.matchAll(TOKEN_RE)) {
    literal(text.slice(pos, match.index));
    const name = match[1].trim();
    const end = match.index + match[0].length;
    const before = text[match.index - 1] || '';
    const after = text[end] || '';
    if (isValidName(name) && before !== '{' && after !== '}') {
      if (!names.includes(name)) names.push(name);
    } else {
      issues.push({ code: 'var_malformed', snippet: clip((before === '{' ? before : '') + match[0] + (after === '}' ? after : '')) });
    }
    pos = end;
  }
  literal(text.slice(pos));
  return { names, issues };
}

function textParts() {
  const parts = [{ text: fields.body.value, place: t('place_body') }];
  state.sections.forEach((section, i) => {
    for (const choice of section.choices) parts.push({ text: choice.text, place: t('place_section', { n: fmtNum(i + 1) }) });
  });
  parts.push({ text: fields.closing.value, place: t('place_closing') });
  return parts;
}

function scan() {
  const names = [];
  const usage = new Map();
  for (const part of textParts()) {
    for (const name of parse(part.text).names) {
      if (!names.includes(name)) names.push(name);
      const places = usage.get(name) || [];
      if (!places.includes(part.place)) places.push(part.place);
      usage.set(name, places);
    }
  }
  return { names, usage };
}

function varConfig(name) {
  if (!state.variables.has(name)) state.variables.set(name, { label: '', type: 'text', required: true, placeholder: '' });
  return state.variables.get(name);
}

function payload() {
  const { names } = scan();
  return {
    title: fields.title.value,
    description: fields.description.value,
    pinned: fields.pinned.checked,
    body: fields.body.value,
    closing: fields.closing.value,
    sections: state.sections.map((s) => ({
      id: s.id,
      question: s.question,
      choices: s.choices.map((c) => ({ id: c.id, label: c.label, text: c.text })),
    })),
    variables: names.map((name) => ({ name, ...varConfig(name) })),
  };
}

/* ------------------------------------------------------------------ errors */

function showParseIssues(textarea) {
  const container = textarea.closest('[data-field]');
  const messages = parse(textarea.value).issues.map((issue) => t(`err_${issue.code}`, { snippet: issue.snippet }));
  setFieldError(container, messages);
}

function clearErrorFor(control) {
  const container = control.closest('[data-field]');
  if (!container?.querySelector(':scope > .field-error:not([hidden])')) return;
  if (control.classList.contains('textarea--template')) showParseIssues(control);
  else setFieldError(container, null);
}

function clearAllErrors() {
  form.querySelectorAll('[data-field]').forEach((container) => {
    if (container.querySelector(':scope > .field-error:not([hidden])')) setFieldError(container, null);
  });
}

function fieldContainer(path) {
  const find = (p) => form.querySelector(`[data-field="${CSS.escape(p)}"]`);
  let el = find(path);
  if (!el && path.startsWith('variables')) el = find('variables');
  if (!el && path.startsWith('sections.')) {
    const parts = path.split('.');
    el = find(parts.slice(0, 4).join('.') + '.label') || find(parts.slice(0, 3).join('.')) || find(`${parts.slice(0, 2).join('.')}.question`);
  }
  return el || (path.startsWith('sections') ? find('sections') : null);
}

function showErrors(errors, summary = t('fix_errors')) {
  clearAllErrors();
  const grouped = new Map();
  const orphans = [];
  for (const error of errors) {
    const el = fieldContainer(error.field);
    if (!el) {
      orphans.push(error.message);
      continue;
    }
    const list = grouped.get(el) || [];
    if (!list.includes(error.message)) list.push(error.message);
    grouped.set(el, list);
  }
  grouped.forEach((messages, el) => setFieldError(el, messages));

  const firstError = form.querySelector('.field-error:not([hidden])');
  if (firstError) {
    const container = firstError.closest('[data-field]');
    const control = container.querySelector('[aria-invalid="true"]') || container.querySelector('input, textarea, select');
    const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    (control || firstError).scrollIntoView({ block: 'center', behavior: smooth ? 'smooth' : 'auto' });
    control?.focus({ preventScroll: true });
  }
  toast.error(orphans.length ? orphans.join(' ') : summary);
}

/* ------------------------------------------------------------------ sections */

function uniqueId(prefix, taken) {
  let id;
  do id = `${prefix}${Math.random().toString(36).slice(2, 8)}`;
  while (taken.has(id));
  return id;
}

function iconButton(name, label, dataset, { disabled = false, extra = '' } = {}) {
  return h(
    'button',
    { type: 'button', class: `btn-icon btn-icon--sm ${extra}`.trim(), 'aria-label': label, title: label, disabled, dataset },
    icon(name),
  );
}

// Each answer: its name, and the paragraph it adds to the message when an agent picks it.
function buildChoice(section, i, choice, j) {
  const n = fmtNum(j + 1);
  const base = `sections.${i}.choices.${j}`;
  const labelId = nextId('choice-label');
  const textId = nextId('choice-text');
  return h(
    'li',
    { class: 'choice-item' },
    h(
      'div',
      { class: 'choice-item__head' },
      h(
        'div',
        { class: 'field', dataset: { field: `${base}.label` } },
        h('label', { class: 'label', for: labelId }, t('answer_n', { n })),
        h('input', {
          class: 'input',
          id: labelId,
          value: choice.label,
          placeholder: t('choice_label_ph'),
          dir: 'auto',
          maxlength: 80,
          dataset: { bind: 'choice-label', s: i, c: j },
        }),
      ),
      iconButton('x', `${t('remove_choice')} — ${t('answer_n', { n })}`, { act: 'choice-remove', s: i, c: j }, {
        disabled: section.choices.length <= LIMITS.choicesMin,
        extra: 'btn-icon--danger',
      }),
    ),
    h(
      'div',
      { class: 'field', dataset: { field: `${base}.text` } },
      h(
        'div',
        { class: 'field__top' },
        h('label', { class: 'label label--muted', for: textId }, t('choice_text')),
        h(
          'button',
          { type: 'button', class: 'btn btn-ghost btn-xs', 'aria-haspopup': 'dialog', dataset: { insertFor: textId } },
          icon('braces'),
          h('span', {}, t('insert_input')),
        ),
      ),
      h('textarea', {
        class: 'textarea textarea--template',
        id: textId,
        rows: 2,
        value: choice.text,
        placeholder: t('choice_text_ph'),
        dir: 'auto',
        maxlength: 5000,
        dataset: { bind: 'choice-text', s: i, c: j },
      }),
    ),
  );
}

function buildSection(section, i) {
  const base = `sections.${i}`;
  const questionId = nextId('question');
  const last = state.sections.length - 1;
  return h(
    'li',
    { class: 'section-item', dataset: { index: i } },
    h(
      'div',
      { class: 'section-item__head' },
      h('span', { class: 'section-item__title' }, t('section_n', { n: fmtNum(i + 1) })),
      iconButton('chevron-up', t('move_up'), { act: 'section-up', s: i }, { disabled: i === 0 }),
      iconButton('chevron-down', t('move_down'), { act: 'section-down', s: i }, { disabled: i === last }),
      iconButton('trash', t('remove_section'), { act: 'section-remove', s: i }, { extra: 'btn-icon--danger' }),
    ),
    h(
      'div',
      { class: 'field', dataset: { field: `${base}.question` } },
      h('label', { class: 'label', for: questionId }, t('question'), h('span', { class: 'req', 'aria-hidden': 'true' }, '*')),
      h('input', {
        class: 'input',
        id: questionId,
        value: section.question,
        placeholder: t('question_ph'),
        dir: 'auto',
        maxlength: 200,
        dataset: { bind: 'question', s: i },
      }),
    ),
    h(
      'div',
      { class: 'field', dataset: { field: `${base}.choices` } },
      h('ol', { class: 'choice-list' }, section.choices.map((choice, j) => buildChoice(section, i, choice, j))),
    ),
    h(
      'div',
      { class: 'section-item__foot' },
      h(
        'button',
        { type: 'button', class: 'btn btn-ghost btn-xs', disabled: section.choices.length >= LIMITS.choicesMax, dataset: { act: 'choice-add', s: i } },
        icon('plus'),
        t('add_choice'),
      ),
    ),
  );
}

function autoGrow(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = `${Math.min(textarea.scrollHeight + 2, 320)}px`;
}

function renderSections(focusSelector) {
  sectionList.replaceChildren(...state.sections.map(buildSection));
  sectionsEmpty.hidden = state.sections.length > 0;
  addSectionBtn.disabled = state.sections.length >= LIMITS.sections;
  sectionList.querySelectorAll('.choice-item textarea').forEach(autoGrow);
  if (focusSelector) sectionList.querySelector(focusSelector)?.focus();
}

sectionList.addEventListener('input', (event) => {
  const el = event.target;
  const bind = el.dataset.bind;
  if (!bind) return;
  const section = state.sections[Number(el.dataset.s)];
  if (bind === 'question') {
    section.question = el.value;
  } else if (bind === 'choice-label') {
    section.choices[Number(el.dataset.c)].label = el.value;
  } else if (bind === 'choice-text') {
    section.choices[Number(el.dataset.c)].text = el.value;
    autoGrow(el);
  }
  clearErrorFor(el);
  scheduleUpdate();
});

sectionList.addEventListener('click', (event) => {
  const button = event.target.closest('button[data-act]');
  if (!button) return;
  const i = Number(button.dataset.s);
  const section = state.sections[i];
  const at = (index) => `[data-index="${index}"]`;
  switch (button.dataset.act) {
    case 'section-up':
    case 'section-down': {
      const target = button.dataset.act === 'section-up' ? i - 1 : i + 1;
      [state.sections[i], state.sections[target]] = [state.sections[target], state.sections[i]];
      const keep = target === 0 ? 'section-down' : target === state.sections.length - 1 ? 'section-up' : button.dataset.act;
      renderSections(`${at(target)} [data-act="${keep}"]`);
      break;
    }
    case 'section-remove':
      state.sections.splice(i, 1);
      renderSections(state.sections.length ? `${at(Math.min(i, state.sections.length - 1))} [data-bind="question"]` : null);
      if (!state.sections.length) addSectionBtn.focus();
      break;
    case 'choice-add':
      section.choices.push({ id: uniqueId('c', new Set(section.choices.map((c) => c.id))), label: '', text: '' });
      renderSections(`${at(i)} .choice-item:last-child [data-bind="choice-label"]`);
      break;
    case 'choice-remove': {
      const j = Number(button.dataset.c);
      section.choices.splice(j, 1);
      renderSections(`${at(i)} .choice-item:nth-child(${Math.min(j + 1, section.choices.length)}) [data-bind="choice-label"]`);
      break;
    }
    default:
      return;
  }
  scheduleUpdate();
});

addSectionBtn.addEventListener('click', () => {
  if (state.sections.length >= LIMITS.sections) return;
  state.sections.push({
    id: uniqueId('s', new Set(state.sections.map((s) => s.id))),
    question: '',
    choices: [
      { id: 'c1', label: '', text: '' },
      { id: 'c2', label: '', text: '' },
    ],
  });
  renderSections(`[data-index="${state.sections.length - 1}"] [data-bind="question"]`);
  scheduleUpdate();
});

/* ------------------------------------------------------------------ inputs panel */

let renderedNames = null;

function buildVarItem(name) {
  const config = varConfig(name);
  const base = `variables.${name}`;
  const ids = { label: nextId('v-label'), type: nextId('v-type'), placeholder: nextId('v-ph') };
  const bind = (key) => (event) => {
    config[key] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    clearErrorFor(event.target);
    scheduleUpdate();
  };
  return h(
    'li',
    { class: 'var-item', dataset: { var: name } },
    h('div', { class: 'var-item__head' }, h('code', { class: 'var-token' }, `{{${name}}}`), h('span', { class: 'var-item__where' })),
    h(
      'div',
      { class: 'var-item__grid' },
      h(
        'div',
        { class: 'field', dataset: { field: `${base}.label` } },
        h('label', { class: 'label', for: ids.label }, t('v_label')),
        h('input', { class: 'input input--sm', id: ids.label, value: config.label, placeholder: autoLabel(name), dir: 'auto', maxlength: 80, oninput: bind('label') }),
      ),
      h(
        'div',
        { class: 'field', dataset: { field: `${base}.type` } },
        h('label', { class: 'label', for: ids.type }, t('v_type')),
        h(
          'select',
          { class: 'select select--sm', id: ids.type, onchange: bind('type') },
          VAR_TYPES.map((type) => h('option', { value: type, selected: config.type === type }, t(`type_${type}`))),
        ),
      ),
      h(
        'div',
        { class: 'field field--wide', dataset: { field: `${base}.placeholder` } },
        h('label', { class: 'label', for: ids.placeholder }, t('v_placeholder')),
        h('input', {
          class: 'input input--sm',
          id: ids.placeholder,
          value: config.placeholder,
          placeholder: t('v_placeholder_ph'),
          dir: 'auto',
          maxlength: 120,
          oninput: bind('placeholder'),
        }),
      ),
      h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: config.required, onchange: bind('required') }), t('v_required')),
    ),
  );
}

function renderVars() {
  const { names, usage } = scan();
  inputsCount.textContent = fmtNum(names.length);
  varsEmpty.hidden = names.length > 0;
  const key = names.join('\u0000');
  if (key !== renderedNames) {
    renderedNames = key;
    varList.replaceChildren(...names.map(buildVarItem));
  }
  const separator = LANG === 'fa' ? '، ' : ', ';
  for (const item of varList.children) {
    item.querySelector('.var-item__where').textContent = t('used_in', { places: (usage.get(item.dataset.var) || []).join(separator) });
  }
}

/* ------------------------------------------------------------------ dirty tracking */

const isDirty = () => JSON.stringify(payload()) !== snapshot;

function refreshDirty() {
  const dirty = isDirty();
  dirtyStatus.textContent = dirty ? t('unsaved') : '';
  dirtyStatus.classList.toggle('is-dirty', dirty);
}

let updateTimer = null;
function scheduleUpdate() {
  clearTimeout(updateTimer);
  updateTimer = setTimeout(() => {
    renderVars();
    refreshDirty();
  }, 120);
}

form.addEventListener('input', (event) => {
  if (!Object.values(fields).includes(event.target)) return;
  clearErrorFor(event.target);
  scheduleUpdate();
});
fields.pinned.addEventListener('change', scheduleUpdate);
form.addEventListener('focusout', (event) => {
  if (event.target.classList?.contains('textarea--template')) showParseIssues(event.target);
});
form.addEventListener('keydown', (event) => {
  // Enter in a single-line field shouldn't save the whole template by accident.
  if (event.key === 'Enter' && event.target.tagName === 'INPUT' && event.target.type !== 'checkbox') event.preventDefault();
});

window.addEventListener('beforeunload', (event) => {
  if (leaving || !isDirty()) return;
  event.preventDefault();
  event.returnValue = '';
});

document.addEventListener('click', async (event) => {
  const link = event.target.closest('a[href]');
  if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
  if (link.getAttribute('href').startsWith('#') || link.target === '_blank' || !isDirty()) return;
  event.preventDefault();
  const discard = await confirmDialog({
    title: t('discard_title'),
    body: t('discard_body'),
    confirmText: t('discard'),
    cancelText: t('keep_editing'),
  });
  if (discard) {
    leaving = true;
    window.location.href = link.href;
  }
});

/* ------------------------------------------------------------------ save & preview */

function setBusy(button, busy, label) {
  button.disabled = busy;
  button.classList.toggle('is-busy', busy);
  if (label) button.querySelector('span').textContent = label;
}

async function save() {
  if (saving) return;
  const body = payload();
  const local = [];
  if (!body.title.trim()) local.push({ field: 'title', message: t('err_title_required') });
  if (!body.body.trim()) local.push({ field: 'body', message: t('err_body_required') });
  if (local.length) {
    showErrors(local);
    return;
  }
  saving = true;
  setBusy(saveBtn, true, t('saving'));
  try {
    const result = templateId
      ? await api('PUT', `/api/templates/${templateId}`, body)
      : await api('POST', '/api/templates', body);
    leaving = true;
    setFlash({ message: t(templateId ? 'toast_saved' : 'toast_created'), id: result.template.id });
    window.location.href = '/templates';
  } catch (error) {
    if (error.status === 422) showErrors(error.fields);
    else toast.error(error.message);
  } finally {
    if (!leaving) {
      saving = false;
      setBusy(saveBtn, false, t('save'));
    }
  }
}

let previewing = false;
async function preview() {
  if (previewing) return;
  previewing = true;
  setBusy(previewBtn, true);
  try {
    const body = payload();
    const prepared = await api('POST', '/api/preview', { template: body });
    clearAllErrors();
    generator.open({ kind: 'draft', template: body, title: body.title }, previewBtn, prepared);
  } catch (error) {
    if (error.status === 422) showErrors(error.fields, t('preview_fix'));
    else toast.error(error.message);
  } finally {
    previewing = false;
    setBusy(previewBtn, false);
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  save();
});
previewBtn.addEventListener('click', preview);
document.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && !document.querySelector('dialog[open]')) {
    event.preventDefault();
    save();
  }
});

/* ------------------------------------------------------------------ insert-input popover */

const popover = document.getElementById('insert-popover');
const popExisting = document.getElementById('insert-existing');
const popExistingWrap = document.getElementById('insert-existing-wrap');
const popName = document.getElementById('insert-name');
const popAdd = document.getElementById('insert-add');
const popError = document.getElementById('insert-error');
const popPreview = document.getElementById('insert-preview');
let popTarget = null;
let popTrigger = null;

function toVarName(raw) {
  let name = raw.trim().replace(/[\s\-‌]+/g, '_').replace(/[^\p{L}\p{N}_]/gu, '').toLowerCase();
  if (/^\p{N}/u.test(name)) name = `_${name}`;
  return name.slice(0, MAX_NAME);
}

function closePopover(restoreFocus = true) {
  if (popover.hidden) return;
  popover.hidden = true;
  if (restoreFocus) popTrigger?.focus();
}

function positionPopover() {
  const rect = popTrigger.getBoundingClientRect();
  const width = popover.offsetWidth;
  const maxLeft = document.documentElement.clientWidth - width - 12;
  const preferred = DIR === 'rtl' ? rect.left : rect.right - width;
  popover.style.left = `${Math.max(12, Math.min(preferred, maxLeft)) + window.scrollX}px`;
  popover.style.top = `${rect.bottom + window.scrollY + 6}px`;
}

function openPopover(trigger, target) {
  popTrigger = trigger;
  popTarget = target;
  const { names } = scan();
  popExistingWrap.hidden = names.length === 0;
  popExisting.replaceChildren(
    ...names.map((name) => h('button', { type: 'button', class: 'chip-btn', onclick: () => insertToken(name) }, `{{${name}}}`)),
  );
  popName.value = '';
  popPreview.textContent = '';
  popError.hidden = true;
  popName.removeAttribute('aria-invalid');
  popover.hidden = false;
  positionPopover();
  popName.focus();
}

function insertToken(name) {
  const token = `{{${name}}}`;
  const target = popTarget;
  closePopover(false);
  target.focus();
  let inserted = false;
  try {
    inserted = document.execCommand('insertText', false, token);
  } catch {
    inserted = false;
  }
  if (!inserted) {
    target.setRangeText(token, target.selectionStart, target.selectionEnd, 'end');
    target.dispatchEvent(new Event('input', { bubbles: true }));
  }
}

function addFromName() {
  const raw = popName.value;
  const name = toVarName(raw);
  const problem = !raw.trim() ? t('insert_name_required') : !isValidName(name) ? t('insert_name_invalid') : '';
  if (problem) {
    popError.replaceChildren(icon('alert'), h('span', {}, problem));
    popError.hidden = false;
    popName.setAttribute('aria-invalid', 'true');
    popName.focus();
    return;
  }
  insertToken(name);
}

document.addEventListener('click', (event) => {
  const trigger = event.target.closest('[data-insert-for]');
  if (!trigger) return;
  const target = document.getElementById(trigger.dataset.insertFor);
  if (!popover.hidden && popTrigger === trigger) closePopover();
  else if (target) openPopover(trigger, target);
});
popName.addEventListener('input', () => {
  const name = toVarName(popName.value);
  popPreview.textContent = name ? `{{${name}}}` : '';
  popError.hidden = true;
  popName.removeAttribute('aria-invalid');
});
popName.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    addFromName();
  }
});
popAdd.addEventListener('click', addFromName);
popover.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    event.stopPropagation();
    closePopover();
  }
});
document.addEventListener('mousedown', (event) => {
  if (!popover.hidden && !popover.contains(event.target) && !event.target.closest('[data-insert-for]')) closePopover(false);
});
window.addEventListener('resize', () => {
  if (!popover.hidden) positionPopover();
});

/* ------------------------------------------------------------------ init */

renderSections();
renderVars();
snapshot = JSON.stringify(payload());
refreshDirty();
if (data.isNew) fields.title.focus();

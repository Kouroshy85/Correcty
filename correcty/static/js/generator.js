// Message generator dialog: pick answers, fill inputs, see a live preview, copy.
// Rendering always happens on the server so the preview and the copied text use the same engine.
import { api, copyText, h, icon, nextId, selectContents, setFieldError, setupDialog, t } from './app.js';
import { toast } from './notifications.js';

const RENDER_DELAY = 70;
const ALWAYS_SHOWN_CODES = new Set(['value_number', 'value_too_long', 'value_braces', 'value_invalid']);

class Generator {
  constructor(dialog) {
    this.dialog = dialog;
    const $ = (id) => dialog.querySelector(`#${id}`);
    this.els = {
      title: $('gen-title'),
      desc: $('gen-desc'),
      badge: $('gen-preview-badge'),
      loading: $('gen-loading'),
      loadError: $('gen-load-error'),
      loadErrorText: $('gen-load-error-text'),
      retry: $('gen-retry'),
      form: $('gen-form'),
      outputBlock: $('gen-output-block'),
      output: $('gen-output'),
      hint: $('gen-output-hint'),
      live: $('gen-live'),
      liveText: $('gen-live-text'),
      copy: $('gen-copy'),
    };
    this.session = 0;
    this.reset();

    this.dialogApi = setupDialog(dialog, { onClose: () => this.reset() });
    this.els.copy.addEventListener('click', () => this.copy());
    this.els.retry.addEventListener('click', () => this.load());
    this.els.form.addEventListener('submit', (event) => event.preventDefault());
    this.els.form.addEventListener('input', (event) => this.onInput(event));
    this.els.form.addEventListener('change', (event) => this.onChange(event));
    this.els.form.addEventListener('focusout', (event) => this.onBlur(event));
    this.els.form.addEventListener('click', (event) => {
      const button = event.target.closest('[data-clear]');
      if (button) this.clearAnswer(button.dataset.clear);
    });
    dialog.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        this.copy();
      }
    });
  }

  reset() {
    clearTimeout(this.timer);
    this.session += 1;
    this.source = null;
    this.form = null;
    this.selections = {};
    this.values = {};
    this.touched = new Set();
    this.attempted = false;
    this.version = 0;
    this.result = null;
    this.resultVersion = -1;
    this.pending = null;
    this.copying = false;
    this.fieldEls = new Map();
    this.sectionEls = new Map();
    this.els.form.replaceChildren();
    this.els.output.replaceChildren();
    this.setReady(false);
  }

  /**
   * Open the dialog.
   * source: { kind: 'saved', id, title } or { kind: 'draft', template, title }
   * preloaded: optional { template, form, result } (already fetched by the caller)
   */
  open(source, trigger, preloaded = null) {
    if (this.dialogApi.isOpen()) this.dialogApi.close();
    this.reset();
    this.source = source;
    this.els.title.textContent = source.title || '';
    this.els.desc.hidden = true;
    this.els.badge.hidden = source.kind !== 'draft';
    this.dialogApi.open(trigger);
    if (preloaded) this.setup(preloaded);
    else this.load();
  }

  async load() {
    const session = this.session;
    this.showState('loading');
    try {
      const data = await api('GET', `/api/templates/${this.source.id}`);
      if (session !== this.session) return;
      this.setup(data);
    } catch (error) {
      if (session !== this.session) return;
      this.els.loadErrorText.textContent = error.status === 404 ? error.message : `${t('load_failed')} ${error.message}`;
      this.showState('error');
    }
  }

  showState(state) {
    this.els.loading.hidden = state !== 'loading';
    this.els.loadError.hidden = state !== 'error';
    this.els.outputBlock.hidden = state !== 'ready';
    this.els.form.hidden = state !== 'ready';
    this.els.copy.disabled = state !== 'ready';
  }

  setup({ template, form, result }) {
    this.form = form;
    this.els.title.textContent = template.title;
    this.els.desc.textContent = template.description || '';
    this.els.desc.hidden = !template.description;
    this.buildForm();
    this.updateVisibility();
    this.showState('ready');
    if (result) this.applyResult(result, this.version);
    else this.renderNow();
    this.focusFirst();
  }

  /* ------------------------------------------------------------ form building */

  buildForm() {
    const { form } = this;
    const sections = new Map(form.sections.map((s) => [s.id, s]));
    const nodes = [];
    form.layout.forEach((item, index) => {
      if (item.kind === 'var') {
        nodes.push(this.buildVar(item.name));
        return;
      }
      // Optional question: starts unanswered, and an unanswered question adds nothing to the message.
      const section = sections.get(item.id);
      const clear = h(
        'button',
        { type: 'button', class: 'btn btn-ghost btn-xs', hidden: true, dataset: { clear: section.id } },
        icon('x'),
        h('span', {}, t('clear_answer')),
      );
      const group = h(
        'fieldset',
        { class: 'choice-group' },
        h(
          'legend',
          { class: 'choice-group__legend' },
          h('span', { dir: 'auto' }, section.question),
          h('span', { class: 'label__opt' }, ` (${t('optional')})`),
        ),
        h(
          'div',
          { class: 'pills' },
          section.choices.map((choice) =>
            h(
              'label',
              { class: 'radio-pill' },
              h('input', {
                type: 'radio',
                name: `gen-section-${index}`,
                value: choice.id,
                dataset: { section: section.id },
              }),
              h('span', { dir: 'auto' }, choice.label),
            ),
          ),
          clear,
        ),
      );
      const sub = h('div', { class: 'gen-subfields' }, item.vars.map((name) => this.buildVar(name)));
      this.sectionEls.set(section.id, { group, sub, clear });
      nodes.push(h('div', { class: 'gen-section' }, group, sub));
    });
    if (!nodes.length) nodes.push(h('p', { class: 'gen-note' }, icon('check'), t('gen_no_inputs')));
    this.els.form.replaceChildren(...nodes);
  }

  buildVar(name) {
    const field = this.form.fields[name];
    const id = nextId('gen-var');
    const common = {
      id,
      dir: 'auto',
      placeholder: field.placeholder || undefined,
      autocomplete: 'off',
      'aria-required': field.required ? 'true' : undefined,
      dataset: { var: name },
    };
    const control =
      field.type === 'multiline'
        ? h('textarea', { ...common, class: 'textarea', rows: 3 })
        : h('input', {
            ...common,
            class: 'input',
            type: 'text',
            inputmode: field.type === 'number' ? 'decimal' : undefined,
            spellcheck: field.type === 'number' ? 'false' : undefined,
          });
    const label = h(
      'label',
      { class: 'label', for: id },
      h('span', { dir: 'auto' }, field.label),
      field.required
        ? h('span', { class: 'req', 'aria-hidden': 'true' }, '*')
        : h('span', { class: 'label__opt' }, ` (${t('optional')})`),
    );
    const container = h('div', { class: 'field', dataset: { var: name } }, label, control);
    this.fieldEls.set(name, container);
    return container;
  }

  visibleVars() {
    const visible = new Set(this.form.always);
    for (const [sectionId, choiceId] of Object.entries(this.selections)) {
      (this.form.choice_vars[sectionId]?.[choiceId] || []).forEach((name) => visible.add(name));
    }
    return visible;
  }

  updateVisibility() {
    const visible = this.visibleVars();
    for (const [name, el] of this.fieldEls) el.hidden = !visible.has(name);
    for (const { sub } of this.sectionEls.values()) {
      sub.hidden = ![...sub.children].some((child) => !child.hidden);
    }
  }

  focusFirst() {
    const form = this.els.form;
    for (const el of form.querySelectorAll('fieldset, [data-var]:is(input, textarea)')) {
      if (el.closest('[hidden]')) continue;
      if (el.tagName === 'FIELDSET') {
        if (!el.querySelector('input:checked')) return el.querySelector('input').focus();
      } else if (!el.value) {
        return el.focus();
      }
    }
    this.els.copy.focus();
  }

  /* ------------------------------------------------------------ events */

  onInput(event) {
    const name = event.target.dataset?.var;
    if (!name) return;
    this.values[name] = event.target.value;
    this.scheduleRender();
  }

  onChange(event) {
    const sectionId = event.target.dataset?.section;
    if (!sectionId) return;
    this.selections[sectionId] = event.target.value;
    this.sectionEls.get(sectionId).clear.hidden = false;
    this.updateVisibility();
    this.scheduleRender(0);
  }

  clearAnswer(sectionId) {
    const { group, clear } = this.sectionEls.get(sectionId);
    delete this.selections[sectionId];
    group.querySelectorAll('input[type="radio"]').forEach((radio) => {
      radio.checked = false;
    });
    clear.hidden = true;
    this.updateVisibility();
    this.scheduleRender(0);
    group.querySelector('input[type="radio"]')?.focus();
  }

  onBlur(event) {
    const name = event.target.dataset?.var;
    if (!name) return;
    this.touched.add(`var:${name}`);
    this.showErrors();
  }

  /* ------------------------------------------------------------ rendering */

  scheduleRender(delay = RENDER_DELAY) {
    this.version += 1;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.renderNow(), delay);
  }

  request(payload) {
    if (this.source.kind === 'saved') return api('POST', `/api/templates/${this.source.id}/render`, payload);
    return api('POST', '/api/preview', { template: this.source.template, ...payload }).then((data) => data.result);
  }

  /** Render the current state. Resolves { version, result } or null on failure. */
  renderNow() {
    clearTimeout(this.timer);
    const { version, session } = this;
    if (this.pending?.version === version) return this.pending.promise;
    const payload = { choices: { ...this.selections }, values: { ...this.values } };
    const promise = this.request(payload)
      .then((result) => {
        if (session !== this.session) return null;
        if (version === this.version) this.applyResult(result, version);
        return { version, result };
      })
      .catch((error) => {
        if (session === this.session) toast.error(error.message);
        return null;
      });
    this.pending = { version, promise };
    return promise;
  }

  applyResult(result, version) {
    this.result = result;
    this.resultVersion = version;
    this.renderPreview(result.segments);
    this.setReady(result.ok);
    this.showErrors();
  }

  renderPreview(segments) {
    const nodes = segments.map((seg) => {
      if (seg.t === 'text') return document.createTextNode(seg.v);
      if (seg.filled && !seg.invalid) return h('span', { class: 'val' }, seg.v);
      if (seg.filled) return h('span', { class: 'ph ph--invalid' }, seg.v);
      return h('span', { class: seg.required ? 'ph' : 'ph ph--optional', dir: 'auto' }, seg.label);
    });
    this.els.output.replaceChildren(...nodes);
    this.els.output.dir = 'auto';
  }

  setReady(ready) {
    this.els.output.classList.toggle('is-ready', ready);
    this.els.live.classList.toggle('is-ready', ready);
    this.els.liveText.textContent = ready ? t('gen_ready') : t('gen_live');
  }

  showErrors() {
    if (!this.result || !this.form) return;
    const errors = new Map(this.result.errors.map((e) => [e.field, e]));
    for (const [name, el] of this.fieldEls) {
      const key = `var:${name}`;
      const error = errors.get(key);
      const show =
        error && !el.hidden && (this.attempted || (this.touched.has(key) && ALWAYS_SHOWN_CODES.has(error.code)));
      setFieldError(el, show ? error.message : null);
    }
    for (const [sectionId, { group }] of this.sectionEls) {
      const error = errors.get(`section:${sectionId}`);
      group.classList.toggle('is-invalid', Boolean(error));
      setFieldError(group, error ? error.message : null);
    }
    const broken = errors.get('_template');
    const hint = broken ? broken.message : '';
    this.els.hint.textContent = hint;
    this.els.hint.hidden = !hint;
  }

  /* ------------------------------------------------------------ copy */

  async copy() {
    if (this.copying || !this.form) return;
    this.copying = true;
    try {
      this.attempted = true;
      let { result } = this;
      if (!result || this.resultVersion !== this.version) {
        const outcome = await this.renderNow();
        if (!outcome) return;
        result = outcome.result;
      }
      this.showErrors();
      if (!result.ok) {
        const invalid = [...this.els.form.querySelectorAll('[aria-invalid="true"], .choice-group.is-invalid input')].find(
          (el) => !el.closest('[hidden]'),
        );
        invalid?.focus();
        if (!invalid) toast.error(this.els.hint.textContent || t('copy_blocked'));
        return;
      }
      if (await copyText(result.text)) {
        toast.success(t('copied'));
      } else {
        selectContents(this.els.output);
        toast.error(t('copy_failed'));
      }
    } finally {
      this.copying = false;
    }
  }
}

export const generator = new Generator(document.getElementById('generator'));

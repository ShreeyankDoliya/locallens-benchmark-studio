/** Theme-aware select-only comboboxes; native selects remain the data source. */
const controls = new Map();
let opened = null;

export function refreshSelects() {
  for (const control of controls.values()) control.refresh();
}

export function enhanceSelects() {
  for (const select of document.querySelectorAll('select')) {
    if (controls.has(select)) continue;
    const wrapper = document.createElement('div');
    wrapper.className = 'themed-select';
    select.before(wrapper);
    wrapper.append(select);
    select.hidden = true;

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'select-trigger';
    button.id = `${select.id}-trigger`;
    button.setAttribute('role', 'combobox');
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    const text = document.createElement('span');
    text.className = 'select-value';
    text.id = `${select.id}-value`;
    const arrow = document.createElement('span');
    arrow.className = 'select-chevron';
    arrow.setAttribute('aria-hidden', 'true');
    button.append(text, arrow);
    wrapper.append(button);

    const labels = [...select.labels];
    labels.forEach((label, index) => {
      label.id ||= `${select.id}-label-${index}`;
      label.htmlFor = button.id;
    });
    if (labels.length) button.setAttribute('aria-labelledby', labels.map(l => l.id).join(' '));
    else button.setAttribute('aria-label', select.getAttribute('aria-label') || select.id);
    button.setAttribute('aria-describedby', text.id);

    const list = document.createElement('div');
    list.id = `${select.id}-listbox`;
    list.className = 'select-menu';
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', labels.map(l => l.textContent).join(' ') || select.id);
    list.hidden = true;
    button.setAttribute('aria-controls', list.id);
    document.body.append(list);
    let active = 0, query = '', queryAt = 0;

    function refresh() {
      text.textContent = select.selectedOptions[0]?.textContent || 'No options';
      button.title = text.textContent;
      button.disabled = select.disabled || select.options.length === 0;
      if (opened === control) close();
    }
    function highlight(index) {
      active = Math.max(0, Math.min(select.options.length - 1, index));
      for (const [i, item] of [...list.children].entries()) item.classList.toggle('is-active', i === active);
      const item = list.children[active];
      if (item) {
        button.setAttribute('aria-activedescendant', item.id);
        item.scrollIntoView({ block: 'nearest' });
      }
    }
    function close() {
      list.hidden = true;
      button.setAttribute('aria-expanded', 'false');
      button.removeAttribute('aria-activedescendant');
      if (opened === control) opened = null;
      query = '';
    }
    function choose(index) {
      const option = select.options[index];
      if (!option || option.disabled) return;
      const changed = select.value !== option.value;
      select.value = option.value;
      close();
      refresh();
      button.focus({ preventScroll: true });
      if (changed) select.dispatchEvent(new Event('change', { bubbles: true }));
    }
    function open() {
      if (button.disabled) return;
      opened?.close();
      list.replaceChildren(...[...select.options].map((option, index) => {
        const item = document.createElement('div');
        item.id = `${select.id}-option-${index}`;
        item.className = 'select-option';
        item.setAttribute('role', 'option');
        item.setAttribute('aria-selected', String(option.selected));
        item.setAttribute('aria-disabled', String(option.disabled));
        item.dataset.value = option.value;
        const label = document.createElement('span');
        label.textContent = option.textContent;
        const check = document.createElement('span');
        check.textContent = option.selected ? '✓' : '';
        check.className = 'select-check';
        check.setAttribute('aria-hidden', 'true');
        item.append(label, check);
        item.addEventListener('pointerdown', event => event.preventDefault());
        item.addEventListener('click', () => choose(index));
        item.addEventListener('pointermove', () => highlight(index));
        return item;
      }));
      const rect = button.getBoundingClientRect();
      control.anchorTop = rect.top;
      control.anchorLeft = rect.left;
      const width = Math.min(Math.max(rect.width, 220), innerWidth - 24);
      list.style.width = `${width}px`;
      list.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - width - 12))}px`;
      const below = innerHeight - rect.bottom - 16;
      const above = rect.top - 16;
      const upwards = below < 170 && above > below;
      list.style.maxHeight = `${Math.max(80, Math.min(300, upwards ? above : below))}px`;
      list.style.top = upwards ? 'auto' : `${rect.bottom + 7}px`;
      list.style.bottom = upwards ? `${innerHeight - rect.top + 7}px` : 'auto';
      list.hidden = false;
      opened = control;
      button.setAttribute('aria-expanded', 'true');
      highlight(Math.max(0, select.selectedIndex));
    }
    const control = { select, button, list, open, close, refresh };
    controls.set(select, control);
    button.addEventListener('click', () => opened === control ? close() : open());
    button.addEventListener('keydown', event => {
      const isOpen = opened === control;
      if (event.key === 'Escape' && isOpen) { event.preventDefault(); close(); return; }
      if (event.key === 'Tab') { if (isOpen) choose(active); return; }
      if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(event.key)) {
        event.preventDefault();
        if (!isOpen) { open(); if (event.key === 'Home') highlight(0); if (event.key === 'End') highlight(select.options.length - 1); return; }
        if (event.key === 'ArrowDown') highlight(active + 1);
        if (event.key === 'ArrowUp') highlight(active - 1);
        if (event.key === 'Home') highlight(0);
        if (event.key === 'End') highlight(select.options.length - 1);
        if (event.key === 'Enter' || event.key === ' ') choose(active);
        return;
      }
      if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        if (!isOpen) open();
        const time = performance.now();
        query = (time - queryAt > 700 ? '' : query) + event.key.toLocaleLowerCase();
        queryAt = time;
        const index = [...select.options].findIndex(o => o.textContent.toLocaleLowerCase().startsWith(query));
        if (index >= 0) highlight(index);
      }
    });
    select.addEventListener('change', refresh);
    new MutationObserver(refresh).observe(select, { childList: true, subtree: true, attributes: true });
    refresh();
  }
}

document.addEventListener('pointerdown', event => {
  if (opened && !opened.button.contains(event.target) && !opened.list.contains(event.target)) opened.close();
});
document.addEventListener('focusin', event => {
  if (opened && event.target !== opened.button) opened.close();
});
window.addEventListener('resize', () => opened?.close());
document.addEventListener('scroll', event => {
  if (!opened || opened.list.contains(event.target)) return;
  const rect = opened.button.getBoundingClientRect();
  if (Math.abs(rect.top - opened.anchorTop) > 1 || Math.abs(rect.left - opened.anchorLeft) > 1) opened.close();
}, true);

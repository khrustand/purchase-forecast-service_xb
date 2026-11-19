"""Same-origin JavaScript for the order details dialog."""

ORDER_DETAILS_SCRIPT = """'use strict';
const dialog = document.getElementById('item-dialog');
const content = document.getElementById('dialog-content');
if (dialog && content) {
  document.querySelectorAll('.detail-button').forEach(button => button.addEventListener('click', () => {
    const template = button.parentElement.querySelector('template');
    content.replaceChildren(template ? template.content.cloneNode(true) : document.createTextNode('Детали недоступны'));
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', 'open');
  }));
  const close = () => {
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  };
  document.querySelector('.dialog-close')?.addEventListener('click', close);
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && dialog.open) close(); });
}
"""

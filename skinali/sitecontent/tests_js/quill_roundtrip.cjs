// Кодовая проверка настоящего Quill в DOM-эмуляторе; браузер не запускается.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {JSDOM} = require(process.argv[2] || 'jsdom');
const staticRoot = path.resolve(__dirname, '../static/sitecontent');
const source = '<h2>Заголовок статьи</h2><p>Обычные слова <span class="ql-font-georgia ql-color-green ql-bg-yellow ql-size-large">и оформленный текст</span> переносятся целиком.</p>'
  + '<ul><li>Первый<ul><li>Вложенный</li></ul></li></ul>'
  + '<p class="ql-align-center"><img src="/media/articles/content/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg" alt="Пример"></p>';
const dom = new JSDOM('<form><input name="csrfmiddlewaretoken" value="test-token">'
  + '<div data-quill-field data-upload-url="/admin/sitecontent/article/upload-image/" '
  + 'data-fonts="arial,georgia,monospace" data-colors="ink,muted,green,red,blue" '
  + 'data-backgrounds="yellow,green,blue,pink,orange">'
  + '<textarea id="id_body" required></textarea><div class="article-content" data-quill-editor></div>'
  + '<input type="file" data-quill-image><p data-quill-status></p></div></form>',
  {url: 'http://localhost/', runScripts: 'outside-only', pretendToBeVisual: true});
const {window} = dom;
window.Range.prototype.getBoundingClientRect = () => ({top: 0, left: 0, right: 0, bottom: 0});
window.Range.prototype.getClientRects = () => [];
window.document.querySelector('textarea').value = source;
window.eval(fs.readFileSync(path.join(staticRoot, 'vendor/quill/quill.js'), 'utf8'));
window.eval(fs.readFileSync(path.join(staticRoot, 'js/quill-editor.js'), 'utf8'));
window.document.dispatchEvent(new window.Event('DOMContentLoaded'));
const textarea = window.document.querySelector('textarea');
const editor = window.Quill.find(window.document.querySelector('[data-quill-editor]'));
assert.ok(editor);
assert.ok(textarea.hidden);
assert.equal(textarea.required, false);
const initialDelta = JSON.parse(JSON.stringify(editor.getContents()));
const html = editor.getSemanticHTML();
assert.ok(html.includes('&nbsp;'), 'Quill must reproduce its nonbreaking space export');
for (const expected of ['ql-font-georgia', 'ql-color-green', 'ql-bg-yellow', 'ql-size-large', '<ul>', 'ql-align-center', 'alt="Пример"']) {
  assert.ok(html.includes(expected), `Missing ${expected}: ${html}`);
}
const projectRoot = path.resolve(__dirname, '../..');
const python = process.argv[3] || path.resolve(projectRoot, '../venv/Scripts/python.exe');
const sanitized = spawnSync(python, ['-c',
  'from django.conf import settings; settings.configure(MEDIA_URL="/media/"); '
  + 'from sitecontent.rich_text import sanitize_article_html; import sys; '
  + 'sys.stdout.buffer.write(sanitize_article_html(sys.stdin.buffer.read().decode()).encode())'],
  {cwd: projectRoot, input: html, encoding: 'utf8'});
assert.equal(sanitized.status, 0, sanitized.stderr);
assert.ok(!sanitized.stdout.includes('&nbsp;'), 'Exported spaces must allow word wrapping');
assert.ok(!sanitized.stdout.includes('\u00a0'));
assert.ok(sanitized.stdout.includes('Обычные слова '));
editor.setContents(editor.clipboard.convert({html: sanitized.stdout}), 'silent');
assert.deepEqual(JSON.parse(JSON.stringify(editor.getContents())), initialDelta);
const highlightPicker = window.document.querySelector('.ql-background.ql-picker');
assert.equal(highlightPicker.getAttribute('aria-label'), 'Выделение маркером');
const highlightStart = editor.getText().indexOf('Обычные слова');
const highlightLength = 'Обычные слова'.length;
for (const color of ['yellow', 'green', 'blue', 'pink', 'orange']) {
  editor.setSelection(highlightStart, highlightLength, 'silent');
  highlightPicker.querySelector(`[data-value="${color}"].ql-picker-item`).click();
  assert.equal(editor.getFormat(highlightStart, highlightLength).background, color);
  assert.ok(textarea.value.includes(`ql-bg-${color}`));
}
editor.setSelection(highlightStart, highlightLength, 'silent');
[...highlightPicker.querySelectorAll('.ql-picker-item')].find((item) => !item.dataset.value).click();
assert.equal(editor.getFormat(highlightStart, highlightLength).background, undefined);
const submit = new window.Event('submit', {cancelable: true});
window.document.querySelector('form').dispatchEvent(submit);
assert.equal(submit.defaultPrevented, false);
assert.equal(textarea.value, editor.getSemanticHTML());
const css = fs.readFileSync(path.join(staticRoot, 'css/article-content.css'), 'utf8');
assert.ok(css.includes('--article-font-size: 16px'));
assert.ok(css.includes('--article-color: #1f231f'));
async function checkUpload() {
  let completeUpload;
  let request;
  window.fetch = (url, options) => {
    request = {url, options};
    return new Promise((resolve) => { completeUpload = resolve; });
  };
  const picker = window.document.querySelector('[data-quill-image]');
  Object.defineProperty(picker, 'files', {value: [new window.File(['image'], 'test.jpg', {type: 'image/jpeg'})]});
  picker.dispatchEvent(new window.Event('change'));
  assert.equal(request.options.headers['X-CSRFToken'], 'test-token');
  assert.equal(request.options.credentials, 'same-origin');
  const pendingSubmit = new window.Event('submit', {cancelable: true});
  window.document.querySelector('form').dispatchEvent(pendingSubmit);
  assert.equal(pendingSubmit.defaultPrevented, true);
  const imageUrl = '/media/articles/content/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg';
  completeUpload({ok: true, headers: {get: () => 'application/json'}, json: async () => ({url: imageUrl})});
  await new Promise((resolve) => window.setTimeout(resolve, 0));
  assert.ok(textarea.value.includes(imageUrl));
  assert.equal(editor.isEnabled(), true);
  editor.history.undo();
  assert.ok(!editor.getSemanticHTML().includes(imageUrl));
  console.log('Quill 2: HTML/sanitizer roundtrip, marker colors/removal, nested lists, image upload, CSRF, pending submit and undo passed.');
  window.close();
}
checkUpload().catch((error) => { window.close(); console.error(error); process.exitCode = 1; });

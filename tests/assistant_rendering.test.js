const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const script = fs.readFileSync('app/static/app/chat/presenter.js', 'utf8');

function functionBody(name) {
  const start = script.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} must exist`);
  const end = script.indexOf('\nfunction ', start + 1);
  return script.slice(start, end === -1 ? script.length : end);
}

test('live assistant rendering keeps the copy action between answer body and sources', () => {
  const body = functionBody('renderAssistantInto');
  const contentEnd = body.indexOf('${renderedContent}</div>');
  const actions = body.indexOf('<div class="message-actions">${copyButton}</div>');
  const sources = body.indexOf('${sourcePanel}');

  assert.ok(contentEnd >= 0, 'answer body must close after rendered content');
  assert.ok(actions > contentEnd, 'copy action must follow the answer body');
  assert.ok(sources > actions, 'source panel must follow the copy action');
  assert.match(body, /const sourcePanel = renderSourcePanel\(sources\);/);
});

test('copy replacement and source navigation contracts remain connected to live answers', () => {
  const body = functionBody('renderAssistantInto');
  assert.match(body, /sourcePresenter\.replaceReferenceIds\(content, sources\)/);

  const sourcePanel = functionBody('renderSourcePanel');
  assert.match(sourcePanel, /sourceLink\(source, sourcePresenter\.locationLabel\(source\) \|\| '打开来源'\)/);
  assert.match(functionBody('sourceLink'), /sourceNavigationAttributes\(source\)/);
});

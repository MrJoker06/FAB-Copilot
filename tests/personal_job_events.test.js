const assert = require('assert');
const events = require('../app/static/personal_job_events.js');

const received = [];
const parser = events.createParser(item => received.push(item));
parser.push('id: j-1\r');
parser.push('\nevent: job\r\ndata: {"a":1}\r\ndata: {"b":2}\r\n: ignored\r\nretry: 1200\r');
parser.push('\n\r\n');
parser.push('event: job\ndata: bad-json\n\n');
parser.push('event: unknown\ndata:\n\n');
parser.finish();
assert.deepStrictEqual(received[0], {id:'j-1', event:'job', data:'{"a":1}\n{"b":2}', retry:1200});
assert.equal(received[1].data, 'bad-json'); // parser preserves malformed JSON for callers to ignore.
assert.equal(received[2].event, 'unknown');
assert(events.isActive('indexing'));
assert(!events.isActive('ready'));
assert(events.isTerminal('ready'));
assert(events.isTerminal('deleted'));
const reconnect = events.createReconnectPolicy({maxAttempts:2, baseDelay:10, maxDelay:15});
const initialJobs = events.createParser(() => {});
initialJobs.push('event: job\ndata: {"document_id":"one"}\n\nevent: job\ndata: {"document_id":"two"}\n\n');
// Parsing two initial snapshots does not alter the bounded reconnect budget.
assert.equal(reconnect.nextDelay(), 10);
assert.equal(reconnect.nextDelay(), 15);
assert.equal(reconnect.nextDelay(), null);
reconnect.reset();
assert.equal(reconnect.nextDelay(7), 7);
console.log('personal_job_events tests passed');

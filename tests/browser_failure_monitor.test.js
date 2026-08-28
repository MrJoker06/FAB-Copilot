"use strict";

const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const test = require("node:test");
const { createBrowserFailureMonitor, matchesExpectation } = require("./e2e/support/browser-failure-monitor");

class FakePage extends EventEmitter {}

function fakeRequest(url, method = "GET", errorText = "ERR_FAILED") {
  return { url: () => url, method: () => method, failure: () => ({ errorText }) };
}

function fakeResponse(url, status, method = "GET") {
  return { url: () => url, status: () => status, request: () => ({ method: () => method }) };
}

test("browser failure monitor rejects unapproved same-origin errors and server failures", () => {
  const page = new FakePage();
  const monitor = createBrowserFailureMonitor(page, { baseURL: "http://127.0.0.1:8899" });
  page.emit("pageerror", new Error("render failed"));
  page.emit("console", { type: () => "error", text: () => "client failed" });
  page.emit("requestfailed", fakeRequest("http://127.0.0.1:8899/api/fail", "POST", "ERR_CONNECTION_RESET"));
  page.emit("response", fakeResponse("http://127.0.0.1:8899/api/fail", 503, "POST"));
  assert.throws(() => monitor.assertNoFailures(), /pageerror: render failed[\s\S]*response: POST \/api\/fail 503/);
});

test("browser failure monitor ignores cross-origin events and matches only local expectations", () => {
  const page = new FakePage();
  const monitor = createBrowserFailureMonitor(page, { baseURL: "http://127.0.0.1:8899" });
  monitor.allowRequestFailed({ method: "GET", pathname: "/api/knowledge/personal/jobs/events", errorText: /ERR_ABORTED/i });
  page.emit("requestfailed", fakeRequest("https://example.test/error", "GET"));
  page.emit("requestfailed", fakeRequest("http://127.0.0.1:8899/api/knowledge/personal/jobs/events", "GET", "net::ERR_ABORTED"));
  monitor.assertNoFailures();
  assert.equal(matchesExpectation({ method: "GET", pathname: "/api/items", errorText: "ERR_ABORTED" }, { pathname: "/api/items" }), true);
  assert.equal(matchesExpectation({ method: "POST", pathname: "/api/items", errorText: "ERR_ABORTED" }, { method: "GET", pathname: "/api/items" }), false);
  assert.equal(matchesExpectation({ method: "GET", pathname: "/api/items", status: 503 }, { method: "GET", pathname: "/api/items", status: 503 }), true);
  assert.equal(matchesExpectation({ method: "GET", pathname: "/api/items", status: 500 }, { method: "GET", pathname: "/api/items", status: 503 }), false);
});

test("browser failure monitor rejects underconstrained local exceptions", () => {
  const monitor = createBrowserFailureMonitor(new FakePage(), { baseURL: "http://127.0.0.1:8899" });
  assert.throws(() => monitor.allowRequestFailed({ method: "GET", pathname: "/api/items" }), /requires errorText/);
  assert.throws(() => monitor.allowRequestFailed({ errorText: /ERR_ABORTED/ }), /requires method and pathname/);
  assert.throws(() => monitor.allowResponse({ method: "GET", pathname: "/api/items" }), /requires method, pathname, and integer status/);
  assert.throws(() => monitor.allowConsoleError({ errorText: /.*/ }), /catch-all/);
});

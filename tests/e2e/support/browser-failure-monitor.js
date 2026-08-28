"use strict";

function originFor(url) {
  return new URL(url).origin;
}

function requestDetails(request) {
  const url = new URL(request.url());
  return {
    method: request.method(),
    pathname: url.pathname,
    errorText: request.failure()?.errorText || "failed",
    origin: url.origin,
  };
}

function matchesExpectation(details, expectation) {
  if (expectation.method && details.method !== expectation.method) return false;
  if (expectation.pathname && details.pathname !== expectation.pathname) return false;
  if (expectation.status && details.status !== expectation.status) return false;
  if (expectation.errorText) {
    return expectation.errorText instanceof RegExp
      ? expectation.errorText.test(details.errorText)
      : details.errorText.includes(expectation.errorText);
  }
  return true;
}

function ensureSpecificErrorExpectation(kind, expectation) {
  if (!expectation || typeof expectation !== "object" || !expectation.errorText) {
    throw new TypeError(`${kind} expectation requires errorText`);
  }
  if (expectation.errorText instanceof RegExp && expectation.errorText.source === ".*") {
    throw new TypeError(`${kind} expectation must not use a catch-all errorText regex`);
  }
  return expectation;
}

function ensureSpecificRequestExpectation(kind, expectation) {
  if (!expectation || !expectation.method || !expectation.pathname) {
    throw new TypeError(`${kind} expectation requires method and pathname`);
  }
  return expectation;
}

function createBrowserFailureMonitor(page, { baseURL }) {
  const failures = [];
  const expectedRequestFailures = [];
  const expectedResponses = [];
  const expectedConsoleErrors = [];
  const expectedPageErrors = [];
  const sameOrigin = originFor(baseURL);

  function expected(expectations, details) {
    return expectations.some(expectation => matchesExpectation(details, expectation));
  }

  page.on("pageerror", error => {
    const details = { errorText: error.message };
    if (!expected(expectedPageErrors, details)) failures.push(`pageerror: ${error.message}`);
  });
  page.on("console", message => {
    if (message.type() !== "error") return;
    const details = { errorText: message.text() };
    if (!expected(expectedConsoleErrors, details)) failures.push(`console: ${message.text()}`);
  });
  page.on("requestfailed", request => {
    const details = requestDetails(request);
    if (details.origin !== sameOrigin || expected(expectedRequestFailures, details)) return;
    failures.push(`request: ${details.method} ${details.pathname} ${details.errorText}`);
  });
  page.on("response", response => {
    if (response.status() < 500) return;
    const request = response.request();
    const url = new URL(response.url());
    const details = { method: request.method(), pathname: url.pathname, origin: url.origin, status: response.status() };
    if (details.origin !== sameOrigin || expected(expectedResponses, details)) return;
    failures.push(`response: ${details.method} ${details.pathname} ${details.status}`);
  });

  return {
    allowRequestFailed(expectation) {
      expectedRequestFailures.push(ensureSpecificErrorExpectation(
        "request failure", ensureSpecificRequestExpectation("request failure", expectation),
      ));
    },
    allowResponse(expectation) {
      if (!expectation || !expectation.method || !expectation.pathname || !Number.isInteger(expectation.status)) {
        throw new TypeError("response expectation requires method, pathname, and integer status");
      }
      expectedResponses.push(expectation);
    },
    allowConsoleError(expectation) { expectedConsoleErrors.push(ensureSpecificErrorExpectation("console", expectation)); },
    allowPageError(expectation) { expectedPageErrors.push(ensureSpecificErrorExpectation("page error", expectation)); },
    failures,
    assertNoFailures() {
      if (failures.length) throw new Error(`Unexpected browser failures:\n${failures.join("\n")}`);
    },
  };
}

module.exports = { createBrowserFailureMonitor, matchesExpectation };

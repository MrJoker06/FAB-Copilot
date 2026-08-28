"use strict";

const { test: base, expect } = require("@playwright/test");
const { createBrowserFailureMonitor } = require("./browser-failure-monitor");

const test = base.extend({
  browserFailures: [async ({ page, baseURL }, use) => {
    const monitor = createBrowserFailureMonitor(page, { baseURL });
    let callbackError;
    try {
      await use(monitor);
    } catch (error) {
      callbackError = error;
      throw error;
    } finally {
      if (!callbackError) monitor.assertNoFailures();
    }
  }, { auto: true }],
});

module.exports = { test, expect };

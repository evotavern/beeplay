// Loaded before every other script in base.html so it also sees them fail to
// load. Sends what the page itself runs into to /api/client-error, where it is
// only logged; games carry their own reporter (game-reporter.js). It must
// never throw.
(function () {
  var MAX_REPORTS = 10;
  var sent = 0;

  function text(value, limit) {
    return value == null || value === "" ? null : String(value).slice(0, limit);
  }

  function report(kind, message, extra) {
    if (sent >= MAX_REPORTS) return;
    sent += 1;
    try {
      var body = { kind: kind, message: text(message, 1000) || kind, page: text(location.pathname, 300) };
      Object.keys(extra || {}).forEach(function (key) {
        if (extra[key] != null) body[key] = extra[key];
      });
      fetch("/api/client-error", {
        method: "POST",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }).catch(function () {});
    } catch (ignored) {}
  }

  window.beeplayReport = report;

  // Capture phase also sees resource failures, which do not bubble.
  window.addEventListener("error", function (event) {
    if (event instanceof ErrorEvent) {
      report("error", event.message, {
        source: text(event.filename, 500),
        line: event.lineno || null,
        column: event.colno || null,
        stack: text(event.error && event.error.stack, 4000)
      });
    } else if (event.target && event.target.tagName === "SCRIPT") {
      report("script", "script failed to load", { source: text(event.target.src, 500) });
    }
  }, true);

  window.addEventListener("unhandledrejection", function (event) {
    var reason = event.reason;
    report("rejection", reason && reason.message ? reason.message : String(reason), {
      stack: text(reason && reason.stack, 4000)
    });
  });
})();

// Inlined into every uploaded game's index.html by app/game_imports.py.
// Runs inside the game's sandboxed iframe and only ever talks to the parent
// page, which forwards to /api/game-health. It must never throw.
(function () {
  if (window.parent === window) return;
  function send(kind, detail) {
    try {
      window.parent.postMessage(
        { beeplay: kind, detail: detail == null ? null : String(detail).slice(0, 500) },
        "*"
      );
    } catch (ignored) {}
  }
  // Capture phase also sees resource failures, which do not bubble. Only a
  // script that fails to load counts; a missing image is not a crash.
  window.addEventListener("error", function (event) {
    if (event instanceof ErrorEvent) {
      send("error", (event.message || "error") + (event.filename ? " @ " + event.filename + ":" + event.lineno : ""));
    } else if (event.target && event.target.tagName === "SCRIPT") {
      send("error", "script failed to load: " + event.target.src);
    }
  }, true);
  window.addEventListener("unhandledrejection", function (event) {
    var reason = event.reason;
    send("error", "unhandled rejection: " + (reason && reason.message ? reason.message : reason));
  });
  window.addEventListener("load", function () { send("loaded"); });
})();

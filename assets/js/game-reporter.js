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
  function sendLayout() {
    try {
      var root = document.documentElement;
      var body = document.body;
      var width = Math.max(root.scrollWidth, body ? body.scrollWidth : 0);
      var height = Math.max(root.scrollHeight, body ? body.scrollHeight : 0);
      window.parent.postMessage({ beeplay: "layout", width: width, height: height }, "*");
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
  // Host lifecycle contract. Generated games can listen for the same
  // beeplayHost messages for richer pause/resume behavior; this fallback
  // handles ordinary media in imported games.
  window.addEventListener("message", function (event) {
    var data = event.data || {};
    if (!data.beeplayHost) return;
    try {
      document.querySelectorAll("audio, video").forEach(function (media) {
        if (data.beeplayHost === "deactivate") {
          media.dataset.beeplayWasPlaying = media.paused ? "0" : "1";
          media.pause();
        } else if (data.beeplayHost === "activate") {
          media.muted = !!data.muted;
          if (media.dataset.beeplayWasPlaying !== "0") media.play().catch(function () {});
        }
      });
      window.dispatchEvent(new CustomEvent("beeplay:lifecycle", { detail: data }));
      if (data.beeplayHost === "activate") {
        requestAnimationFrame(function () { requestAnimationFrame(sendLayout); });
      }
    } catch (ignored) {}
  });
  window.addEventListener("load", function () {
    send("loaded");
    requestAnimationFrame(function () { requestAnimationFrame(sendLayout); });
  });
})();

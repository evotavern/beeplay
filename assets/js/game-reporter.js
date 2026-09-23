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
  // Web Audio has no DOM element to pause, so remember every context the
  // game creates. This script runs before any game script.
  var audioContexts = [];
  ["AudioContext", "webkitAudioContext"].forEach(function (name) {
    var Native = window[name];
    if (typeof Native !== "function") return;
    function Tracked() {
      var context = new (Function.prototype.bind.apply(Native, [null].concat([].slice.call(arguments))))();
      audioContexts.push(context);
      return context;
    }
    Tracked.prototype = Native.prototype;
    try { window[name] = Tracked; } catch (ignored) {}
  });
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
  // Host lifecycle contract: the feed deactivates a game when it scrolls
  // away and activates it when it comes back. Only what was paused here is
  // resumed, so a game's own sound effects never start on activation.
  // Generated games can listen for beeplay:lifecycle for richer behavior.
  window.addEventListener("message", function (event) {
    var data = event.data || {};
    if (data.beeplayHost !== "activate" && data.beeplayHost !== "deactivate") return;
    var active = data.beeplayHost === "activate";
    try {
      document.querySelectorAll("audio, video").forEach(function (media) {
        if (!active && !media.paused) {
          media.dataset.beeplayPaused = "1";
          media.pause();
        } else if (active && media.dataset.beeplayPaused === "1") {
          delete media.dataset.beeplayPaused;
          media.play().catch(function () {});
        }
      });
      audioContexts.forEach(function (context) {
        if (!active && context.state === "running") {
          context.beeplayPaused = true;
          context.suspend().catch(function () {});
        } else if (active && context.beeplayPaused) {
          context.beeplayPaused = false;
          context.resume().catch(function () {});
        }
      });
      window.dispatchEvent(new CustomEvent("beeplay:lifecycle", { detail: data }));
    } catch (ignored) {}
  });
  window.addEventListener("load", function () { send("loaded"); });
})();

// Inlined first into every game's index.html by app/game_imports.py. It must
// never throw. Two jobs:
//
// Reporting: postMessages "loaded" and "error" to the host page, which
// forwards them to /api/game-health.
//
// Sandbox shim: games are written for a normal web page but run with an
// opaque origin (iframe sandbox="allow-scripts", and the same CSP when opened
// directly), which breaks them in ways the author never sees:
// - localStorage/sessionStorage throw SecurityError. They become in-memory
//   stand-ins, so a game keeps its settings for the session instead of
//   crashing or falling back to a default like "muted".
// - A tap on the host's play button is not a gesture inside the game, so
//   audio created at load stays suspended. The first tap in the game resumes
//   every AudioContext the game made.
// - A hidden game cannot tell it was hidden. The host sends
//   {beeplayHost: "pause"|"resume"|"mute"|"unmute"} and the audio is held
//   here. That is the whole host-to-game vocabulary.
(function () {
  var framed = window.parent !== window;

  // Each part is guarded on its own: whatever a browser lacks, reporting must
  // still be wired up at the end.
  try { shimStorage(); } catch (ignored) {}
  try { shimAudio(); } catch (ignored) {}
  if (!framed) return;

  // --- reporting ---------------------------------------------------------
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

  // --- storage -----------------------------------------------------------
  function memoryStorage() {
    var items = {};
    var has = function (key) { return Object.prototype.hasOwnProperty.call(items, key); };
    return {
      get length() { return Object.keys(items).length; },
      key: function (index) { var keys = Object.keys(items); return index < keys.length ? keys[index] : null; },
      getItem: function (key) { key = String(key); return has(key) ? items[key] : null; },
      setItem: function (key, value) { items[String(key)] = String(value); },
      removeItem: function (key) { delete items[String(key)]; },
      clear: function () { items = {}; }
    };
  }
  function shimStorage() {
    ["localStorage", "sessionStorage"].forEach(function (name) {
      try { window[name].getItem("beeplay"); return; } catch (denied) {}
      Object.defineProperty(window, name, { value: memoryStorage(), configurable: true });
    });
  }

  // --- audio -------------------------------------------------------------
  function shimAudio() {
    // Feed games play sound like feed videos, even with the iPhone ringer off.
    try { if (navigator.audioSession) navigator.audioSession.type = "playback"; } catch (ignored) {}

    var paused = false;     // host hid the game
    var muted = false;      // host mute button
    var contexts = [];      // [{context, resume}] every AudioContext the game made
    var held = [];          // entries of `contexts` suspended here, to resume later
    var media = [];         // media elements currently playing or held
    var heldMedia = [];     // elements paused here while the game is hidden
    var mutedBefore = typeof WeakMap === "function" ? new WeakMap() : null;
    var nativePlay = window.HTMLMediaElement && HTMLMediaElement.prototype.play;

    function silenced() { return paused || muted; }

    function hold(entry) {
      if (held.indexOf(entry) < 0) held.push(entry);
      try { entry.context.suspend().catch(function () {}); } catch (ignored) {}
    }

    function entryFor(context) {
      for (var i = 0; i < contexts.length; i++) if (contexts[i].context === context) return contexts[i];
      return null;
    }

    ["AudioContext", "webkitAudioContext"].forEach(function (name) {
      var Native = window[name];
      if (typeof Native !== "function" || Native.beeplayTracked) return;
      var nativeResume = Native.prototype.resume;
      function Tracked() {
        var context = Reflect.construct(Native, arguments, new.target || Tracked);
        var entry = { context: context, resume: nativeResume };
        contexts.push(entry);
        if (silenced()) hold(entry);
        return context;
      }
      Tracked.prototype = Native.prototype;
      Tracked.beeplayTracked = true;
      if (nativeResume && !nativeResume.beeplayTracked) {
        // While silenced, a game's own resume() is remembered, not obeyed.
        var resume = function () {
          var entry = entryFor(this);
          if (entry && silenced()) { hold(entry); return Promise.resolve(); }
          return nativeResume.apply(this, arguments);
        };
        resume.beeplayTracked = true;
        Native.prototype.resume = resume;
      }
      try { Object.defineProperty(window, name, { value: Tracked, configurable: true, writable: true }); } catch (ignored) {}
    });

    function forget(element) {
      var index = media.indexOf(element);
      if (index >= 0) media.splice(index, 1);
    }

    function muteElement(element) {
      if (!mutedBefore || mutedBefore.has(element)) return;
      mutedBefore.set(element, element.muted);
      element.muted = true;
    }

    if (nativePlay) {
      HTMLMediaElement.prototype.play = function () {
        if (media.indexOf(this) < 0) {
          media.push(this);
          this.addEventListener("ended", forget.bind(null, this));
        }
        if (muted) muteElement(this);
        if (paused) {
          if (heldMedia.indexOf(this) < 0) heldMedia.push(this);
          return Promise.resolve();
        }
        return nativePlay.apply(this, arguments);
      };
    }

    function apply() {
      contexts.forEach(function (entry) {
        if (silenced() && entry.context.state === "running") hold(entry);
      });
      if (!silenced()) {
        held.splice(0).forEach(function (entry) {
          try { entry.resume.call(entry.context).catch(function () {}); } catch (ignored) {}
        });
      }
      media.forEach(function (element) {
        if (paused && !element.paused) {
          if (heldMedia.indexOf(element) < 0) heldMedia.push(element);
          element.pause();
        }
        if (muted) muteElement(element);
        else if (mutedBefore && mutedBefore.has(element)) {
          element.muted = mutedBefore.get(element);
          mutedBefore.delete(element);
        }
      });
      if (!paused) {
        heldMedia.splice(0).forEach(function (element) {
          try { nativePlay.call(element).catch(function () {}); } catch (ignored) {}
        });
      }
    }

    // The first gesture inside the game is the first moment audio may start.
    var gestures = ["pointerdown", "touchend", "mousedown", "keydown"];
    function unlock() {
      gestures.forEach(function (type) { window.removeEventListener(type, unlock, true); });
      contexts.forEach(function (entry) {
        if (entry.context.state !== "suspended") return;
        if (silenced()) hold(entry);
        else try { entry.resume.call(entry.context).catch(function () {}); } catch (ignored) {}
      });
    }
    gestures.forEach(function (type) { window.addEventListener(type, unlock, true); });

    if (!framed) return;
    // Host commands.
    window.addEventListener("message", function (event) {
      if (event.source !== window.parent) return;
      var command = event.data && event.data.beeplayHost;
      if (command === "pause") paused = true;
      else if (command === "resume") paused = false;
      else if (command === "mute") muted = true;
      else if (command === "unmute") muted = false;
      else return;
      try { apply(); } catch (ignored) {}
    });
  }
})();

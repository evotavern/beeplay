// Inlined right after the reporter into games generated for head control
// (app/generation.py). It must never throw. It defines window.beeplay.head
// before the game's own code runs:
//
//   beeplay.head.x, .y     0..1 across and down the screen, 0.5 is the centre
//   beeplay.head.tilt      -1 (left) .. 1 (right)
//   beeplay.head.open      mouth open right now
//   beeplay.head.found     false while the camera sees no face
//   beeplay.head.camera    true while the camera drives it
//   beeplay.head.on("open" | "lost" | "found", fn)
//
// The game never touches the camera: the host page runs the face tracker
// (assets/js/head-camera.js) and posts {beeplayHead: {x, y, tilt, open,
// found}} on every frame, or {beeplayHead: null} when the camera goes off.
// Without a camera, dragging moves x/y (a mouse just hovering does too) and a
// tap is "open", so every head game is also a touch game. A tap does not move
// x/y: tapping to jump must not also teleport the player.
(function () {
  var head = { x: 0.5, y: 0.5, tilt: 0, open: false, found: true, camera: false };
  var listeners = { open: [], lost: [], found: [] };
  head.on = function (type, fn) {
    if (listeners[type] && typeof fn === "function") listeners[type].push(fn);
  };
  window.beeplay = window.beeplay || {};
  window.beeplay.head = head;

  function fire(type) {
    listeners[type].slice().forEach(function (fn) {
      // A game's own bug surfaces in the reporter, not here.
      try { fn(head); } catch (error) { setTimeout(function () { throw error; }); }
    });
  }

  function clamp(value, low, high) {
    value = Number(value);
    if (!isFinite(value)) return (low + high) / 2;
    return Math.min(high, Math.max(low, value));
  }

  function setFound(found) {
    if (found === head.found) return;
    head.found = found;
    fire(found ? "found" : "lost");
  }

  // The camera image sits behind the game, but only while the camera is on:
  // without it the game keeps the background it chose.
  var see = document.createElement("style");
  see.textContent = "html,body{background:transparent!important;color-scheme:normal!important}";
  function showCamera(on) {
    try {
      if (on && !see.parentNode) (document.head || document.documentElement).appendChild(see);
      if (!on && see.parentNode) see.parentNode.removeChild(see);
    } catch (ignored) {}
  }

  // --- touch and mouse ---------------------------------------------------
  var press = null;
  function point(event) {
    if (head.camera) return;
    head.x = clamp(event.clientX / (window.innerWidth || 1), 0, 1);
    head.y = clamp(event.clientY / (window.innerHeight || 1), 0, 1);
  }
  window.addEventListener("pointerdown", function (event) {
    if (!event.isPrimary) return;
    press = { x: event.clientX, y: event.clientY, at: Date.now(), moved: false };
  }, true);
  window.addEventListener("pointermove", function (event) {
    if (!event.isPrimary) return;
    if (press && Math.abs(event.clientX - press.x) + Math.abs(event.clientY - press.y) > 12) press.moved = true;
    if ((press && press.moved) || event.pointerType === "mouse") point(event);
  }, true);
  window.addEventListener("pointerup", function (event) {
    if (!event.isPrimary || !press) return;
    var tap = !press.moved && Date.now() - press.at < 400;
    press = null;
    if (tap) fire("open");
  }, true);
  window.addEventListener("pointercancel", function () { press = null; }, true);

  // --- camera, through the host ------------------------------------------
  if (window.parent === window) return;
  window.addEventListener("message", function (event) {
    if (event.source !== window.parent || !event.data || !("beeplayHead" in event.data)) return;
    var frame = event.data.beeplayHead;
    if (!frame) {
      head.camera = false;
      head.open = false;
      showCamera(false);
      setFound(true);
      return;
    }
    head.camera = true;
    showCamera(true);
    if (frame.found) {
      head.x = clamp(frame.x, 0, 1);
      head.y = clamp(frame.y, 0, 1);
      head.tilt = clamp(frame.tilt, -1, 1);
    }
    var opened = !!frame.open && !head.open;
    head.open = !!frame.open;
    setFound(!!frame.found);
    if (opened) fire("open");
  });

  // Tells the host this game takes head input, so it offers the camera. Said
  // more than once: the host page may still be starting when the game runs.
  function announce() {
    try { window.parent.postMessage({ beeplay: "head" }, "*"); } catch (ignored) {}
  }
  announce();
  document.addEventListener("DOMContentLoaded", announce);
  window.addEventListener("load", announce);
})();

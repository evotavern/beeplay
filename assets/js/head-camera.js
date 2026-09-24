// Camera head control for games generated with it (assets/js/head-api.js is
// the half inside the game). The page, not the game, opens the front camera
// and runs MediaPipe's face tracker: a game's sandbox allows neither the
// camera nor WebAssembly, and a game only ever receives numbers, never video.
//
//   BeeHead.attach(stage, frame, area)  show the mirrored camera behind this
//                                       game frame and stream head input to it
//   BeeHead.detach()                    and stop: the camera is off outside
//                                       head games
//   BeeHead.toggle()                    the "📷 用头玩" button, any
//                                       [data-head-toggle] element
//
// Once a player turns the camera on it comes back on for every head game they
// reach, until they turn it off. Nothing is loaded before the first tap: the
// tracker is ~15 MB (about 7 MB compressed).
(function () {
  "use strict";

  var files = document.currentScript.dataset;
  var LABELS = { off: "📷 用头玩", starting: "📷 打开中…", on: "🔴 关闭摄像头" };
  // Head position is scaled up around the centre: nobody moves their head
  // to the edge of the picture.
  var GAIN = 2;
  var SMOOTHING = 0.5;
  var TILT_FULL = Math.PI / 6;       // 30° of roll is tilt 1
  var OPEN_AT = 0.35, CLOSE_AT = 0.2; // jawOpen, with hysteresis
  var LOST_AFTER_MS = 300;

  var state = "off";
  var wanted = false;
  var stream = null;
  var landmarker = null;
  var loading = null;
  var run = 0;                        // bumped by stop(), cancels a start in flight

  // {stage, frame, area, layer, video, canvas, note}. The mirror video is
  // also what the tracker reads: iOS may not decode a video off the page.
  var view = null;
  var head = { x: 0.5, y: 0.5, tilt: 0, open: false, found: false };
  var seenAt = 0, lastVideoTime = -1, lastDetectAt = 0, loop = 0;

  function clamp(value) { return Math.min(1, Math.max(0, value)); }

  function setState(next) {
    state = next;
    document.querySelectorAll("[data-head-toggle]").forEach(function (button) {
      button.textContent = LABELS[state];
      button.classList.toggle("head-on", state !== "off");
      button.setAttribute("aria-pressed", state === "off" ? "false" : "true");
    });
    if (view) view.stage.classList.toggle("head-live", state !== "off");
    if (state === "off") send(null);
  }

  function send(frame) {
    if (!view || !view.frame.contentWindow) return;
    view.frame.contentWindow.postMessage({ beeplayHead: frame }, "*");
  }

  function note(text) {
    if (!view) return;
    view.note.textContent = text || "";
    view.note.hidden = !text;
  }

  // --- what the player sees ------------------------------------------------
  function attach(stage, frame, area) {
    if (view && view.stage === stage && view.frame === frame) return;
    detach();
    var layer = document.createElement("div");
    layer.className = "head-mirror";
    var video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.setAttribute("playsinline", "");
    var canvas = document.createElement("canvas");
    layer.appendChild(video);
    layer.appendChild(canvas);
    var hint = document.createElement("p");
    hint.className = "head-note";
    hint.hidden = true;
    stage.insertBefore(layer, stage.firstChild);
    stage.appendChild(hint);
    view = { stage: stage, frame: frame, area: area, layer: layer, video: video, canvas: canvas, note: hint };
    setState(state);
    if (wanted && state === "off") start();
  }

  function detach() {
    if (!view) return;
    stop();
    view.layer.remove();
    view.note.remove();
    view.stage.classList.remove("head-live");
    view = null;
  }

  // The face outline, drawn over the camera picture so players can see it
  // tracks them. The canvas is mirrored by CSS, like the video.
  function draw(face) {
    if (!view) return;
    var canvas = view.canvas, video = view.video;
    var ratio = Math.min(2, window.devicePixelRatio || 1);
    var width = view.stage.clientWidth, height = view.stage.clientHeight;
    if (canvas.width !== Math.round(width * ratio)) canvas.width = Math.round(width * ratio);
    if (canvas.height !== Math.round(height * ratio)) canvas.height = Math.round(height * ratio);
    var context = canvas.getContext("2d");
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (!face || !video.videoWidth) return;
    // Same mapping as the video's object-fit: cover.
    var scale = Math.max(width / video.videoWidth, height / video.videoHeight);
    var left = (width - video.videoWidth * scale) / 2;
    var top = (height - video.videoHeight * scale) / 2;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.strokeStyle = "rgba(181, 214, 90, 0.9)";
    context.lineWidth = 3;
    context.lineCap = "round";
    context.beginPath();
    window.Vision.FaceLandmarker.FACE_LANDMARKS_FACE_OVAL.forEach(function (edge) {
      var a = face[edge.start], b = face[edge.end];
      context.moveTo(left + a.x * video.videoWidth * scale, top + a.y * video.videoHeight * scale);
      context.lineTo(left + b.x * video.videoWidth * scale, top + b.y * video.videoHeight * scale);
    });
    context.stroke();
  }

  // --- tracking ------------------------------------------------------------
  function read(result, now) {
    var video = view.video;
    var face = result.faceLandmarks && result.faceLandmarks[0];
    if (face) {
      seenAt = now;
      var nose = face[1], right = face[33], left = face[263];
      // Mirrored, so moving right moves right on screen.
      var x = clamp(0.5 + (0.5 - nose.x) * GAIN);
      var y = clamp(0.5 + (nose.y - 0.5) * GAIN);
      var roll = Math.atan2((right.y - left.y) * video.videoHeight, (left.x - right.x) * video.videoWidth);
      var tilt = Math.max(-1, Math.min(1, roll / TILT_FULL));
      if (!head.found) { head.x = x; head.y = y; head.tilt = tilt; }
      head.x += (x - head.x) * SMOOTHING;
      head.y += (y - head.y) * SMOOTHING;
      head.tilt += (tilt - head.tilt) * SMOOTHING;
      var jaw = 0;
      var shapes = result.faceBlendshapes && result.faceBlendshapes[0];
      (shapes ? shapes.categories : []).forEach(function (shape) {
        if (shape.categoryName === "jawOpen") jaw = shape.score;
      });
      head.open = head.open ? jaw > CLOSE_AT : jaw > OPEN_AT;
      head.found = true;
    } else if (head.found && now - seenAt > LOST_AFTER_MS) {
      head.found = false;
      head.open = false;
    }
    note(head.found ? "" : "看不到你 👀 把脸放进画面里");
    draw(face);
    send({ x: head.x, y: head.y, tilt: head.tilt, open: head.open, found: head.found });
  }

  function tick() {
    if (state !== "on") return;
    // The game's card left the page (another view): let the camera go.
    if (!view.stage.isConnected) { detach(); return; }
    loop = requestAnimationFrame(tick);
    var now = performance.now();
    var video = view.video;
    // About 30 detections a second, and only on new video frames.
    if (video.readyState < 2 || now - lastDetectAt < 30 || video.currentTime === lastVideoTime) return;
    lastDetectAt = now;
    lastVideoTime = video.currentTime;
    try {
      read(landmarker.detectForVideo(video, now), now);
    } catch (error) {
      fail("failed", error);
    }
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = src;
      script.onload = resolve;
      script.onerror = function () { reject(new Error("script failed to load: " + src)); };
      document.head.appendChild(script);
    });
  }

  // Loaded once per page; the GPU path is not there in every in-app browser.
  function load() {
    if (landmarker) return Promise.resolve(landmarker);
    if (!loading) {
      loading = (window.Vision ? Promise.resolve() : loadScript(files.bundle))
        .then(function () { return window.Vision.FilesetResolver.isSimdSupported(); })
        .then(function (simd) {
          if (!simd) throw Object.assign(new Error("no WebAssembly SIMD"), { code: "unsupported" });
          var fileset = { wasmLoaderPath: files.loader, wasmBinaryPath: files.wasm };
          var options = {
            baseOptions: { modelAssetPath: files.model, delegate: "GPU" },
            runningMode: "VIDEO", numFaces: 1, outputFaceBlendshapes: true
          };
          return window.Vision.FaceLandmarker.createFromOptions(fileset, options).catch(function () {
            options.baseOptions.delegate = "CPU";
            return window.Vision.FaceLandmarker.createFromOptions(fileset, options);
          });
        })
        .then(function (created) { landmarker = created; return created; })
        .catch(function (error) { loading = null; throw error; });
    }
    return loading;
  }

  function start() {
    if (state !== "off" || !view) return;
    var ticket = ++run;
    setState("starting");
    note("正在打开摄像头…");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      fail("unsupported");
      return;
    }
    navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }
    }).then(function (opened) {
      if (ticket !== run) { opened.getTracks().forEach(function (track) { track.stop(); }); return; }
      stream = opened;
      view.video.srcObject = stream;
      note("正在准备识别，第一次要几秒…");
      return Promise.all([load(), view.video.play()]).then(function () {
        if (ticket !== run) return;
        head.found = false;
        seenAt = performance.now();
        setState("on");
        tick();
      });
    }).catch(function (error) {
      if (ticket !== run) return;
      var code = error && error.code === "unsupported" ? "unsupported"
        : error && (error.name === "NotAllowedError" || error.name === "SecurityError") ? "denied"
        : error && (error.name === "NotFoundError" || error.name === "OverconstrainedError") ? "nocamera"
        : "failed";
      fail(code, error);
    });
  }

  function stop() {
    run += 1;
    cancelAnimationFrame(loop);
    if (stream) stream.getTracks().forEach(function (track) { track.stop(); });
    stream = null;
    if (view) {
      view.video.srcObject = null;
      draw(null);
      note("");
    }
    head.found = false;
    head.open = false;
    lastVideoTime = -1;
    if (state !== "off") setState("off");
  }

  var inApp = /MicroMessenger|QQ\/|aweme|Douyin/i.test(navigator.userAgent);
  var MESSAGES = {
    unsupported: inApp
      ? "这个 App 里用不了摄像头。点右上角「···」用浏览器打开，或者继续用手指玩。"
      : "这个浏览器用不了摄像头，继续用手指玩吧。",
    denied: "没有摄像头权限，继续用手指玩吧。",
    nocamera: "没找到前置摄像头，继续用手指玩吧。",
    failed: "摄像头没能打开，继续用手指玩吧。"
  };

  function fail(code, error) {
    var area = view ? view.area : "gameplay";
    wanted = false;
    stop();
    var text = MESSAGES[code] || MESSAGES.failed;
    note(text);
    var shown = view;
    setTimeout(function () { if (view === shown && state === "off") note(""); }, 5000);
    // The player's own "no" is not a bug; everything else is.
    if (code !== "denied" && window.beeplayReport) {
      var reason = error ? String(error.name || "Error") + ": " + String(error.message || error).slice(0, 300) : code;
      window.beeplayReport("shown", text + " (" + reason + ")", { area: area, next: "stayed", lost: false });
    }
  }

  function toggle() {
    if (!view) return;
    if (state === "off") {
      wanted = true;
      start();
    } else {
      wanted = false;
      stop();
    }
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest && event.target.closest("[data-head-toggle]")) toggle();
  });
  // A hidden page gives the camera back; it comes back with the page.
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop();
    else if (wanted && view) start();
  });
  window.addEventListener("pagehide", stop);

  window.BeeHead = { attach: attach, detach: detach, toggle: toggle };
})();

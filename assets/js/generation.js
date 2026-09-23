(function () {
  "use strict";
  var job = null, configured = false, loaded = false, starting = false;
  var epoch = 0, polling = false, saveTimer, saveChain = Promise.resolve(), requestId = null;
  var overlay, frame, previewStart = 0, previewJob = null, loadTimer, eventCount = 0;
  var statusMessages = {queued: "已排队，先来完善游戏信息。", generating: "Bee 正在编写玩法，你可以继续填写信息。", validating: "正在整理游戏，马上就能试玩。", ready: "游戏准备好了！完善信息后，亲自试玩一下。", published: "已发布！大家可以在首页玩到你的游戏了。"};
  var errors = {keys_unavailable: "生成额度暂时不可用，请稍后重试或联系管理员。", provider_connection_failed: "生成连接中断，请重试。你填写的信息还在。", provider_error: "生成服务暂时出错，请稍后重试。", invalid_game: "这次没能生成完整的游戏，请重新生成。", interrupted: "服务重启中断了这次生成，请重新生成。", internal_error: "生成出了点问题，请重新生成。"};
  function root() { return document.getElementById("createView"); }
  function el(id) { return document.getElementById(id); }
  function active() { return job && ["queued", "generating", "validating"].indexOf(job.status) >= 0; }
  function message(text, error) { if (el("generationStatus")) { el("generationStatus").textContent = text; el("generationStatus").dataset.error = error ? "true" : "false"; } }
  function storage(key, value) { try { if (value !== undefined) sessionStorage.setItem(key, JSON.stringify(value)); else return JSON.parse(sessionStorage.getItem(key) || "null"); } catch (_) { return null; } }
  async function api(path, method, body, keepalive) {
    var response = await fetch("/api/generations" + path, {method: method || "GET", credentials: "same-origin", cache: "no-store", headers: body === undefined ? {} : {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body), keepalive: !!keepalive});
    if (response.status === 401) throw new Error("请先认领一个身份，再回来继续创作。");
    if (response.status === 204) return null;
    var data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "请求未完成，请检查输入后重试。");
    return data;
  }
  function readDetails() {
    var form = el("generationDetails"), data = {};
    if (!form) return job ? job.details : {};
    new FormData(form).forEach(function (value, key) { data[key] = value; });
    return data;
  }
  function fillDetails(data) {
    var form = el("generationDetails");
    if (!form) return;
    Object.keys(data || {}).forEach(function (key) { if (form.elements.namedItem(key)) form.elements.namedItem(key).value = data[key] || ""; });
  }
  function hydrate() {
    if (!root()) return;
    el("ideaInput").value = job ? job.prompt : (storage("beeplay-prompt") || "");
    if (job) fillDetails(storage("beeplay-details-" + job.id) || job.details);
    render();
  }
  function render() {
    if (!root()) return;
    el("ideaSubmit").disabled = !loaded || starting || !!job || !configured;
    el("ideaInput").disabled = !!job || starting;
    el("generationDetails").hidden = !job;
    el("generationInspiration").hidden = !!job;
    el("generationProgress").hidden = !active();
    el("generationPlay").disabled = !job || job.status !== "ready";
    el("generationRetry").hidden = !job || job.status !== "failed";
    el("generationNew").hidden = !job || ["ready", "published", "failed"].indexOf(job.status) < 0;
    el("generationDetails").querySelectorAll("input").forEach(function (input) { input.disabled = !!job && job.status === "published"; });
    if (job) {
      message(job.status === "failed" ? (errors[job.error] || "生成未完成，请重试。") : statusMessages[job.status], job.status === "failed");
      el("generationElapsed").textContent = "已用 " + Math.floor(job.elapsed_ms / 1000) + " 秒";
    } else if (!root().dataset.creator) {
      message("先认领一个身份，就能开始创作。");
      el("ideaSubmit").disabled = false;
    } else if (loaded) message(configured ? "准备好了，写下你的游戏想法。" : "生成服务尚未配置，请联系管理员添加 API key。", !configured);
  }
  async function mount() {
    var ticket = ++epoch;
    if (!root()) return;
    loaded = false; render();
    if (!root().dataset.creator) { loaded = true; render(); return; }
    try {
      var data = await api("/current");
      if (ticket !== epoch || !root()) return;
      job = data.job; configured = data.configured; loaded = true;
      hydrate();
      // Restore a last local edit that had not reached the server before reload.
      if (job && job.status !== "published" && storage("beeplay-details-" + job.id)) saveDetails().catch(function () {});
    } catch (error) { if (ticket === epoch) message(error.message, true); }
  }
  function saveDetails() {
    clearTimeout(saveTimer);
    if (!job || job.status === "published") return Promise.resolve();
    var id = job.id, details = readDetails();
    storage("beeplay-details-" + id, details);
    saveChain = saveChain.catch(function () {}).then(async function () {
      try {
        await api("/" + id + "/details", "PUT", details);
        if (job && job.id === id && el("generationSave")) el("generationSave").textContent = "信息已保存";
      } catch (error) {
        if (el("generationSave")) el("generationSave").textContent = "尚未同步，信息已保留在此浏览器。";
        throw error;
      }
    });
    return saveChain;
  }
  async function start(retry) {
    if (!root() || starting) return;
    if (!root().dataset.creator) { storage("beeplay-prompt", el("ideaInput").value); window.location.href = "/claim"; return; }
    var prompt = el("ideaInput").value.trim();
    if (!prompt) { el("ideaInput").focus(); message("先写下一句想法吧"); return; }
    var previous = retry ? readDetails() : null;
    starting = true; render(); message("正在开始创作…");
    requestId = requestId || crypto.randomUUID();
    try {
      job = await api("", "POST", {prompt: prompt, request_id: requestId});
      requestId = null; storage("beeplay-prompt", prompt);
      hydrate();
      if (previous) { fillDetails(previous); await saveDetails(); }
    } catch (error) { message(error.message, true); }
    finally { starting = false; if (el("ideaSubmit")) el("ideaSubmit").disabled = !!job || !configured; }
  }
  window.BeeGeneration = {start: function () { start(false); }};
  async function signal(kind, elapsed, keepalive) {
    if (!previewJob || eventCount >= 100) return;
    eventCount++;
    return api("/" + previewJob + "/events", "POST", {kind: kind, elapsed_ms: Math.min(86400000, Math.max(0, Math.round(elapsed || 0)))}, keepalive);
  }
  function ensureOverlay() {
    if (overlay) return;
    overlay = document.createElement("section"); overlay.className = "generation-playtest"; overlay.hidden = true;
    overlay.setAttribute("role", "dialog"); overlay.setAttribute("aria-modal", "true"); overlay.setAttribute("aria-label", "试玩你的游戏");
    overlay.innerHTML = '<div class="generation-playtest-bar"><button class="generation-playtest-close" type="button">← 返回修改信息</button><strong>亲自试玩</strong><button class="generation-publish" type="button" disabled>发布到游戏流 →</button></div><p class="generation-playtest-message" role="status">正在加载游戏…</p>';
    document.body.appendChild(overlay);
    overlay.querySelector(".generation-playtest-close").onclick = closePreview;
    overlay.querySelector(".generation-publish").onclick = publish;
  }
  function previewMessage(text) { overlay.querySelector(".generation-playtest-message").textContent = text; }
  async function play() {
    if (!job || job.status !== "ready" || !el("generationDetails").reportValidity()) return;
    try { await saveDetails(); } catch (error) { message(error.message, true); return; }
    ensureOverlay(); overlay.hidden = false; document.body.style.overflow = "hidden";
    previewJob = job.id; previewStart = performance.now(); eventCount = 0;
    overlay.querySelector(".generation-publish").disabled = true;
    previewMessage("正在加载游戏…");
    frame = document.createElement("iframe"); frame.title = "试玩生成的游戏";
    frame.setAttribute("sandbox", "allow-scripts"); frame.referrerPolicy = "no-referrer";
    frame.src = job.preview_url; overlay.appendChild(frame);
    signal("playtest_opened", 0).catch(function () {});
    loadTimer = setTimeout(function () { previewMessage("加载时间有点长，可以返回后再次试玩。"); signal("playtest_timeout", performance.now() - previewStart).catch(function () {}); }, 15000);
    document.querySelector(".app-shell").inert = true;
    document.querySelector(".bottom-nav").inert = true;
    overlay.querySelector(".generation-playtest-close").focus();
  }
  function closePreview() {
    if (!overlay || overlay.hidden) return;
    signal("playtest_closed", performance.now() - previewStart, true).catch(function () {});
    clearTimeout(loadTimer); if (frame) frame.remove(); frame = null; previewJob = null;
    overlay.hidden = true; document.body.style.overflow = "";
    document.querySelector(".app-shell").inert = false;
    document.querySelector(".bottom-nav").inert = false;
    if (el("generationPlay")) el("generationPlay").focus();
  }
  async function publish() {
    var button = overlay.querySelector(".generation-publish"); button.disabled = true;
    previewMessage("正在发布…");
    try {
      await api("/" + previewJob + "/publish", "POST", readDetails());
      closePreview(); job.status = "published"; render();
      window.location.href = "/";
    } catch (error) { previewMessage(error.message); button.disabled = false; }
  }
  window.addEventListener("message", function (event) {
    if (!frame || event.source !== frame.contentWindow || !event.data) return;
    var kind = event.data.beeplay, id = previewJob;
    if (kind === "loaded") {
      clearTimeout(loadTimer);
      signal("playtest_loaded", performance.now() - previewStart).then(function () {
        if (previewJob !== id || !frame) return;
        overlay.querySelector(".generation-publish").disabled = false;
        previewMessage("试试操作、得分和重新开始。满意后再发布。");
      }).catch(function (error) { previewMessage(error.message); });
    } else if (kind === "error") {
      signal("playtest_error", performance.now() - previewStart).catch(function () {});
      previewMessage("游戏报告了运行错误。建议返回检查，或重新创作。");
    }
  });
  document.addEventListener("click", function (event) {
    if (event.target.closest("#generationPlay")) play();
    if (event.target.closest("#generationRetry")) start(true);
    if (event.target.closest("#generationNew")) { job = null; requestId = null; storage("beeplay-prompt", ""); el("generationDetails").reset(); hydrate(); el("ideaInput").focus(); }
  });
  document.addEventListener("submit", function (event) { if (event.target.id === "generationDetails") event.preventDefault(); });
  document.addEventListener("input", function (event) {
    if (event.target.closest("#generationDetails") && job) {
      storage("beeplay-details-" + job.id, readDetails());
      if (el("generationSave")) el("generationSave").textContent = "正在保存…";
      clearTimeout(saveTimer); saveTimer = setTimeout(function () { saveDetails().catch(function () {}); }, 400);
    }
  });
  document.addEventListener("keydown", function (event) { if (event.key === "Escape") closePreview(); });
  window.addEventListener("pagehide", closePreview);
  document.body.addEventListener("htmx:beforeSwap", function () { if (root() && job) { saveDetails().catch(function () {}); closePreview(); } });
  document.body.addEventListener("htmx:afterSwap", mount);
  document.body.addEventListener("htmx:historyRestore", mount);
  setInterval(async function () {
    if (!root() || !job || !active() || polling) return;
    polling = true; var id = job.id;
    try { var data = await api("/" + id); if (job && job.id === id) { job = data; render(); } }
    catch (error) { message(error.message, true); }
    finally { polling = false; }
  }, 1200);
  mount();
})();

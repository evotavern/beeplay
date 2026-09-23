(function () {
  "use strict";

  var modal = document.getElementById("createModal");
  var toast = document.getElementById("toast");
  var toastTimer;
  var feedWheelLocked = false;

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.classList.remove("show"); }, 2200);
  }

  // The swapped-in section is the only .view in the DOM, so it *is* the state.
  function currentView() {
    var view = document.querySelector("#viewport .view");
    return view ? view.dataset.view : "home";
  }

  // Nav and body live outside #viewport, so htmx never touches them.
  function syncChrome() {
    var view = currentView();
    document.querySelectorAll(".nav-item, .desktop-nav button").forEach(function (nav) {
      nav.classList.toggle("active", nav.dataset.viewTarget === view);
    });
    document.body.classList.toggle("feed-mode", view === "home");
  }

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target.id !== "viewport") return;
    syncChrome();
    window.scrollTo({ top: 0, behavior: "smooth" });
    setTimeout(scrollToSharedGame, 0);
  });

  // A history restore swaps #viewport without firing htmx:afterSwap, and the
  // chrome it leaves behind belongs to the page we navigated away from — a
  // stale nav highlight, and a missing body.feed-mode that unlocks page scroll
  // underneath the feed. htmx restores the scroll position itself, so only the
  // chrome needs resyncing here.
  document.body.addEventListener("htmx:historyRestore", syncChrome);

  function openCreateModal() {
    showCreateChoices();
    modal.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  function closeCreateModal() {
    modal.classList.remove("open");
    document.body.style.overflow = "";
  }

  var importGameForm = document.getElementById("importGameForm");
  var createChoices = document.getElementById("createChoices");
  var importGameZip = document.getElementById("importGameZip");
  var importGameFolder = document.getElementById("importGameFolder");
  var importDropzone = document.getElementById("importDropzone");
  var importSubmit = importGameForm.querySelector("[type='submit']");
  var importSelection = null;

  function setCreateModalCopy(title, description) {
    document.getElementById("createModalTitle").textContent = title;
    document.getElementById("createModalDescription").textContent = description;
  }

  function showImportGame() {
    createChoices.hidden = true;
    importGameForm.hidden = false;
    setCreateModalCopy("导入一个小游戏", "把已经做好的游戏放进你的首页游戏流。");
  }

  function showCreateChoices() {
    importGameForm.hidden = true;
    createChoices.hidden = false;
    importGameForm.reset();
    importSubmit.disabled = false;
    importSelection = null;
    document.getElementById("importSelection").textContent = "拖入一个 zip 游戏包";
    document.getElementById("importStatus").textContent = "";
    setCreateModalCopy("你想玩什么？", "选择一个入口，马上开始你的 Bee。");
  }

  var importProgress = document.getElementById("importProgress");

  function megabytes(bytes) {
    return (bytes / 1048576).toFixed(1);
  }

  // Upload progress needs XMLHttpRequest: fetch() cannot observe the request
  // body leaving the browser. Resolves with a fetch-like response so the
  // handling below reads the same either way.
  function postWithProgress(url, data, onProgress) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", url);
      xhr.upload.onprogress = function (event) {
        if (event.lengthComputable) onProgress(event.loaded, event.total);
      };
      xhr.upload.onload = function () { onProgress(1, 1); };
      xhr.onload = function () {
        resolve({
          ok: xhr.status >= 200 && xhr.status < 300,
          status: xhr.status,
          json: function () {
            return new Promise(function (done) { done(JSON.parse(xhr.responseText)); });
          }
        });
      };
      xhr.onerror = function () { reject(new Error("网络断开了，上传没有完成，请重试")); };
      xhr.send(data);
    });
  }

  function reportUploadFailure(error, status) {
    if (!window.beeplayReport || !importSelection) return;
    var bytes = importSelection.files.reduce(function (sum, file) { return sum + file.size; }, 0);
    window.beeplayReport("upload", error.message + " (" + (status ? "HTTP " + status : "no response") + ", "
      + importSelection.kind + " " + importSelection.files.length + " files "
      + (bytes / 1048576).toFixed(1) + " MB)");
  }

  function showUploadProgress(loaded, total) {
    var status = document.getElementById("importStatus");
    importProgress.hidden = false;
    if (total && loaded >= total) {
      importProgress.removeAttribute("value");
      status.textContent = "上传完成，正在放进游戏流…";
      return;
    }
    importProgress.value = total ? loaded / total : 0;
    status.textContent = total
      ? "正在上传… " + Math.round(100 * loaded / total) + "%（" + megabytes(loaded) + " / " + megabytes(total) + " MB）"
      : "正在上传…";
  }

  function selectImport(kind, files) {
    if (!files.length) return;
    importSelection = { kind: kind, files: [].slice.call(files) };
    document.getElementById("importSelection").textContent =
      kind === "zip" ? "已选择 " + files[0].name : "已选择 " + files.length + " 个游戏文件";
    document.getElementById("importStatus").textContent = "已就绪，加入后会出现在首页游戏流。";
  }

  // --- feed navigation -------------------------------------------------
  // Re-queried per call: the feed is destroyed and rebuilt on every swap.
  function moveFeed(direction) {
    var feed = document.getElementById("homeFeed");
    var cards = [].slice.call(document.querySelectorAll(".game-card"));
    if (!feed || !cards.length) return;
    var currentIndex = Math.max(0, cards.findIndex(function (card) {
      return Math.abs(card.getBoundingClientRect().top - feed.getBoundingClientRect().top) < 40;
    }));
    var nextIndex = Math.min(cards.length - 1, Math.max(0, currentIndex + direction));
    cards[nextIndex].scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function scrollToSharedGame() {
    if (currentView() !== "home") return;
    var artifact = new URLSearchParams(window.location.search).get("game");
    if (!artifact) return;
    var card = document.querySelector('.game-card[data-artifact="' + CSS.escape(artifact) + '"]');
    if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function interactionId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return Date.now().toString(36) + Math.random().toString(36).slice(2);
  }

  function socialFetch(workId, action, body) {
    return fetch("/api/works/" + workId + "/" + action, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (response) {
      if (response.status === 401) {
        window.location.href = "/claim";
        throw new Error("identity required");
      }
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok) throw new Error(payload.detail || "操作没有保存，请重试");
        return payload;
      });
    });
  }

  function renderToggle(button, active) {
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }

  async function updateToggle(button, card, action, title) {
    if (button.disabled) return;
    button.disabled = true;
    var active = !button.classList.contains("active");
    try {
      var result = await socialFetch(card.dataset.gameId, action, { active: active });
      renderToggle(button, result.active);
      var counter = button.querySelector("[data-social-count='likes']");
      if (counter && typeof result.count === "number") counter.textContent = result.count;
      showToast(result.active
        ? (action === "like" ? "已喜欢 " : "已收藏 ") + title
        : (action === "like" ? "已取消喜欢" : "已取消收藏"));
    } catch (error) {
      if (error.message !== "identity required") showToast(error.message);
    } finally {
      button.disabled = false;
    }
  }

  async function copyShareUrl(url) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(url);
      return true;
    }
    var field = document.createElement("textarea");
    field.value = url;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    var copied = document.execCommand("copy");
    field.remove();
    return copied;
  }

  async function shareGame(button, card, title) {
    if (button.disabled) return;
    button.disabled = true;
    var url = new URL("/", window.location.origin);
    url.searchParams.set("game", card.dataset.artifact);
    var completed = false;
    try {
      if (navigator.share) {
        await navigator.share({ title: title, text: "来 BeePlay 玩玩 “" + title + "”", url: url.href });
        completed = true;
      } else {
        completed = await copyShareUrl(url.href);
      }
      if (!completed) throw new Error("没有复制成功，请重试");
      showToast(navigator.share ? "已分享 " + title : "分享链接已复制");
      // The share already happened; failing to count it must not read as a failed share.
      try {
        var result = await socialFetch(card.dataset.gameId, "share", { event_id: interactionId() });
        var counter = button.querySelector("[data-social-count='shares']");
        if (counter && typeof result.count === "number") counter.textContent = result.count;
      } catch (recordError) {}
    } catch (error) {
      if (error.name !== "AbortError") showToast(error.message || "分享没有完成");
    } finally {
      button.disabled = false;
    }
  }

  document.addEventListener("wheel", function (event) {
    if (!event.target.closest || !event.target.closest(".home-feed")) return;
    if (Math.abs(event.deltaY) < 8 || feedWheelLocked || gamePlaying()) return;
    event.preventDefault();
    feedWheelLocked = true;
    moveFeed(event.deltaY > 0 ? 1 : -1);
    setTimeout(function () { feedWheelLocked = false; }, 520);
  }, { passive: false });

  // --- delegated clicks ------------------------------------------------
  // Everything below is delegated from document so it survives htmx swaps.
  document.addEventListener("click", function (event) {
    var target = event.target;

    var gameAction = target.closest("[data-game-action]");
    if (gameAction) {
      var gameCard = gameAction.closest(".game-card");
      var title = (gameCard && gameCard.dataset.gameTitle) || "这个游戏";
      var action = gameAction.dataset.gameAction;
      if (action === "play") {
        togglePlay(gameCard, gameAction, title);
      } else if (action === "like" || action === "save") {
        updateToggle(gameAction, gameCard, action, title);
      } else if (action === "share") {
        shareGame(gameAction, gameCard, title);
      }
      return;
    }

    if (target.closest("[data-action='create']")) {
      openCreateModal();
      return;
    }

    // htmx swaps the grid; the pill row stays put, so mark the active pill here.
    var pill = target.closest(".category-pill");
    if (pill) {
      document.querySelectorAll(".category-pill").forEach(function (item) {
        item.classList.remove("active");
      });
      pill.classList.add("active");
      return;
    }

    var profileTab = target.closest("[data-profile-tab]");
    if (profileTab) {
      document.querySelectorAll("[data-profile-tab]").forEach(function (item) {
        item.classList.remove("active");
      });
      profileTab.classList.add("active");
      return;
    }

    var taskCheck = target.closest(".task-check");
    if (taskCheck) {
      var row = taskCheck.closest(".task-row");
      row.classList.toggle("complete");
      var complete = row.classList.contains("complete");
      taskCheck.textContent = complete ? "✓" : "○";
      showToast(complete ? "任务完成，蜂蜜积分 +10" : "已取消完成状态");
      return;
    }

    var fill = target.closest("[data-fill]");
    if (fill) {
      var ideaInput = document.getElementById("ideaInput");
      ideaInput.value = fill.dataset.fill;
      ideaInput.focus();
      return;
    }

    var tool = target.closest("[data-tool]");
    if (tool) {
      tool.classList.toggle("active");
      return;
    }

    if (target.closest("#ideaSubmit")) {
      var input = document.getElementById("ideaInput");
      if (!input.value.trim()) {
        input.focus();
        showToast("先写下一句想法吧");
        return;
      }
      if (window.BeeGeneration) window.BeeGeneration.start();
      return;
    }

    if (target.closest("#enableNotifications")) {
      if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission().then(function (permission) {
          showToast(permission === "granted" ? "通知已开启" : "你可以稍后在浏览器设置中开启");
        });
      } else {
        showToast("通知偏好已更新");
      }
      return;
    }

    if (target.closest("#creditPill")) {
      showToast("你的蜂蜜积分余额：1,000");
      return;
    }

    var toastTarget = target.closest("[data-toast]");
    if (toastTarget) showToast(toastTarget.dataset.toast);
  });

  // --- discover search -------------------------------------------------
  // Filters the cards htmx rendered; input bubbles, so delegation works.
  document.addEventListener("input", function (event) {
    if (event.target.id !== "searchInput") return;
    var keyword = event.target.value.trim().toLowerCase();
    document.querySelectorAll("#workGrid .work-card").forEach(function (card) {
      card.style.display = !keyword || card.dataset.workTitle.indexOf(keyword) !== -1 ? "" : "none";
    });
  });

  // --- create modal ----------------------------------------------------
  document.getElementById("closeModal").addEventListener("click", closeCreateModal);

  modal.addEventListener("click", function (event) {
    if (event.target === modal) { closeCreateModal(); showCreateChoices(); return; }
    var choice = event.target.closest("[data-modal-choice]");
    if (!choice) return;
    if (choice.dataset.modalChoice === "import") {
      showImportGame();
      return;
    }
    closeCreateModal();
    // No pushState here: htmx.ajax has no source element, so it resolves
    // hx-push-url from <body>, where it is true, and pushes /create itself.
    // Pushing again stacked a second identical entry, which swallowed the
    // first Back press — and left htmx no snapshot for the entry it never saw.
    htmx.ajax("GET", "/create", { target: "#viewport", swap: "innerHTML" }).then(function () {
      var ideaInput = document.getElementById("ideaInput");
      if (!ideaInput) return;
      if (choice.dataset.modalChoice === "habit") {
        ideaInput.value = "帮我做一个每天都想打开的习惯计划";
      }
      if (choice.dataset.modalChoice === "remix") {
        ideaInput.value = "我想 Remix 一个轻松、有一点惊喜的互动作品";
      }
      setTimeout(function () { ideaInput.focus(); }, 250);
    });
  });

  document.getElementById("importBack").addEventListener("click", showCreateChoices);
  importDropzone.addEventListener("click", function () { importGameZip.click(); });
  document.getElementById("chooseGameZip").addEventListener("click", function () { importGameZip.click(); });
  document.getElementById("chooseGameFolder").addEventListener("click", function () { importGameFolder.click(); });
  importGameZip.addEventListener("change", function () { selectImport("zip", importGameZip.files); });
  importGameFolder.addEventListener("change", function () { selectImport("folder", importGameFolder.files); });
  ["dragenter", "dragover"].forEach(function (type) {
    importDropzone.addEventListener(type, function (event) {
      event.preventDefault();
      importDropzone.classList.add("dragging");
    });
  });
  ["dragleave", "drop"].forEach(function (type) {
    importDropzone.addEventListener(type, function (event) {
      event.preventDefault();
      importDropzone.classList.remove("dragging");
    });
  });
  importDropzone.addEventListener("drop", function (event) {
    var files = event.dataTransfer.files;
    if (!files.length) return;
    selectImport(files.length === 1 && /\.zip$/i.test(files[0].name) ? "zip" : "folder", files);
  });
  importGameForm.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!importSelection) {
      document.getElementById("importStatus").textContent = "先选择一个 zip 或 dist 文件夹。";
      return;
    }
    importSubmit.disabled = true;
    var data = new FormData();
    ["Title", "Category", "Emoji", "Description"].forEach(function (field) {
      data.append(field.toLowerCase(), document.getElementById("importGame" + field).value.trim());
    });
    data.append("art", importGameForm.querySelector("[name='importGameArt']:checked").value);
    if (importSelection.kind === "zip") {
      data.append("bundle", importSelection.files[0]);
    } else {
      importSelection.files.forEach(function (file) {
        data.append("files", file);
        data.append("paths", file.webkitRelativePath || file.name);
      });
    }
    showUploadProgress(0, 0);
    var answered = false;
    var httpStatus = 0;
    postWithProgress("/api/import-game", data, showUploadProgress)
      .then(function (response) {
        httpStatus = response.status;
        return response.json().catch(function () {
          throw new Error(response.ok ? "导入失败" : "服务器拒绝了上传，请检查文件大小后重试");
        }).then(function (result) {
          answered = true;
          if (response.status === 401) {
            window.location.href = "/claim";
            throw new Error(result.detail);
          }
          if (!response.ok) throw new Error(result.detail || "导入失败");
          return result;
        });
      })
      .then(function (game) {
        closeCreateModal();
        showCreateChoices();
        return htmx.ajax("GET", "/", { target: "#viewport", swap: "innerHTML" }).then(function () {
          history.pushState({}, "", "/");
          var card = document.querySelector('.game-card[data-artifact="' + game.artifact + '"]');
          if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
          showToast("“" + game.title + "” 已加入游戏流");
        });
      })
      .catch(function (error) {
        // A refusal the app answered is already in the server's log.
        if (!answered) reportUploadFailure(error, httpStatus);
        document.getElementById("importStatus").textContent = error.message;
      })
      .finally(function () { importProgress.hidden = true; })
      .finally(function () { importSubmit.disabled = false; });
  });

  // --- keyboard --------------------------------------------------------
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && modal.classList.contains("open")) closeCreateModal();
    if (modal.classList.contains("open")) return;
    if (currentView() !== "home") return;
    if (gamePlaying()) return;
    if (event.key === "ArrowDown") { event.preventDefault(); moveFeed(1); }
    if (event.key === "ArrowUp") { event.preventDefault(); moveFeed(-1); }
  });


  // --- inline game host ------------------------------------------------
  // A game is an offline H5 artifact in its own sandboxed iframe. The iframe
  // lives in #gameHost, a body-level sibling of #viewport, for one reason:
  // htmx replaces #viewport wholesale on every nav, which destroys any iframe
  // inside it and the running game with it. Body level is what lets a full
  // four-stage session survive navigation. #createModal and #toast sit at the
  // same level for the same reason.
  //
  // The host is NEVER reparented. Moving an iframe node in the DOM reloads its
  // document in every browser, which would destroy exactly the session this
  // design exists to preserve. So the iframe is appended once and only ever
  // shown or hidden — never moved.
  //
  // The host is full-bleed (position:fixed, inset:0, z-index:60), which covers
  // beeplay's topbar and bottom nav as well as the card. That is what resolves
  // double chrome: the game's own topbar and journey nav become the only
  // chrome on screen, and nothing in the artifact had to change.
  var gameHost = document.getElementById("gameHost");
  var gameStop = document.getElementById("gameStop");

  // One live session at a time: {hash, frame, card, active}. `active` false
  // means paused — the iframe is still mounted and still holding game state,
  // the host is just hidden and the feed unlocked.
  var session = null;

  // TODO(completion-contract): After we have ten real games, review how each
  // one expresses completion and define a dedicated game-to-host hook from
  // that evidence. Keep completion separate from views and health signals;
  // do not infer it from load, pause, or exit. Then retrofit those ten games
  // to the agreed contract.

  function gamePlaying() {
    return !!(session && session.active);
  }

  // --- crash reporting -------------------------------------------------
  // Every uploaded game carries an inlined reporter (assets/js/game-reporter.js)
  // that postMessages "loaded" and "error" here. The host adds "start" on
  // mount and "timeout" when "loaded" never arrives, which is also what a
  // missing or broken index.html looks like from here. All of it goes to
  // /api/game-health, which hides games that keep crashing.
  var loadTimeoutMs = 1000 * (parseInt(document.body.dataset.loadTimeoutS, 10) || 10);

  function reportHealth(play, kind, detail) {
    try {
      fetch("/api/game-health", {
        method: "POST",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          artifact: play.hash,
          session: play.healthId,
          kind: kind,
          elapsed_ms: Date.now() - play.mountedAt,
          detail: detail || null
        })
      }).catch(function () {});
    } catch (ignored) {}
  }

  function newHealthId() {
    return interactionId();
  }

  function watchHealth(play) {
    play.healthId = newHealthId();
    play.mountedAt = Date.now();
    play.loaded = false;
    socialFetch(play.workId, "view", { event_id: play.healthId }).catch(function () {});
    reportHealth(play, "start");
    play.loadTimer = setTimeout(function () {
      if (!play.loaded) reportHealth(play, "timeout", "no load signal after " + loadTimeoutMs + "ms");
    }, loadTimeoutMs);
  }

  window.addEventListener("message", function (event) {
    var play = session;
    if (!play || !play.frame || event.source !== play.frame.contentWindow) return;
    var data = event.data || {};
    if (data.beeplay === "loaded" && !play.loaded) {
      play.loaded = true;
      clearTimeout(play.loadTimer);
      reportHealth(play, "loaded");
    } else if (data.beeplay === "error") {
      reportHealth(play, "error", data.detail);
    }
  });

  function mountGame(card, hash) {
    var frame = document.createElement("iframe");
    frame.src = "/games/" + hash + "/index.html";
    // No allow-same-origin: the game runs on an opaque origin and cannot
    // reach this document. There is deliberately no host API.
    frame.setAttribute("sandbox", "allow-scripts");
    frame.title = card.dataset.gameTitle || "游戏";
    frame.className = "game-frame";
    gameHost.appendChild(frame);
    return frame;
  }

  function resumeGame(card, button) {
    session.card = card;
    session.active = true;
    document.body.classList.add("playing");
    gameHost.hidden = false;
    if (button) { button.classList.add("active"); button.textContent = "Ⅱ"; }
  }

  function pauseGame() {
    if (!session) return;
    session.active = false;
    document.body.classList.remove("playing");
    gameHost.hidden = true;
    // Hidden, not unmounted. The iframe stays in the DOM holding the game's
    // JS state, so resuming returns the user to their half-made cup. This is
    // the whole reason the host is body-level: a paused session has to survive
    // an htmx nav swap, and anything inside #viewport would not.
    var button = session.card && session.card.querySelector('[data-game-action="play"]');
    if (button) { button.classList.remove("active"); button.textContent = "▶"; }
  }

  // Destroys the document and the session with it. Only ever deliberate.
  function endGame() {
    if (!session) return;
    pauseGame();
    // Only the frames go. #gameStop is a child of the host, so clearing the
    // host wholesale would delete the sole exit control — body.playing hides
    // the topbar and the bottom nav, leaving a full-bleed overlay with no way
    // out but the Escape key, which a phone does not have.
    [].forEach.call(gameHost.querySelectorAll("iframe"), function (frame) {
      frame.remove();
    });
    clearTimeout(session.loadTimer);
    session = null;
  }

  function togglePlay(card, button, title) {
    // No artifact means nothing to run; keep the prototype's toast.
    var hash = card && card.dataset.artifact;
    if (!hash || !gameHost) {
      button.classList.toggle("active");
      var on = button.classList.contains("active");
      button.textContent = on ? "Ⅱ" : "▶";
      showToast(on ? "正在试玩 " + title : "已暂停 " + title);
      return;
    }

    if (session && session.hash === hash) {
      if (session.active) pauseGame(); else resumeGame(card, button);
      return;
    }

    // Switching games throws away the cup in progress, so make it a decision.
    if (session && !window.confirm("换一个游戏会结束当前这局，确定吗？")) return;
    endGame();

    session = { hash: hash, workId: card.dataset.gameId, frame: null, card: card, active: false };
    session.frame = mountGame(card, hash);
    watchHealth(session);
    resumeGame(card, button);
  }

  // Nav guard. Hiding beeplay's chrome while body.playing removes the bottom
  // nav from the screen, so stray taps largely disappear — but the topbar
  // brand and nav links still carry hx-get, so leaving must stay deliberate.
  document.addEventListener("click", function (event) {
    if (!gamePlaying()) return;
    var nav = event.target.closest("[hx-get], [data-view-target]");
    if (!nav || gameHost.contains(nav)) return;
    if (!window.confirm("离开会暂停这一局，确定吗？")) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    pauseGame();
  }, true);

  // The card is rebuilt on every swap, so re-find it by hash and re-anchor.
  // A paused session survives the swap because the host is outside #viewport.
  function reanchorSession() {
    if (!session) return;
    session.card = document.querySelector(
      '.game-card[data-artifact="' + session.hash + '"]'
    );
  }

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target.id !== "viewport") return;
    reanchorSession();
  });

  // Back and forward rebuild the card too, and a paused session has to survive
  // them for the same reason it survives a nav swap.
  document.body.addEventListener("htmx:historyRestore", reanchorSession);

  // The exit control belongs to the host, not the card: the full-bleed
  // overlay covers .game-actions, so the card's own Ⅱ is unreachable while
  // playing. It pauses rather than ends — see pauseGame().
  if (gameStop) gameStop.addEventListener("click", pauseGame);

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && gamePlaying()) pauseGame();
  });

  syncChrome();
  scrollToSharedGame();
})();

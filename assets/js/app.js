(function () {
  "use strict";

  var modal = document.getElementById("createModal");
  var toast = document.getElementById("toast");
  var toastTimer;
  var feedWheelMoved = false;
  var feedWheelQuiet;

  function showToast(message, link) {
    toast.textContent = message;
    if (link) {
      var anchor = document.createElement("a");
      anchor.href = link.href;
      anchor.textContent = link.text;
      toast.appendChild(anchor);
    }
    toast.classList.add("show");
    clearTimeout(toastTimer);
    // A toast with a link stays up long enough to be tapped.
    toastTimer = setTimeout(function () { toast.classList.remove("show"); }, link ? 4000 : 2200);
  }

  // The swapped-in section is the only .view in the DOM, so it *is* the state.
  function currentView() {
    var view = document.querySelector("#viewport .view");
    return view ? view.dataset.view : "home";
  }

  function highlightNav(view) {
    document.querySelectorAll(".nav-item, .desktop-nav button").forEach(function (nav) {
      nav.classList.toggle("active", nav.dataset.viewTarget === view);
    });
  }

  // Nav and body live outside #viewport, so htmx never touches them.
  function syncChrome() {
    var view = currentView();
    highlightNav(view);
    document.body.classList.toggle("feed-mode", view === "home");
  }

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target.id !== "viewport") return;
    syncChrome();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  // The tapped page shows as current at once: the page itself is a network
  // round trip away, and until it came the old one stayed lit. A request that
  // fails puts the highlight back on the page still showing.
  document.body.addEventListener("htmx:beforeRequest", function (event) {
    var view = event.detail.elt.dataset && event.detail.elt.dataset.viewTarget;
    if (view && event.detail.target && event.detail.target.id === "viewport") highlightNav(view);
  });
  document.body.addEventListener("htmx:afterRequest", function (event) {
    if (!event.detail.successful) syncChrome();
  });

  // A history restore swaps #viewport without firing htmx:afterSwap, and the
  // chrome it leaves behind belongs to the page we navigated away from — a
  // stale nav highlight, and a missing body.feed-mode that unlocks page scroll
  // underneath the feed. htmx restores the scroll position itself, so only the
  // chrome needs resyncing here.
  document.body.addEventListener("htmx:historyRestore", function () {
    syncChrome();
    initInlineGames();
  });

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
  // Counted from the active card, not the scroll position: mid-scroll, no
  // card is at the top yet, and a second move would restart from the first.
  function moveFeed(direction) {
    var feed = document.getElementById("homeFeed");
    var cards = [].slice.call(document.querySelectorAll(".game-card"));
    if (!feed || !cards.length) return;
    var currentIndex = Math.max(0, cards.indexOf(activeInlineCard));
    var nextIndex = Math.min(cards.length - 1, Math.max(0, currentIndex + direction));
    feed.scrollTo({ top: cards[nextIndex].offsetTop, behavior: "smooth" });
    activateInlineGame(cards[nextIndex]);
  }

  function sharedGameCard() {
    if (currentView() !== "home") return null;
    var artifact = new URLSearchParams(window.location.search).get("game");
    if (!artifact) return null;
    return document.querySelector('.game-card[data-artifact="' + CSS.escape(artifact) + '"]');
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

  // Shown on the tap rather than after the round trip, and put back if the
  // server refuses it.
  async function updateToggle(button, card, action, title) {
    if (button.disabled) return;
    button.disabled = true;
    var active = !button.classList.contains("active");
    var counter = button.querySelector("[data-social-count='likes']");
    var count = counter ? parseInt(counter.textContent, 10) : NaN;
    renderToggle(button, active);
    if (!isNaN(count)) counter.textContent = Math.max(0, count + (active ? 1 : -1));
    try {
      var result = await socialFetch(card.dataset.gameId, action, { active: active });
      renderToggle(button, result.active);
      if (counter && typeof result.count === "number") counter.textContent = result.count;
      showToast(result.active
        ? (action === "like" ? "已喜欢 " : "已收藏 ") + title
        : (action === "like" ? "已取消喜欢" : "已取消收藏"));
    } catch (error) {
      renderToggle(button, !active);
      if (!isNaN(count)) counter.textContent = count;
      showToast(error.message);
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

  // One trackpad flick is dozens of wheel events, still arriving a second
  // after the fingers lift (macOS momentum), so a fixed lock let one flick
  // skip games. Move once per gesture: it ends when the wheel goes quiet.
  // Until then body.feed-wheeling lets the rest of the flick through the
  // game frames the feed scrolls under the pointer, or they would swallow it.
  document.addEventListener("wheel", function (event) {
    var onTray = event.target.closest && event.target.closest("[data-feed-swipe]");
    if (!onTray && !feedWheelMoved) return;
    event.preventDefault();
    clearTimeout(feedWheelQuiet);
    feedWheelQuiet = setTimeout(function () {
      feedWheelMoved = false;
      document.body.classList.remove("feed-wheeling");
    }, 200);
    if (feedWheelMoved || Math.abs(event.deltaY) < 8) return;
    feedWheelMoved = true;
    document.body.classList.add("feed-wheeling");
    moveFeed(event.deltaY > 0 ? 1 : -1);
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
      if (action === "like" || action === "save") {
        updateToggle(gameAction, gameCard, action, title);
      } else if (action === "comments") {
        openComments(gameCard);
      } else if (action === "share") {
        shareGame(gameAction, gameCard, title);
      }
      return;
    }

    var follow = target.closest("[data-follow-user]");
    if (follow) {
      updateFollow(follow);
      return;
    }

    var createButton = target.closest("[data-action='create']");
    if (createButton) {
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
          if (game.ask_profile && window.BeeAccount) window.BeeAccount.askForProfile(false);
        });
      })
      .catch(function (error) {
        // A refusal the app answered is already in the server's log.
        if (!answered) reportUploadFailure(error, httpStatus);
        document.getElementById("importStatus").textContent = error.message;
        if (window.beeplayReport) {
          window.beeplayReport("shown", error.message, {
            area: "creation",
            next: "stayed",
            lost: false,
            status: httpStatus || null
          });
        }
      })
      .finally(function () { importProgress.hidden = true; })
      .finally(function () { importSubmit.disabled = false; });
  });

  // --- keyboard --------------------------------------------------------
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && modal.classList.contains("open")) closeCreateModal();
    if (modal.classList.contains("open")) return;
    if (currentView() !== "home") return;
    if (event.key === "ArrowDown") { event.preventDefault(); moveFeed(1); }
    if (event.key === "ArrowUp") { event.preventDefault(); moveFeed(-1); }
  });


  // --- crash reporting -------------------------------------------------
  // Every uploaded game carries an inlined reporter (assets/js/game-reporter.js)
  // that postMessages "loaded" and "error" here. The feed adds "start" when a
  // game first becomes the active card and "timeout" when "loaded" never
  // arrives, which is also what a missing or broken index.html looks like from
  // here. All of it goes to /api/game-health, which hides games that keep
  // crashing.
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

  // TODO(completion-contract): After we have ten real games, review how each
  // one expresses completion and define a dedicated game-to-host hook from
  // that evidence. Keep completion separate from views and health signals;
  // do not infer it from load, pause, or exit. Then retrofit those ten games
  // to the agreed contract.

  // --- inline game feed ----------------------------------------------
  // Games are full-screen phone pages. Each frame is given the screen size
  // the game would get opened on its own, then scaled evenly into the game
  // window, so every game lays out exactly as it does standalone. Expanding
  // plays it at full size; the frame is only rescaled, never reloaded.
  // Games own every gesture inside their frame; only the tray switches cards.
  var inlinePlays = new WeakMap();
  var activeInlineCard = null;
  var expandedCard = null;
  // Wider than any phone: show games at a typical phone's screen size.
  var PHONE_MAX_WIDTH = 500;
  var PHONE_SCREEN = { width: 390, height: 844 };

  // The game's inlined reporter holds its audio on "pause" and "mute": a card
  // scrolled out of view keeps running, and the game cannot tell.
  function tellGame(frame, command) {
    if (!frame || !frame.contentWindow) return;
    frame.contentWindow.postMessage({ beeplayHost: command }, "*");
  }

  // One mute for every game, kept across visits like a feed's sound toggle.
  var muted = false;
  try { muted = localStorage.getItem("beeplay.muted") === "1"; } catch (ignored) {}

  function showMute() {
    document.querySelectorAll("[data-game-mute]").forEach(function (button) {
      button.classList.toggle("muted", muted);
      button.setAttribute("aria-pressed", muted ? "true" : "false");
      button.setAttribute("aria-label", muted ? "打开声音" : "静音");
    });
  }

  function toggleMute() {
    muted = !muted;
    try { localStorage.setItem("beeplay.muted", muted ? "1" : "0"); } catch (ignored) {}
    showMute();
    document.querySelectorAll(".game-frame").forEach(function (frame) {
      tellGame(frame, muted ? "mute" : "unmute");
    });
  }

  function gameScreen() {
    if (window.innerWidth > PHONE_MAX_WIDTH) return PHONE_SCREEN;
    return { width: window.innerWidth, height: window.innerHeight };
  }

  function fitStage(windowElement) {
    var stage = windowElement.querySelector(".game-stage");
    if (!stage || !windowElement.clientWidth || !windowElement.clientHeight) return;
    var screen = gameScreen();
    var scale = Math.min(1, windowElement.clientWidth / screen.width,
      windowElement.clientHeight / screen.height);
    stage.style.width = screen.width + "px";
    stage.style.height = screen.height + "px";
    stage.style.setProperty("--game-scale", scale.toFixed(4));
  }

  function fitStages() {
    document.querySelectorAll(".game-window").forEach(fitStage);
  }

  // Game windows change size without a window resize too: the tray's
  // max-height breakpoint, htmx swaps, and expanding or collapsing a game.
  // Cards are one screen tall, so a resize (rotation, the address bar, a
  // desktop window) moves every card; keep the active one aligned. The
  // observer runs after layout, when the window's resize event may not.
  function alignFeed() {
    var feed = document.getElementById("homeFeed");
    if (feed && activeInlineCard && feed.contains(activeInlineCard)) {
      feed.scrollTo({ top: activeInlineCard.offsetTop, behavior: "instant" });
    }
  }
  var stageObserver = window.ResizeObserver
    ? new ResizeObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.target.id === "homeFeed") alignFeed();
          else fitStage(entry.target);
        });
      })
    : null;
  window.addEventListener("resize", function () {
    fitStages();
    alignFeed();
  });

  function activateInlineGame(card) {
    if (!card || card === activeInlineCard) return;
    if (expandedCard) collapseGame();
    var candidates = [].slice.call(document.querySelectorAll(".game-card"));
    var activeIndex = candidates.indexOf(card);
    candidates.forEach(function (candidate, index) {
      var frame = candidate.querySelector(".game-frame");
      var active = candidate === card;
      if (frame && Math.abs(index - activeIndex) <= 1 && !frame.hasAttribute("src") && frame.dataset.src) {
        frame.setAttribute("src", frame.dataset.src);
      }
      candidate.classList.toggle("active-game", active);
      tellGame(frame, active ? "resume" : "pause");
      if (active) {
        var play = inlinePlays.get(frame);
        if (play && !play.started) {
          play.started = true;
          play.mountedAt = Date.now();
          socialFetch(play.workId, "view", { event_id: play.healthId }).catch(function () {});
          reportHealth(play, "start");
          play.loadTimer = setTimeout(function () {
            if (!play.loaded) reportHealth(play, "timeout", "no load signal after " + loadTimeoutMs + "ms");
          }, loadTimeoutMs);
        }
      }
    });
    activeInlineCard = card;
  }

  function expandGame(card) {
    if (!card || expandedCard === card) return;
    if (card !== activeInlineCard) activateInlineGame(card);
    expandedCard = card;
    card.classList.add("expanded");
    document.body.classList.add("game-expanded");
    // The phone's back gesture (and WeChat's back button) collapses the game
    // instead of leaving BeePlay.
    history.pushState({ beeplayExpanded: true }, "");
    fitStage(card.querySelector(".game-window"));
    var collapse = card.querySelector("[data-game-collapse]");
    if (collapse) collapse.focus({ preventScroll: true });
  }

  function collapseGame(fromHistory) {
    var card = expandedCard;
    if (!card) return;
    expandedCard = null;
    card.classList.remove("expanded");
    document.body.classList.remove("game-expanded");
    if (!fromHistory && history.state && history.state.beeplayExpanded) history.back();
    fitStage(card.querySelector(".game-window"));
  }

  window.addEventListener("popstate", function () {
    if (expandedCard) collapseGame(true);
  });

  function initInlineGames() {
    var cards = [].slice.call(document.querySelectorAll(".game-card"));
    cards.forEach(function (card) {
      var frame = card.querySelector(".game-frame");
      if (!frame || inlinePlays.has(frame)) return;
      var play = {
        frame: frame,
        card: card,
        hash: card.dataset.artifact,
        workId: card.dataset.gameId,
        healthId: interactionId(),
        mountedAt: 0,
        started: false,
        loaded: false
      };
      inlinePlays.set(frame, play);
      if (stageObserver) stageObserver.observe(card.querySelector(".game-window"));
      frame.addEventListener("load", function () {
        frame.classList.add("loaded");
        var loading = card.querySelector(".game-loading");
        if (loading) loading.hidden = true;
        if (play.started && !play.loaded) {
          play.loaded = true;
          clearTimeout(play.loadTimer);
          reportHealth(play, "loaded");
        }
        tellGame(frame, card === activeInlineCard ? "resume" : "pause");
        if (muted) tellGame(frame, "mute");
      });
    });
    var feed = document.getElementById("homeFeed");
    if (feed && stageObserver) stageObserver.observe(feed);
    fitStages();
    showMute();
    if (cards.length && !(activeInlineCard && document.contains(activeInlineCard))) {
      activateInlineGame(sharedGameCard() || cards[0]);
      alignFeed();
    }
  }

  window.addEventListener("message", function (event) {
    var matched = null;
    document.querySelectorAll(".game-frame").forEach(function (frame) {
      if (event.source === frame.contentWindow) matched = inlinePlays.get(frame);
    });
    if (!matched) return;
    var data = event.data || {};
    if (data.beeplay === "loaded" && !matched.loaded) {
      matched.loaded = true;
      clearTimeout(matched.loadTimer);
      matched.frame.classList.add("loaded");
      var loading = matched.card.querySelector(".game-loading");
      if (loading) loading.hidden = true;
      reportHealth(matched, "loaded");
    } else if (data.beeplay === "error") {
      reportHealth(matched, "error", data.detail);
    }
  });

  document.addEventListener("click", function (event) {
    if (!event.target.closest) return;
    var expand = event.target.closest("[data-game-expand]");
    if (expand) { expandGame(expand.closest(".game-card")); return; }
    if (event.target.closest("[data-game-mute]")) { toggleMute(); return; }
    if (event.target.closest("[data-game-collapse]")) collapseGame();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && expandedCard) collapseGame();
  });

  // A vertical drag on the tray switches games, decided while it moves: a
  // mouse let go over the game sends its pointerup to the game's frame, and
  // iOS cancels a touch it takes over. Once it is a drag, the tray captures
  // the pointer, and letting go is not a tap on what lies under it.
  var swipe = null;
  var dragEndedAt = 0;
  document.addEventListener("pointerdown", function (event) {
    var tray = event.isPrimary && event.target.closest && event.target.closest("[data-feed-swipe]");
    swipe = tray ? { tray: tray, x: event.clientX, y: event.clientY, id: event.pointerId } : null;
  });
  document.addEventListener("pointermove", function (event) {
    if (!swipe || event.pointerId !== swipe.id || swipe.moved) return;
    var dy = event.clientY - swipe.y;
    var dx = event.clientX - swipe.x;
    if (!swipe.dragging && Math.abs(dy) > 8) {
      swipe.dragging = true;
      try { swipe.tray.setPointerCapture(event.pointerId); } catch (ignored) {}
    }
    if (Math.abs(dy) > 44 && Math.abs(dy) > Math.abs(dx) * 1.2) {
      swipe.moved = true;
      moveFeed(dy < 0 ? 1 : -1);
    }
  });
  function endSwipe(event) {
    if (!swipe || event.pointerId !== swipe.id) return;
    if (swipe.dragging) dragEndedAt = Date.now();
    swipe = null;
  }
  document.addEventListener("pointerup", endSwipe);
  document.addEventListener("pointercancel", endSwipe);
  document.addEventListener("click", function (event) {
    if (Date.now() - dragEndedAt > 300) return;
    event.preventDefault();
    event.stopPropagation();
  }, true);

  // --- persistent follows and comments --------------------------------
  function renderFollow(button, active) {
    button.classList.toggle("following", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.textContent = active ? "已关注" : "+ 关注";
  }

  // Like the toggles: shown on the tap, put back if refused.
  function updateFollow(button) {
    if (button.disabled) return;
    button.disabled = true;
    var active = !button.classList.contains("following");
    renderFollow(button, active);
    fetch("/api/users/" + button.dataset.followUser + "/follow", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: active })
    }).then(function (response) {
      if (!response.ok) throw new Error("关注没有保存，请重试");
      return response.json();
    }).then(function (result) {
      renderFollow(button, result.active);
    }).catch(function (error) {
      renderFollow(button, !active);
      showToast(error.message);
    }).finally(function () { button.disabled = false; });
  }

  var commentsModal = document.getElementById("commentsModal");
  var commentsList = document.getElementById("commentsList");
  var commentInput = document.getElementById("commentInput");
  var commentsCard = null;

  function commentNode(comment) {
    var row = document.createElement("article");
    row.className = "comment-item";
    var avatar = document.createElement("img");
    avatar.className = "comment-avatar";
    avatar.src = comment.avatar;
    avatar.alt = "";
    var copy = document.createElement("div");
    copy.className = "comment-copy";
    // A plain link: the comment sheet is not part of the htmx view.
    var author = document.createElement("a");
    author.className = "comment-author";
    author.href = "/u/" + encodeURIComponent(comment.handle);
    author.textContent = comment.author;
    var content = document.createElement("p");
    content.textContent = comment.content;
    copy.append(author, content);
    var like = document.createElement("button");
    like.type = "button";
    like.className = "comment-like" + (comment.liked ? " active" : "");
    like.dataset.commentLike = comment.id;
    like.setAttribute("aria-pressed", comment.liked ? "true" : "false");
    like.textContent = "♥ " + comment.likes;
    row.append(avatar, copy, like);
    return row;
  }

  function renderComments(comments) {
    commentsList.replaceChildren();
    if (!comments.length) {
      var empty = document.createElement("p");
      empty.className = "comment-empty";
      empty.textContent = "还没有评论，来写第一条吧。";
      commentsList.appendChild(empty);
      return;
    }
    comments.forEach(function (comment) { commentsList.appendChild(commentNode(comment)); });
  }

  function openComments(card) {
    commentsCard = card;
    document.getElementById("commentsTitle").textContent = card.dataset.gameTitle + " · 评论";
    commentsList.textContent = "正在加载…";
    commentsModal.classList.add("open");
    fetch("/api/works/" + card.dataset.gameId + "/comments")
      .then(function (response) { if (!response.ok) throw new Error(); return response.json(); })
      .then(function (payload) { renderComments(payload.comments); })
      .catch(function () { commentsList.textContent = "评论没有加载，请重试。"; });
  }

  function closeComments() {
    commentsModal.classList.remove("open");
    commentsCard = null;
    commentInput.value = "";
  }

  document.getElementById("commentsClose").addEventListener("click", closeComments);
  commentsModal.addEventListener("click", function (event) {
    if (event.target === commentsModal) closeComments();
  });
  document.getElementById("commentForm").addEventListener("submit", function (event) {
    event.preventDefault();
    if (!commentsCard || !commentInput.value.trim()) return;
    fetch("/api/works/" + commentsCard.dataset.gameId + "/comments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: commentInput.value.trim() })
    }).then(function (response) {
      if (!response.ok) throw new Error("评论没有保存，请重试");
      return response.json();
    }).then(function (comment) {
      var empty = commentsList.querySelector(".comment-empty");
      if (empty) empty.remove();
      commentsList.appendChild(commentNode(comment));
      commentInput.value = "";
      var count = commentsCard.querySelector("[data-social-count='comments']");
      if (count) count.textContent = String(Number(count.textContent || 0) + 1);
      commentsList.scrollTop = commentsList.scrollHeight;
    }).catch(function (error) {
      showToast(error.message);
    });
  });
  function renderCommentLike(button, active, count) {
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.textContent = "♥ " + count;
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-comment-like]");
    if (!button || button.disabled) return;
    button.disabled = true;
    var active = !button.classList.contains("active");
    var count = parseInt(button.textContent.replace(/[^0-9]/g, ""), 10) || 0;
    renderCommentLike(button, active, Math.max(0, count + (active ? 1 : -1)));
    fetch("/api/comments/" + button.dataset.commentLike + "/like", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: active })
    }).then(function (response) {
      if (!response.ok) throw new Error("点赞没有保存，请重试");
      return response.json();
    }).then(function (result) {
      renderCommentLike(button, result.active, result.count);
    }).catch(function (error) {
      renderCommentLike(button, !active, count);
      showToast(error.message);
    }).finally(function () { button.disabled = false; });
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target.id === "viewport") initInlineGames();
  });

  syncChrome();
  initInlineGames();
})();

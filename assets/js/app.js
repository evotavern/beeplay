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
  });

  function openCreateModal() {
    modal.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  function closeCreateModal() {
    modal.classList.remove("open");
    document.body.style.overflow = "";
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
      }
      if (action === "like") {
        gameAction.classList.toggle("active");
        showToast(gameAction.classList.contains("active") ? "已喜欢 " + title : "已取消喜欢");
      }
      if (action === "save") {
        gameAction.classList.toggle("active");
        showToast(gameAction.classList.contains("active") ? "已收藏 " + title : "已取消收藏");
      }
      if (action === "share") showToast("分享卡片已准备好：" + title);
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
      showToast("Bee 正在把你的想法变成一个可玩的版本…");
      setTimeout(function () { showToast("初版完成，马上可以开始试玩"); }, 1700);
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
    if (event.target === modal) closeCreateModal();
    var choice = event.target.closest("[data-modal-choice]");
    if (!choice) return;
    closeCreateModal();
    htmx.ajax("GET", "/create", { target: "#viewport", swap: "innerHTML" }).then(function () {
      history.pushState({}, "", "/create");
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
  // design exists to preserve. It is positioned over the playing card by
  // setting style from the card's measured box — never by appendChild.
  var gameHost = document.getElementById("gameHost");

  // One live session at a time: {hash, frame, card, active}. `active` false
  // means paused — the iframe is still mounted and still holding game state,
  // the host is just hidden and the feed unlocked.
  var session = null;

  function gamePlaying() {
    return !!(session && session.active);
  }

  // Position the host over its card. Called on mount and whenever the card
  // could have moved under it.
  function anchorHost() {
    if (!session || !session.card || !gameHost) return;
    var box = session.card.getBoundingClientRect();
    gameHost.style.top = box.top + "px";
    gameHost.style.left = box.left + "px";
    gameHost.style.width = box.width + "px";
    gameHost.style.height = box.height + "px";
  }

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
    if (button) { button.classList.add("active"); button.textContent = "Ⅱ"; }
    anchorHost();
  }

  function pauseGame() {
    if (!session) return;
    session.active = false;
    document.body.classList.remove("playing");
    // Hidden, not unmounted: the document keeps running and keeps its state,
    // so resuming returns the user to their half-made cup. Hiding via a class
    // rather than display:none, which risks pausing or reloading the frame.
    var button = session.card && session.card.querySelector('[data-game-action="play"]');
    if (button) { button.classList.remove("active"); button.textContent = "▶"; }
  }

  // Destroys the document and the session with it. Only ever deliberate.
  function endGame() {
    if (!session) return;
    pauseGame();
    gameHost.innerHTML = "";
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

    session = { hash: hash, frame: null, card: card, active: false };
    session.frame = mountGame(card, hash);
    resumeGame(card, button);
  }

  // Keep the host over its card if the viewport changes under it.
  window.addEventListener("resize", anchorHost);
  window.addEventListener("scroll", anchorHost, { passive: true });

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
  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target.id !== "viewport" || !session) return;
    var card = document.querySelector('.game-card[data-artifact="' + session.hash + '"]');
    session.card = card || null;
    if (card) anchorHost();
  });

  // TODO(contract): the exit control is body-level markup owned by the other
  // session — the card's own Ⅱ cannot serve, because .game-card sets
  // isolation:isolate and a body-level host paints over the whole card
  // including its z-index:4 buttons. Wire the real selector when it lands.
  // Escape is an interim exit so the feed lock is never inescapable.
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && gamePlaying()) pauseGame();
  });

  syncChrome();
})();

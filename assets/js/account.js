(function () {
  "use strict";

  // Profile and password editors open in #accountSheet, a body-level
  // backdrop, so the one-time "pick a name" prompt after a first publish can
  // appear over whatever view the publish landed on. The editor markup is
  // fetched fresh every time it opens, so it never shows stale values.

  var sheet = document.getElementById("accountSheet");
  var PROMPT_KEY = "beeplay-ask-profile";
  if (!sheet) return;
  // Refreshing the view from here must not stack a history entry: htmx takes
  // hx-push-url from the source element, which htmx.ajax gets from this.
  sheet.setAttribute("hx-push-url", "false");

  function toast(message) {
    var node = document.getElementById("toast");
    if (!node) return;
    node.textContent = message;
    node.classList.add("show");
    setTimeout(function () { node.classList.remove("show"); }, 2200);
  }

  function currentView() {
    var view = document.querySelector("#viewport .view");
    return view ? view.dataset.view : "";
  }

  function refreshView() {
    if (["profile", "user"].indexOf(currentView()) < 0 || !window.htmx) return;
    htmx.ajax("GET", window.location.pathname + window.location.search, {
      source: sheet, target: "#viewport", swap: "innerHTML"
    });
  }

  function showAccount(account) {
    var header = document.getElementById("headerAvatar");
    if (header && account.avatar) header.src = account.avatar;
    var preview = sheet.querySelector("[data-photo-preview]");
    if (preview && account.avatar) preview.src = account.avatar;
  }

  // FastAPI answers validation failures with a list; show one readable line.
  async function send(url, method, body) {
    var isForm = body instanceof FormData;
    var response = await fetch(url, {
      method: method,
      credentials: "same-origin",
      headers: isForm || body === undefined ? {} : { "Content-Type": "application/json" },
      body: isForm ? body : body === undefined ? undefined : JSON.stringify(body)
    });
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "没有保存成功，请检查后重试");
    }
    return data;
  }

  async function openSheet(kind, prompt) {
    var url = kind === "password" ? "/partials/password-editor" : "/partials/profile-editor";
    try {
      var response = await fetch(url + (prompt ? "?prompt=1" : ""), { credentials: "same-origin" });
      if (!response.ok) throw new Error("打不开编辑页，请刷新后重试");
      sheet.innerHTML = await response.text();
    } catch (error) {
      toast(error.message);
      return;
    }
    sheet.classList.add("open");
    document.body.style.overflow = "hidden";
    var first = sheet.querySelector("input:not([type=file]):not([type=radio])");
    if (first && !prompt) first.focus();
  }

  function closeSheet() {
    sheet.classList.remove("open");
    sheet.innerHTML = "";
    document.body.style.overflow = "";
  }

  function fields(form) {
    var data = {};
    new FormData(form).forEach(function (value, key) { data[key] = value; });
    return data;
  }

  var submitters = {
    profile: async function (form) {
      var account = await send("/api/account/profile", "POST", fields(form));
      showAccount(account);
      closeSheet();
      toast("个人档案已保存");
      refreshView();
    },
    password: async function (form) {
      var hadPassword = !!form.querySelector("[name=current_password]");
      var account = await send("/api/account/password", "POST", fields(form));
      closeSheet();
      toast(hadPassword ? "密码已修改" : "密码已设置，用 @" + account.handle + " 登录");
      refreshView();
    },
    login: async function (form) {
      await send("/api/login", "POST", fields(form));
      // A full load: the header, nav and every card now belong to someone else.
      window.location.href = form.dataset.next || "/profile";
    },
    reset: async function (form) {
      await send("/api/reset", "POST", { token: form.dataset.token, password: fields(form).password });
      window.location.href = form.dataset.next || "/profile";
    }
  };

  document.addEventListener("submit", async function (event) {
    var form = event.target.closest("[data-account-form]");
    if (!form) return;
    event.preventDefault();
    var button = form.querySelector("[type=submit]");
    var error = form.querySelector(".account-error");
    if (button) button.disabled = true;
    if (error) error.textContent = "";
    try {
      await submitters[form.dataset.accountForm](form);
    } catch (problem) {
      if (error) error.textContent = problem.message;
      else toast(problem.message);
    } finally {
      if (button) button.disabled = false;
    }
  });

  document.addEventListener("change", async function (event) {
    var input = event.target.closest("[data-photo-input]");
    if (!input || !input.files.length) return;
    var row = input.closest(".photo-row");
    var error = sheet.querySelector(".account-error");
    var data = new FormData();
    data.append("photo", input.files[0]);
    row.classList.add("busy");
    if (error) error.textContent = "";
    try {
      showAccount(await send("/api/account/photo", "POST", data));
      var remove = sheet.querySelector("[data-photo-remove]");
      if (remove) remove.hidden = false;
      refreshView();
    } catch (problem) {
      if (error) error.textContent = problem.message;
    } finally {
      row.classList.remove("busy");
      input.value = "";
    }
  });

  document.addEventListener("click", async function (event) {
    var opener = event.target.closest("[data-account-open]");
    if (opener) {
      openSheet(opener.dataset.accountOpen, false);
      return;
    }
    if (event.target === sheet || event.target.closest("[data-account-close]")) {
      closeSheet();
      return;
    }
    var remove = event.target.closest("[data-photo-remove]");
    if (remove) {
      try {
        showAccount(await send("/api/account/photo", "DELETE"));
        remove.hidden = true;
        refreshView();
      } catch (problem) {
        toast(problem.message);
      }
      return;
    }
    if (event.target.closest("[data-account-logout]")) {
      if (!window.confirm("退出后需要用户名和密码才能再登录。确定退出吗？")) return;
      try {
        await send("/api/logout", "POST", {});
        window.location.href = "/";
      } catch (problem) {
        toast(problem.message);
      }
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && sheet.classList.contains("open")) closeSheet();
  });

  // Called after a first publish. A publish that reloads the page asks via
  // sessionStorage so the prompt survives the navigation.
  window.BeeAccount = {
    askForProfile: function (afterNavigation) {
      if (!afterNavigation) { openSheet("profile", true); return; }
      try { sessionStorage.setItem(PROMPT_KEY, "1"); } catch (_) {}
    }
  };

  try {
    if (sessionStorage.getItem(PROMPT_KEY)) {
      sessionStorage.removeItem(PROMPT_KEY);
      openSheet("profile", true);
    }
  } catch (_) {}
})();

const $ = (id) => document.getElementById(id);

const els = {
  form: $("login_form"),
  token: $("login_token"),
  button: $("login_btn"),
  message: $("login_message"),
  msgContainer: $("login_message_container"),
};

function setMessage(text, error = false) {
  els.message.textContent = text || "";
  if (text) {
    els.msgContainer.classList.add('show');
    els.message.className = `md3-body-small msg-text ${error ? "error" : "success"}`;
  } else {
    els.msgContainer.classList.remove('show');
  }
}

function setLoading(loading) {
  els.button.disabled = loading;
  if (loading) {
    els.button.classList.add("is-loading");
    els.button.querySelector("span:last-child").textContent = "验证中...";
  } else {
    els.button.classList.remove("is-loading");
    els.button.querySelector("span:last-child").textContent = "验证身份";
  }
}

async function requestJson(path, method = "GET", body = null) {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : null,
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    // Ignore and use HTTP status.
  }

  if (!response.ok || payload?.status !== "ok") {
    throw new Error(payload?.message || `HTTP ${response.status}`);
  }

  return payload.data || {};
}

async function checkStatus() {
  const data = await requestJson("/api/auth/status");
  if (!data.require_login || data.authenticated) {
    window.location.href = "/";
    return false;
  }
  return true;
}

async function submitLogin(event) {
  event.preventDefault();
  const token = String(els.token.value || "");

  setLoading(true);
  setMessage("");
  try {
    await requestJson("/api/auth/login", "POST", { token });
    setMessage("登录成功，正在跳转...", false);
    document.body.classList.remove("is-ready");
    document.body.classList.add("is-leaving");
    setTimeout(() => {
      window.location.href = "/";
    }, 400);
  } catch (error) {
    setMessage(error.message || "口令无效，登录失败", true);
    els.form.classList.add("shake");
    setTimeout(() => els.form.classList.remove("shake"), 400);
  } finally {
    setLoading(false);
  }
}

async function bootstrap() {
  setTimeout(() => {
    document.body.classList.add("is-ready");
  }, 50);

  try {
    const shouldContinue = await checkStatus();
    if (!shouldContinue) {
      return;
    }
  } catch (error) {
    setMessage(error.message || "鉴权状态检查失败", true);
  }

  els.form.addEventListener("submit", submitLogin);
  els.token.focus();
}

bootstrap();

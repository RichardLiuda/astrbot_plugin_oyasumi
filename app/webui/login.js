const $ = (id) => document.getElementById(id);

const els = {
  form: $("login_form"),
  token: $("login_token"),
  button: $("login_btn"),
  message: $("login_message"),
};

function setMessage(text, type = "info") {
  els.message.textContent = text || "";
  els.message.className = `login-message ${type === "error" ? "error" : ""}`.trim();
}

function setLoading(loading) {
  els.button.disabled = loading;
  if (loading) {
    els.button.classList.add("is-loading");
  } else {
    els.button.classList.remove("is-loading");
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
  } catch (_err) {
    // Ignore and use HTTP status.
  }
  if (!response.ok || payload?.status !== "ok") {
    throw new Error(payload?.message || `HTTP ${response.status}`);
  }
  return payload.data || {};
}

async function checkStatusAndRedirect() {
  const data = await requestJson("/api/auth/status");
  if (!data.require_login || data.authenticated) {
    window.location.href = "/";
    return false;
  }
  return true;
}

async function onSubmit(event) {
  event.preventDefault();
  const token = els.token.value || "";

  setLoading(true);
  setMessage("");
  try {
    await requestJson("/api/auth/login", "POST", { token });
    window.location.href = "/";
  } catch (err) {
    setMessage(err.message || "登录失败", "error");
  } finally {
    setLoading(false);
  }
}

async function bootstrap() {
  try {
    const shouldContinue = await checkStatusAndRedirect();
    if (!shouldContinue) {
      return;
    }
  } catch (err) {
    setMessage(err.message || "鉴权状态检查失败", "error");
  }
  els.form.addEventListener("submit", onSubmit);
  els.token.focus();
}

bootstrap();

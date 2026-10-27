const state = { id: null, file: null, pendingId: null };

const projectSelect = document.querySelector("#project-select");
const tree = document.querySelector("#tree");
const editor = document.querySelector("#editor");
const currentPath = document.querySelector("#current-path");
const messages = document.querySelector("#messages");
const pendingBox = document.querySelector("#pending");
const pendingNote = document.querySelector("#pending-note");
const diffs = document.querySelector("#diffs");
const output = document.querySelector("#output");
const banner = document.querySelector("#banner");
const mode = document.querySelector("#mode");
const undoButton = document.querySelector("#undo");

function showError(text) {
  if (!text) {
    banner.hidden = true;
    banner.textContent = "";
    return;
  }
  banner.hidden = false;
  banner.textContent = text;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "الطلب فشل.");
  }
  return data;
}

function renderMessages(chat) {
  messages.replaceChildren();
  for (const item of chat || []) {
    const article = document.createElement("article");
    article.className = item.role === "user" ? "user" : "assistant";
    const who = document.createElement("b");
    who.textContent = item.role === "user" ? "أنت" : "مداد";
    const body = document.createElement("p");
    body.textContent = item.content || "";
    article.append(who, body);
    messages.append(article);
  }
  messages.scrollTop = messages.scrollHeight;
}

function renderPending(pending) {
  state.pendingId = pending ? pending.id : null;
  pendingBox.hidden = !pending;
  diffs.replaceChildren();
  if (!pending) return;
  pendingNote.textContent = `${pending.summary}. لسه مفيش كتابة على الملفات. راجع الفرق وبعدين طبّق.`;
  for (const diff of pending.diffs || []) {
    const title = document.createElement("h3");
    title.textContent = diff.path;
    diffs.append(title);
    for (const line of (diff.unified || "").split("\n")) {
      const row = document.createElement("div");
      row.textContent = line || " ";
      if (line.startsWith("+") && !line.startsWith("+++")) row.className = "add";
      else if (line.startsWith("-") && !line.startsWith("---")) row.className = "del";
      diffs.append(row);
    }
  }
}

function renderTree(paths) {
  tree.replaceChildren();
  for (const path of paths || []) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = path;
    button.className = path === state.file ? "active" : "";
    button.addEventListener("click", () => openFile(path));
    item.append(button);
    tree.append(item);
  }
}

async function openFile(path) {
  if (state.file && editor.dataset.dirty === "1") await saveFile();
  const data = await api(`/api/projects/${state.id}/file?path=${encodeURIComponent(path)}`);
  state.file = data.path;
  editor.value = data.content;
  editor.dataset.dirty = "0";
  currentPath.textContent = data.path;
  renderTree(state.tree || []);
}

async function refresh() {
  const data = await api(`/api/projects/${state.id}`);
  state.tree = data.tree;
  renderTree(data.tree);
  renderMessages(data.chat);
  renderPending(data.pending);
  undoButton.disabled = !data.can_undo;
  if (state.file && (data.tree || []).includes(state.file)) {
    const file = await api(`/api/projects/${state.id}/file?path=${encodeURIComponent(state.file)}`);
    if (editor.dataset.dirty !== "1") editor.value = file.content;
  }
}

async function loadProjects(selectId) {
  const data = await api("/api/projects");
  projectSelect.replaceChildren();
  for (const project of data.projects) {
    const option = document.createElement("option");
    option.value = project.id;
    option.textContent = project.name;
    projectSelect.append(option);
  }
  if (!data.projects.length) return;
  state.id = selectId || data.projects[0].id;
  projectSelect.value = state.id;
  state.file = null;
  editor.value = "";
  await refresh();
  const preferred = (state.tree || []).includes("main.py") ? "main.py" : (state.tree || [])[0];
  if (preferred) await openFile(preferred);
}

async function saveFile() {
  if (!state.file) return;
  await api(`/api/projects/${state.id}/file`, {
    method: "PUT",
    body: JSON.stringify({ path: state.file, content: editor.value }),
  });
  editor.dataset.dirty = "0";
  await refresh();
}

async function loadSettings() {
  const settings = await api("/api/settings");
  mode.textContent = settings.provider === "openai" ? "متصل بالنموذج" : "وضع التجربة";
  document.querySelector("#base-url").value = settings.base_url;
  document.querySelector("#model").value = settings.model;
  document.querySelector("#key-state").textContent = settings.key_set
    ? `المفتاح محفوظ ${settings.key_hint}`
    : "مفيش مفتاح. وضع التجربة يعدّل الآلة الحاسبة ويعمل صفحة بسيطة.";
  return settings;
}

document.querySelector("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = document.querySelector("#chat-input").value.trim();
  if (!message || !state.id) return;
  showError("");
  const send = document.querySelector("#send");
  send.disabled = true;
  try {
    if (editor.dataset.dirty === "1") await saveFile();
    await api(`/api/projects/${state.id}/chat`, {
      method: "POST",
      body: JSON.stringify({ message, active_file: state.file }),
    });
    document.querySelector("#chat-input").value = "";
    await refresh();
  } catch (error) {
    showError(error.message);
  } finally {
    send.disabled = false;
  }
});

document.querySelector("#apply").addEventListener("click", async () => {
  if (!state.pendingId) return;
  showError("");
  document.querySelector("#apply").disabled = true;
  try {
    await api(`/api/projects/${state.id}/apply`, {
      method: "POST",
      body: JSON.stringify({ pending_id: state.pendingId }),
    });
    editor.dataset.dirty = "0";
    await refresh();
  } catch (error) {
    showError(error.message);
    await refresh();
  } finally {
    document.querySelector("#apply").disabled = false;
  }
});

document.querySelector("#cancel-pending").addEventListener("click", async () => {
  await api(`/api/projects/${state.id}/cancel`, { method: "POST" });
  await refresh();
});

document.querySelector("#save").addEventListener("click", async () => {
  try {
    await saveFile();
    showError("");
  } catch (error) {
    showError(error.message);
  }
});

editor.addEventListener("input", () => {
  editor.dataset.dirty = "1";
});

document.querySelector("#undo").addEventListener("click", async () => {
  try {
    editor.dataset.dirty = "0";
    await api(`/api/projects/${state.id}/undo`, { method: "POST" });
    showError("");
    await refresh();
  } catch (error) {
    showError(error.message);
  }
});

document.querySelector("#run").addEventListener("click", async () => {
  try {
    if (editor.dataset.dirty === "1") await saveFile();
    const data = await api(`/api/projects/${state.id}/run`, {
      method: "POST",
      body: JSON.stringify({ path: state.file }),
    });
    output.replaceChildren();
    if (data.kind === "preview") {
      const frame = document.createElement("iframe");
      frame.title = "معاينة";
      frame.src = data.preview_url;
      output.append(frame);
      return;
    }
    output.textContent = `$ ${data.command}\nexit ${data.exit_code}\n${data.stdout || ""}${data.stderr || ""}`;
  } catch (error) {
    showError(error.message);
  }
});

document.querySelector("#export").addEventListener("click", () => {
  if (state.id) window.location = `/api/projects/${state.id}/export`;
});

projectSelect.addEventListener("change", async () => {
  state.id = projectSelect.value;
  state.file = null;
  editor.dataset.dirty = "0";
  await refresh();
  const preferred = (state.tree || []).includes("main.py") ? "main.py" : (state.tree || [])[0];
  if (preferred) await openFile(preferred);
});

document.querySelector("#new-project-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = document.querySelector("#project-name-input").value.trim();
  if (!name) return;
  const created = await api("/api/projects", { method: "POST", body: JSON.stringify({ name }) });
  document.querySelector("#project-name-input").value = "";
  await loadProjects(created.id);
});

document.querySelector("#new-file-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const path = document.querySelector("#new-file-name").value.trim();
  if (!path || !state.id) return;
  try {
    await api(`/api/projects/${state.id}/file`, {
      method: "PUT",
      body: JSON.stringify({ path, content: "" }),
    });
    document.querySelector("#new-file-name").value = "";
    editor.dataset.dirty = "0";
    await refresh();
    await openFile(path);
  } catch (error) {
    showError(error.message);
  }
});

document.querySelector("#import-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.querySelector("#zip-file");
  if (!input.files.length) return;
  const body = new FormData();
  body.set("file", input.files[0]);
  body.set("name", input.files[0].name.replace(/\.zip$/i, ""));
  const response = await fetch("/api/projects/import", { method: "POST", body });
  const data = await response.json();
  if (!response.ok) {
    showError(data.error || "الاستيراد فشل.");
    return;
  }
  input.value = "";
  await loadProjects(data.id);
});

document.querySelector("#settings-open").addEventListener("click", () => {
  document.querySelector("#settings").showModal();
});
document.querySelector("#settings-close").addEventListener("click", () => {
  document.querySelector("#settings").close();
});
document.querySelector("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        base_url: document.querySelector("#base-url").value,
        model: document.querySelector("#model").value,
        api_key: document.querySelector("#api-key").value,
      }),
    });
    document.querySelector("#api-key").value = "";
    await loadSettings();
    document.querySelector("#settings").close();
    showError("");
  } catch (error) {
    showError(error.message);
  }
});
document.querySelector("#clear-key").addEventListener("click", async () => {
  await api("/api/settings", { method: "PUT", body: JSON.stringify({ clear_key: true }) });
  document.querySelector("#api-key").value = "";
  await loadSettings();
});

loadSettings().then(() => loadProjects()).catch((error) => showError(error.message));

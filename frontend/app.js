// Plain JavaScript client: Cognito sign-in, exam with 30-second autosave, direct-to-S3 upload.
const cfg = window.APP_CONFIG;
const $ = (id) => document.getElementById(id);
let idToken = sessionStorage.getItem("idToken");
let attempt = null, dirty = {}, autosaveTimer = null, countdown = null;

// ---------- Cognito sign-in (USER_PASSWORD_AUTH, public app client) ----------
async function signIn(email, password) {
  const res = await fetch(`https://cognito-idp.${cfg.region}.amazonaws.com/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
    },
    body: JSON.stringify({ AuthFlow: "USER_PASSWORD_AUTH", ClientId: cfg.cognitoClientId,
                           AuthParameters: { USERNAME: email, PASSWORD: password } }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || "Sign-in failed");
  if (!data.AuthenticationResult) throw new Error(`Extra step required: ${data.ChallengeName}`);
  return data.AuthenticationResult.IdToken;
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Authorization": `Bearer ${idToken}`, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { logout(); throw new Error("Please sign in again"); }
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function logout() {
  sessionStorage.removeItem("idToken"); idToken = null;
  clearInterval(autosaveTimer); clearInterval(countdown);
  $("app").classList.add("hidden"); $("login").classList.remove("hidden");
}

// ---------- Exams ----------
async function loadHome() {
  const { exams, user } = await api("GET", "/api/exams");
  $("who").textContent = user.email; $("roles").textContent = user.groups.join(", ") || "no role";
  const isTutor = user.groups.includes("tutor") || user.groups.includes("admin");
  $("exams").innerHTML = exams.map((e) => `
    <p><b>${e.title}</b> · ${e.duration_minutes} min
      <button data-start="${e.id}">Start / resume</button>
      ${isTutor ? `<button class="secondary" data-release="${e.id}">Release results</button>` : ""}
      ${e.results_released ? '<span class="ok">results released</span>' : ""}</p>`).join("");
  document.querySelectorAll("[data-start]").forEach((b) => b.onclick = () => startExam(b.dataset.start, b.parentElement.querySelector("b").textContent));
  document.querySelectorAll("[data-release]").forEach((b) => b.onclick = async () => {
    const r = await api("POST", `/api/exams/${b.dataset.release}/release`); alert(`Released. ${r.emails_queued} emails queued.`); loadHome();
  });
  const { assignments } = await api("GET", "/api/assignments");
  $("assignments").innerHTML = assignments.map((a, i) =>
    `<label><input type="radio" name="assignment" value="${a.id}" ${i === 0 ? "checked" : ""}> ${a.title}</label><br>`).join("");
}

async function startExam(examId, title) {
  try {
    attempt = await api("POST", `/api/exams/${examId}/start`);
  } catch (e) { alert(e.message); return; }
  $("examTitle").textContent = title; $("examView").classList.remove("hidden");
  $("questions").innerHTML = attempt.questions.map((q) => {
    const saved = attempt.saved_answers[q.id] || "";
    const input = q.kind === "mcq"
      ? q.options.map((o) => `<label><input type="radio" name="q${q.id}" value="${o}" ${saved === o ? "checked" : ""}> ${o}</label><br>`).join("")
      : `<textarea name="q${q.id}" rows="3">${saved}</textarea>`;
    return `<div class="question" data-q="${q.id}"><b>${q.position}. ${q.text}</b> <span class="muted">(${q.marks} mark${q.marks > 1 ? "s" : ""})</span><br>${input}</div>`;
  }).join("");
  $("questions").oninput = (ev) => { const qid = ev.target.closest("[data-q]").dataset.q; dirty[qid] = ev.target.value; };
  clearInterval(autosaveTimer); autosaveTimer = setInterval(autosave, 30000); // every 30 seconds
  clearInterval(countdown); countdown = setInterval(tick, 1000); tick();
}

async function autosave() {
  if (!attempt || Object.keys(dirty).length === 0) return;
  const batch = dirty; dirty = {};
  try {
    const r = await api("PUT", `/api/attempts/${attempt.attempt_id}/answers`, { answers: batch });
    $("saveStatus").innerHTML = `<span class="ok">saved ${new Date(r.saved_at).toLocaleTimeString()}</span>`;
  } catch (e) {
    dirty = { ...batch, ...dirty }; // keep the answers and retry on the next tick
    $("saveStatus").innerHTML = `<span class="err">not saved (${e.message}), retrying</span>`;
  }
}

function tick() {
  const left = Math.max(0, new Date(attempt.deadline) - Date.now());
  $("timer").textContent = `${Math.floor(left / 60000)}:${String(Math.floor(left / 1000) % 60).padStart(2, "0")}`;
  if (left === 0) { clearInterval(countdown); submitExam(); }
}

async function submitExam() {
  await autosave(); clearInterval(autosaveTimer);
  try {
    await api("POST", `/api/attempts/${attempt.attempt_id}/submit`);
    $("submitMsg").innerHTML = '<span class="ok">Submitted. MCQs are being marked.</span>';
  } catch (e) { $("submitMsg").innerHTML = `<span class="err">${e.message}</span>`; }
}

// ---------- Upload: ask the API for a presigned POST, then send the file straight to S3 ----------
async function upload() {
  const file = $("file").files[0];
  const assignment = document.querySelector('input[name="assignment"]:checked');
  if (!file || !assignment) { $("uploadMsg").textContent = "Choose a file first"; return; }
  $("uploadMsg").textContent = "Requesting upload link...";
  try {
    const { upload } = await api("POST", `/api/assignments/${assignment.value}/upload-url`,
      { filename: file.name, content_type: file.type || "application/octet-stream", size_bytes: file.size });
    const form = new FormData();
    Object.entries(upload.fields).forEach(([k, v]) => form.append(k, v));
    form.append("file", file); // must be the last field
    $("uploadMsg").textContent = `Uploading ${(file.size / 1048576).toFixed(1)} MB to S3...`;
    const res = await fetch(upload.url, { method: "POST", body: form });
    if (!res.ok) throw new Error(`S3 rejected the upload (${res.status})`);
    $("uploadMsg").innerHTML = '<span class="ok">Uploaded. Your tutor has been notified.</span>';
  } catch (e) { $("uploadMsg").innerHTML = `<span class="err">${e.message}</span>`; }
}

// ---------- Wire up ----------
$("loginBtn").onclick = async () => {
  $("loginMsg").textContent = "Signing in...";
  try {
    idToken = await signIn($("email").value.trim(), $("password").value);
    sessionStorage.setItem("idToken", idToken);
    $("login").classList.add("hidden"); $("app").classList.remove("hidden"); $("loginMsg").textContent = "";
    await loadHome();
  } catch (e) { $("loginMsg").innerHTML = `<span class="err">${e.message}</span>`; }
};
$("logoutBtn").onclick = logout;
$("submitBtn").onclick = submitExam;
$("uploadBtn").onclick = upload;
if (idToken) { $("login").classList.add("hidden"); $("app").classList.remove("hidden"); loadHome().catch(logout); }

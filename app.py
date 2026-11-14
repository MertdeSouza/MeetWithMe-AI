"""MeetWithMe AI - local web interface.

Start with:
    python app.py

Then open http://127.0.0.1:5000 (it opens automatically). The page is only
reachable from this computer.

Needs:  pip install flask
"""

import os
import re
import threading
import webbrowser

from flask import Flask, Response, jsonify, request

import live_analysis as LA
from live_session import LiveSession

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
SET_NAME_PATTERN = re.compile(r"^[\w\- ]{1,50}$")
MAX_QUESTION_LENGTH = 500
MAX_QUESTIONS = 200


# ==========================================
# QUESTION SETS ON DISK
# ==========================================

def set_path(name):
    """File for a set name, or None if the name is not allowed.

    "default" is questions.txt; every other set is questions/<name>.txt.
    Names may only contain letters, digits, spaces, "-" and "_", so a name
    can never point outside the questions folder.
    """
    name = name.strip()
    if name == "default":
        return LA.DEFAULT_QUESTIONS_FILE
    if not SET_NAME_PATTERN.fullmatch(name):
        return None
    return LA.QUESTIONS_DIR / f"{name}.txt"


def list_sets():
    names = []
    if LA.DEFAULT_QUESTIONS_FILE.is_file():
        names.append("default")
    if LA.QUESTIONS_DIR.is_dir():
        names.extend(path.stem for path in sorted(LA.QUESTIONS_DIR.glob("*.txt")))
    return names


def clean_questions(raw):
    """Validate a list of questions from the browser."""
    if not isinstance(raw, list) or len(raw) > MAX_QUESTIONS:
        return None

    cleaned = []
    for item in raw:
        if not isinstance(item, str):
            return None
        text = " ".join(item.split())
        if not text or len(text) > MAX_QUESTION_LENGTH:
            return None
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


# ==========================================
# THE WEB PAGE
# ==========================================

INDEX_HTML = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MeetWithMe AI</title>
<style>
:root{--bg:#f4f6f9;--card:#fff;--text:#1c2430;--muted:#667085;--line:#e1e5ea;
--accent:#2563eb;--accent-text:#fff;--danger:#dc2626;--ok:#15803d;--warn:#b45309;--soft:#eef2f7}
@media (prefers-color-scheme: dark){:root{--bg:#0e1217;--card:#171c23;--text:#e7eaee;
--muted:#9aa4b2;--line:#2a313b;--accent:#5b8def;--accent-text:#0b1220;--danger:#f87171;
--ok:#4ade80;--warn:#fbbf24;--soft:#1f2630}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:14px 20px;
background:var(--card);border-bottom:1px solid var(--line)}
h1{font-size:18px;margin:0;margin-right:auto}
h2{font-size:15px;margin:0 0 10px}
main{max-width:1100px;margin:0 auto;padding:16px 20px;display:grid;gap:16px}
.cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.4fr);gap:16px}
@media (max-width:800px){.cols{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
button{font:inherit;border:1px solid var(--line);background:var(--soft);color:var(--text);
padding:7px 14px;border-radius:8px;cursor:pointer}
button.primary{background:var(--accent);color:var(--accent-text);border-color:var(--accent)}
button.danger{background:var(--danger);color:#fff;border-color:var(--danger)}
button:disabled{opacity:.45;cursor:default}
input[type=text],select{font:inherit;color:var(--text);background:var(--card);
border:1px solid var(--line);border-radius:8px;padding:7px 10px;min-width:0}
.row{display:flex;gap:8px;margin-bottom:8px}
.row input[type=text],.row select{flex:1}
.pill{padding:3px 10px;border-radius:999px;background:var(--soft);font-size:13px}
.pill.on{background:var(--ok);color:#fff}
.timer{font-variant-numeric:tabular-nums;color:var(--muted)}
ul{list-style:none;margin:0 0 12px;padding:0}
li.q{display:flex;gap:8px;align-items:flex-start;padding:6px 0;border-bottom:1px solid var(--line)}
li.q span{flex:1;word-break:break-word}
li.q button{padding:0 8px;line-height:1.4}
.muted{color:var(--muted);font-size:13px}
.banner{padding:8px 12px;border-radius:8px;font-size:14px;display:none}
.banner.err{display:block;background:rgba(220,38,38,.12);color:var(--danger)}
.banner.warn{display:block;background:rgba(180,83,9,.12);color:var(--warn)}
.qa{margin-bottom:14px}
.qa h3{font-size:14px;margin:0 0 6px}
.ans{border-left:3px solid var(--accent);background:var(--soft);padding:8px 10px;
border-radius:0 8px 8px 0;margin-bottom:6px}
.ans .meta{font-size:12px;color:var(--muted);margin-top:2px}
.ans blockquote{margin:4px 0 0;font-size:13px;color:var(--muted);word-break:break-word}
pre{margin:0;white-space:pre-wrap;word-break:break-word;font:13px/1.5 ui-monospace,Consolas,monospace}
</style>
</head>
<body>
<header>
  <h1>MeetWithMe AI</h1>
  <span id="pill" class="pill">Hazır</span>
  <span id="timer" class="timer">00:00</span>
  <button id="start" class="primary">Başlat</button>
  <button id="stop" class="danger" disabled>Durdur</button>
</header>
<main>
  <div id="error" class="banner"></div>
  <div id="warning" class="banner"></div>
  <div class="cols">
    <section class="card">
      <h2>Sorular</h2>
      <div class="row">
        <input id="newq" type="text" maxlength="500" placeholder="Yeni soru yazın">
        <button id="addq">Ekle</button>
      </div>
      <ul id="questions"></ul>
      <p class="muted">Toplantı sürerken eklenen soru, o ana kadar konuşulanlara karşı hemen kontrol edilir.</p>
      <h2>Soru setleri</h2>
      <div class="row">
        <select id="sets"></select>
        <button id="loadset">Yükle</button>
      </div>
      <div class="row">
        <input id="setname" type="text" maxlength="50" placeholder="Set adı">
        <button id="saveset">Kaydet</button>
      </div>
      <p id="setmsg" class="muted"></p>
    </section>
    <section class="card">
      <h2>Cevaplar</h2>
      <div id="answers"></div>
    </section>
  </div>
  <section class="card">
    <h2>Son duyulan satırlar</h2>
    <pre id="recent" class="muted">Henüz bir şey yok.</pre>
  </section>
  <section id="reportcard" class="card" style="display:none">
    <h2>Rapor <span id="reportfile" class="muted"></span></h2>
    <pre id="report"></pre>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
const LABELS = {
  idle: "Hazır",
  loading: "Başlatılıyor (model yükleniyor)...",
  listening: "Dinleniyor",
  stopping: "Durduruluyor, kalan ses yazıya çevriliyor...",
  analyzing: "Son analiz yapılıyor..."
};
let busy = false, lastQuestions = "", lastAnswers = "", reportShownFor = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options) {
  try {
    const response = await fetch(path, options);
    let data = null;
    try { data = await response.json(); } catch (e) {}
    return { ok: response.ok, data };
  } catch (e) {
    return { ok: false, data: { error: "Sunucuya ulaşılamıyor." } };
  }
}
const post = (path, body) => api(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {})
});

function clock(seconds) {
  const s = Math.floor(seconds);
  const m = Math.floor(s / 60), r = s % 60;
  return String(m).padStart(2, "0") + ":" + String(r).padStart(2, "0");
}

function showBanner(id, text, kind) {
  const node = $(id);
  node.textContent = text || "";
  node.className = text ? "banner " + kind : "banner";
}

function renderQuestions(list, locked) {
  const key = JSON.stringify(list);
  if (key === lastQuestions) return;
  lastQuestions = key;
  const ul = $("questions");
  ul.replaceChildren();
  if (!list.length) {
    ul.appendChild(el("li", "muted", "Henüz soru yok."));
    return;
  }
  list.forEach((question) => {
    const li = el("li", "q");
    li.appendChild(el("span", "", question));
    const remove = el("button", "", "×");
    remove.title = "Soruyu sil";
    remove.addEventListener("click", async () => {
      await post("/api/questions/remove", { question });
      refresh();
    });
    li.appendChild(remove);
    ul.appendChild(li);
  });
}

function renderAnswers(questions, answers, enabled, running) {
  const key = JSON.stringify([questions, answers, enabled, running]);
  if (key === lastAnswers) return;
  lastAnswers = key;
  const box = $("answers");
  box.replaceChildren();
  if (!questions.length) {
    box.appendChild(el("p", "muted", "Önce soru ekleyin."));
    return;
  }
  questions.forEach((question) => {
    const block = el("div", "qa");
    block.appendChild(el("h3", "", question));
    const found = answers.filter((a) => a.question === question);
    if (!found.length) {
      const text = !enabled && running ? "Cevap takibi kapalı."
        : running ? "Henüz cevap bulunamadı." : "Henüz cevap yok.";
      block.appendChild(el("p", "muted", text));
    }
    found.forEach((a) => {
      const card = el("div", "ans");
      card.appendChild(el("div", "", a.answer));
      card.appendChild(el("div", "meta",
        "[" + clock(parseFloat(a.timestamp) || 0) + "] " + a.speaker + " · güven: " + a.confidence));
      card.appendChild(el("blockquote", "", "\\u201c" + a.evidence + "\\u201d"));
      block.appendChild(card);
    });
    box.appendChild(block);
  });
}

async function showReport(file) {
  if (reportShownFor === file) return;
  const response = await fetch("/api/report");
  if (!response.ok) return;
  reportShownFor = file;
  $("report").textContent = await response.text();
  $("reportfile").textContent = "(" + file + ")";
  $("reportcard").style.display = "block";
}

async function refresh() {
  if (busy) return;
  busy = true;
  try {
    const { ok, data: s } = await api("/api/state");
    if (!ok || !s) return;

    const running = s.state === "loading" || s.state === "listening";
    $("pill").textContent = LABELS[s.state] || s.state;
    $("pill").className = s.state === "listening" ? "pill on" : "pill";
    $("timer").textContent = clock(s.elapsed);
    $("start").disabled = s.state !== "idle";
    $("stop").disabled = !(s.state === "listening" || s.state === "loading");
    $("loadset").disabled = s.state !== "idle";

    showBanner("error", s.error || (s.last_error ? "Hata: " + s.last_error : ""), "err");
    showBanner("warning", s.warning, "warn");

    renderQuestions(s.questions, running);
    renderAnswers(s.questions, s.answers, s.analysis_enabled, running);
    $("recent").textContent = s.recent_lines.length
      ? s.recent_lines.join("\\n") : "Henüz bir şey yok.";

    if (s.state === "idle" && s.report_file) showReport(s.report_file);
    if (s.state === "loading") { reportShownFor = null; $("reportcard").style.display = "none"; }
  } finally {
    busy = false;
  }
}

async function loadSets(selected) {
  const { data } = await api("/api/sets");
  const select = $("sets");
  select.replaceChildren();
  const names = (data && data.sets) || [];
  names.forEach((name) => {
    const option = el("option", "", name === "default" ? "default (questions.txt)" : name);
    option.value = name;
    select.appendChild(option);
  });
  if (!names.length) {
    const none = el("option", "", "Kayıtlı set yok");
    none.value = "";
    select.appendChild(none);
  }
  if (selected) select.value = selected;
}

$("start").addEventListener("click", async () => {
  const result = await post("/api/start");
  if (!result.ok) showBanner("error", result.data && result.data.error, "err");
  refresh();
});
$("stop").addEventListener("click", async () => { await post("/api/stop"); refresh(); });

async function addQuestion() {
  const input = $("newq");
  const question = input.value.trim();
  if (!question) return;
  const result = await post("/api/questions/add", { question });
  if (result.ok) input.value = "";
  else showBanner("error", result.data && result.data.error, "err");
  refresh();
}
$("addq").addEventListener("click", addQuestion);
$("newq").addEventListener("keydown", (e) => { if (e.key === "Enter") addQuestion(); });

$("loadset").addEventListener("click", async () => {
  const name = $("sets").value;
  if (!name) return;
  const loaded = await api("/api/sets/" + encodeURIComponent(name));
  if (!loaded.ok) { $("setmsg").textContent = (loaded.data && loaded.data.error) || "Yüklenemedi."; return; }
  const result = await post("/api/questions/replace", { questions: loaded.data.questions });
  $("setmsg").textContent = result.ok ? "'" + name + "' yüklendi." : (result.data && result.data.error) || "Yüklenemedi.";
  refresh();
});

$("saveset").addEventListener("click", async () => {
  const name = $("setname").value.trim();
  const snapshot = await api("/api/state");
  const result = await post("/api/sets", { name, questions: snapshot.data.questions });
  $("setmsg").textContent = result.ok ? "'" + name + "' kaydedildi." : (result.data && result.data.error) || "Kaydedilemedi.";
  if (result.ok) { $("setname").value = ""; loadSets(name); }
});

loadSets();
refresh();
setInterval(refresh, 1500);
</script>
</body>
</html>
"""


# ==========================================
# SERVER
# ==========================================

def create_app(session):
    app = Flask(__name__)

    @app.before_request
    def guard():
        # Only this computer, and only our own page, may talk to the server.
        # This stops other websites from controlling it through the browser.
        if request.host.split(":")[0] not in ALLOWED_HOSTS:
            return jsonify(error="Erişim reddedildi."), 403

        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != f"http://{request.host}":
            return jsonify(error="Erişim reddedildi."), 403

        if request.method == "POST" and not request.is_json:
            return jsonify(error="JSON gerekli."), 415

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        response = Response(INDEX_HTML, mimetype="text/html")
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; connect-src 'self'; "
            "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
            "base-uri 'none'; form-action 'none'"
        )
        return response

    @app.get("/api/state")
    def state():
        return jsonify(session.snapshot())

    @app.post("/api/start")
    def start():
        try:
            session.start()
        except RuntimeError:
            return jsonify(error="Zaten çalışıyor."), 409
        return jsonify(ok=True)

    @app.post("/api/stop")
    def stop():
        if not session.stop():
            return jsonify(error="Durdurulacak bir oturum yok."), 409
        return jsonify(ok=True)

    @app.post("/api/questions/add")
    def add_question():
        body = request.get_json(silent=True) or {}
        cleaned = clean_questions([body.get("question", "")])
        if not cleaned:
            return jsonify(error="Geçersiz soru."), 400
        if len(session.questions) >= MAX_QUESTIONS:
            return jsonify(error="Çok fazla soru."), 400
        session.add_question(cleaned[0])
        return jsonify(ok=True)

    @app.post("/api/questions/remove")
    def remove_question():
        body = request.get_json(silent=True) or {}
        session.remove_question(str(body.get("question", "")))
        return jsonify(ok=True)

    @app.post("/api/questions/replace")
    def replace_questions():
        body = request.get_json(silent=True) or {}
        cleaned = clean_questions(body.get("questions"))
        if cleaned is None:
            return jsonify(error="Geçersiz soru listesi."), 400
        if not session.replace_questions(cleaned):
            return jsonify(
                error="Toplantı sürerken set yüklenemez. "
                      "Soruları tek tek ekleyin."
            ), 409
        return jsonify(ok=True)

    @app.get("/api/sets")
    def sets():
        return jsonify(sets=list_sets())

    @app.get("/api/sets/<name>")
    def read_set(name):
        path = set_path(name)
        if path is None:
            return jsonify(error="Geçersiz set adı."), 400
        if not path.is_file():
            return jsonify(error="Set bulunamadı."), 404
        return jsonify(questions=LA.load_questions(path))

    @app.post("/api/sets")
    def save_set():
        body = request.get_json(silent=True) or {}
        name = str(body.get("name", "")).strip()
        path = set_path(name)
        if path is None:
            return jsonify(
                error="Set adı yalnızca harf, rakam, boşluk, - ve _ içerebilir."
            ), 400

        cleaned = clean_questions(body.get("questions"))
        if not cleaned:
            return jsonify(error="Kaydedilecek soru yok."), 400

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
        return jsonify(ok=True)

    @app.get("/api/report")
    def report():
        text = session.report_text()
        if text is None:
            return jsonify(error="Rapor yok."), 404
        return Response(text, mimetype="text/plain; charset=utf-8")

    return app


def main():
    port = int(os.getenv("MEETWITHME_PORT", "5000"))

    initial = []
    if LA.DEFAULT_QUESTIONS_FILE.is_file():
        initial = LA.load_questions(LA.DEFAULT_QUESTIONS_FILE)

    session = LiveSession(questions=initial)
    app = create_app(session)

    url = f"http://127.0.0.1:{port}"
    print(f"MeetWithMe AI is running at {url}")
    print("Use the Stop button before closing this window, so the report is written.")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

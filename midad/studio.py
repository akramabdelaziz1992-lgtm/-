"""قوالب التجربة: موقع، لعبة، صورة، وصوت يشتغلوا من غير مفتاح."""

from __future__ import annotations

from midad.safety import Operation

SITE_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>بيت النور</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header class="top">
    <a class="logo" href="#start">بيت النور</a>
    <nav>
      <a href="#work">الأعمال</a>
      <a href="#method">المنهج</a>
      <a href="#visit">الزيارة</a>
    </nav>
  </header>
  <main id="start">
    <section class="hero">
      <p class="kicker">عمارة سكنية · الرياض</p>
      <h1>بيوت هادية، نورها مظبوط، وظلها محسوب.</h1>
      <p class="lead">نستوديو بيت النور يصمّم مساكن صغيرة بفناء داخلي، حجر الرياض، ونحاس قليل. كل بيت يتراجع عن الشارع ويحتفظ بهوائه.</p>
      <a class="action" href="#visit">احجز زيارة للورشة</a>
      <figure class="plan" aria-hidden="true">
        <svg viewBox="0 0 280 180">
          <rect width="280" height="180" fill="#efe4d4"/>
          <rect x="18" y="16" width="244" height="148" fill="none" stroke="#241910" stroke-width="3"/>
          <rect x="96" y="48" width="88" height="84" fill="#c96b45"/>
          <rect x="28" y="28" width="58" height="40" fill="#9a7040"/>
          <rect x="194" y="28" width="58" height="70" fill="#8d3b2b"/>
          <rect x="28" y="112" width="58" height="40" fill="#d7c4a8"/>
        </svg>
        <figcaption>مسقط فناء داخلي</figcaption>
      </figure>
    </section>
    <section id="work" class="work">
      <article>
        <span>٠١</span>
        <h2>دار العقيق</h2>
        <p>فناء ضيق، مجلس غربي، وشباك علوي ياخد نور المغرب من غير ما يكشف الجيران.</p>
      </article>
      <article>
        <span>٠٢</span>
        <h2>بيت الملقا</h2>
        <p>ثلاث غرف حول درج مفتوح. المطبخ على الحوش، والنوم في أهدى ضلع.</p>
      </article>
      <article>
        <span>٠٣</span>
        <h2>مجلس النخيل</h2>
        <p>مضافة مستقلة بسقف خشبي منخفض، وممر حجر يغسله رشاش خفيف قبل المغرب.</p>
      </article>
    </section>
    <section id="method" class="method">
      <h2>المنهج</h2>
      <ol>
        <li>نقيس الأرض والريح والشمس قبل أي رسمة واجهة.</li>
        <li>نثبت الفناء، وبعدين نرص الغرف حواليه.</li>
        <li>الخامات قليلة: حجر، جص، خشب، ونحاس في المقبض والضوء.</li>
      </ol>
    </section>
    <section id="visit" class="visit">
      <h2>الورشة مفتوحة الخميس</h2>
      <p>من ٤ العصر لـ ٨ المغرب، حي الملقا. الاتصال من النموذج، ومفيش رسوم على الزيارة الأولى.</p>
      <form id="visit-form">
        <label>الاسم<input name="name" required></label>
        <label>الجوال<input name="phone" required dir="ltr"></label>
        <button type="submit">أرسل الطلب</button>
        <p id="visit-note" role="status"></p>
      </form>
    </section>
  </main>
  <footer>بيت النور · الرياض · <span id="year"></span></footer>
  <script src="site.js"></script>
</body>
</html>
"""

SITE_CSS = """:root {
  color-scheme: light;
  --ink: #241910;
  --paper: #f4ecdf;
  --clay: #8d3b2b;
  --brass: #9a7040;
  --line: #ddcbb6;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: "Noto Sans Arabic", "Noto Naskh Arabic", sans-serif;
}
.top, .hero, .work, .method, .visit, footer {
  width: min(1040px, calc(100% - 32px));
  margin-inline: auto;
}
.top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 22px 0;
}
.logo { color: inherit; text-decoration: none; font-family: "Noto Kufi Arabic", sans-serif; font-size: 22px; }
nav { display: flex; gap: 16px; }
nav a { color: var(--brass); }
.hero { padding: 48px 0 24px; }
.kicker { letter-spacing: 0; color: var(--clay); margin: 0; }
h1 {
  font-family: "Noto Naskh Arabic", serif;
  font-size: clamp(36px, 6vw, 68px);
  line-height: 1.25;
  font-weight: 700;
  margin: 8px 0;
  max-width: 12ch;
}
.lead { max-width: 38rem; font-size: 18px; }
.plan { margin: 22px 0 0; max-width: 360px; }
.plan svg { width: 100%; height: auto; display: block; }
.plan figcaption { color: var(--brass); font-size: 14px; margin-top: 6px; }
.action {
  display: inline-block;
  background: var(--ink);
  color: var(--paper);
  text-decoration: none;
  padding: 12px 18px;
}
.work { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; padding: 20px 0 40px; }
.work article { border-top: 1px solid var(--line); padding-top: 12px; }
.work span { color: var(--brass); }
.method, .visit { padding-bottom: 36px; }
form { display: grid; gap: 10px; max-width: 420px; }
input, button { font: inherit; padding: 10px; }
button { background: var(--clay); color: white; border: 0; }
footer { padding: 20px 0 32px; color: var(--brass); }
@media (max-width: 800px) {
  .work { grid-template-columns: 1fr; }
  nav { display: none; }
}
"""

SITE_JS = """document.querySelector("#year").textContent = String(new Date().getFullYear());
document.querySelector("#visit-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  document.querySelector("#visit-note").textContent =
    "وصل طلب " + data.get("name") + ". هنكلمك على " + data.get("phone") + ".";
  event.currentTarget.reset();
});
"""

GAME_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>شرارة</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="hud">
    <strong>شرارة</strong>
    <span id="score">٠</span>
    <span id="lives">٣ محاولات</span>
    <button id="left" type="button">يسار</button>
    <button id="right" type="button">يمين</button>
    <button id="restart" type="button">من الأول</button>
  </div>
  <canvas id="board" width="960" height="540"></canvas>
  <p class="help">الأسهم يمين ويسار. اجمع الشرارة النحاسية وتفادى الرماد.</p>
  <script src="game.js"></script>
</body>
</html>
"""

GAME_CSS = """body {
  margin: 0;
  min-height: 100vh;
  background: #140f0c;
  color: #f3e6d4;
  font-family: "Noto Sans Arabic", sans-serif;
  display: grid;
  place-items: center;
  gap: 8px;
}
.hud { display: flex; gap: 16px; align-items: center; }
button { font: inherit; background: #e0a85a; color: #24180f; border: 0; padding: 6px 12px; }
canvas { width: min(960px, 100%); height: auto; background: #1c1612; border: 1px solid #4a3b2c; }
.help { margin: 0; color: #cbbba6; }
"""

GAME_JS = """const canvas = document.querySelector("#board");
const ctx = canvas.getContext("2d");
const scoreNode = document.querySelector("#score");
const livesNode = document.querySelector("#lives");
const arabic = new Intl.NumberFormat("ar");
const state = { x: 480, score: 0, lives: 3, sparks: [], over: false, left: false, right: false };
let audio;

function tone(freq, ms) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return;
  if (!audio) audio = new Ctx();
  if (audio.state === "suspended") audio.resume();
  const osc = audio.createOscillator();
  const gain = audio.createGain();
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0.04, audio.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + ms / 1000);
  osc.connect(gain);
  gain.connect(audio.destination);
  osc.start();
  osc.stop(audio.currentTime + ms / 1000);
}

function reset() {
  state.x = 480;
  state.score = 0;
  state.lives = 3;
  state.sparks = [];
  state.over = false;
  for (let i = 0; i < 5; i += 1) state.sparks.push(spawn(i * 90));
}

function spawn(y) {
  return { x: 40 + Math.random() * 880, y: y || -20, good: Math.random() > 0.28, speed: 2 + Math.random() * 2.4 };
}

document.addEventListener("keydown", (event) => {
  if (event.key === "ArrowLeft") state.left = true;
  if (event.key === "ArrowRight") state.right = true;
});
document.addEventListener("keyup", (event) => {
  if (event.key === "ArrowLeft") state.left = false;
  if (event.key === "ArrowRight") state.right = false;
});
document.querySelector("#restart").addEventListener("click", () => {
  tone(220, 120);
  reset();
});
function hold(id, key) {
  const node = document.querySelector(id);
  const down = (event) => {
    event.preventDefault();
    state[key] = true;
  };
  const up = () => {
    state[key] = false;
  };
  node.addEventListener("pointerdown", down);
  node.addEventListener("pointerup", up);
  node.addEventListener("pointerleave", up);
  node.addEventListener("pointercancel", up);
}
hold("#left", "left");
hold("#right", "right");

function frame() {
  if (!state.over) {
    if (state.left) state.x -= 6;
    if (state.right) state.x += 6;
    state.x = Math.max(30, Math.min(930, state.x));
    for (const spark of state.sparks) {
      spark.y += spark.speed;
      const hit = Math.abs(spark.x - state.x) < 28 && spark.y > 470 && spark.y < 520;
      if (hit) {
        if (spark.good) {
          state.score += 1;
          tone(660, 90);
        } else {
          state.lives -= 1;
          tone(140, 180);
        }
        spark.y = -20;
        spark.x = 40 + Math.random() * 880;
        spark.good = Math.random() > 0.28;
      } else if (spark.y > 560) {
        spark.y = -20;
        spark.x = 40 + Math.random() * 880;
      }
    }
    if (state.lives <= 0) state.over = true;
  }
  ctx.fillStyle = "#1c1612";
  ctx.fillRect(0, 0, 960, 540);
  ctx.fillStyle = "#3a2a1c";
  ctx.fillRect(0, 500, 960, 40);
  ctx.fillStyle = "#e0a85a";
  ctx.beginPath();
  ctx.arc(state.x, 492, 18, 0, Math.PI * 2);
  ctx.fill();
  for (const spark of state.sparks) {
    ctx.fillStyle = spark.good ? "#f2d48a" : "#8d3b2b";
    ctx.fillRect(spark.x - 6, spark.y, 12, 18);
  }
  if (state.over) {
    ctx.fillStyle = "#f3e6d4";
    ctx.font = "32px sans-serif";
    ctx.fillText("انتهت الجولة", 380, 260);
  }
  scoreNode.textContent = arabic.format(state.score);
  livesNode.textContent = arabic.format(state.lives) + " محاولات";
  requestAnimationFrame(frame);
}

reset();
requestAnimationFrame(frame);
"""

SOUND_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>صوت الشرارة</title>
  <style>
    body { font-family: "Noto Sans Arabic", sans-serif; background: #140f0c; color: #f3e6d4; display: grid; gap: 12px; place-content: center; min-height: 100vh; }
    button { font: inherit; padding: 12px 18px; background: #e0a85a; color: #24180f; border: 0; }
  </style>
</head>
<body>
  <h1>مؤثرات اللعبة</h1>
  <p>الصوت يتولد هنا في المتصفح، عشان المنتج يفضل قابل للبيع من غير أوزان بحثية.</p>
  <button type="button" id="catch">صوت الجمع</button>
  <button type="button" id="hit">صوت الخسارة</button>
  <button type="button" id="start">صوت البداية</button>
  <script src="sfx.js"></script>
</body>
</html>
"""

SOUND_JS = """let audio;
function tone(freq, ms) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return;
  if (!audio) audio = new Ctx();
  if (audio.state === "suspended") audio.resume();
  const osc = audio.createOscillator();
  const gain = audio.createGain();
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0.05, audio.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + ms / 1000);
  osc.connect(gain);
  gain.connect(audio.destination);
  osc.start();
  osc.stop(audio.currentTime + ms / 1000);
}
document.querySelector("#catch").addEventListener("click", () => tone(660, 90));
document.querySelector("#hit").addEventListener("click", () => tone(140, 180));
document.querySelector("#start").addEventListener("click", () => tone(220, 120));
"""

LANTERN_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 320" role="img" aria-label="فانوس نحاسي">
  <rect width="240" height="320" fill="#140f0c"/>
  <rect x="108" y="18" width="24" height="28" fill="#9a7040"/>
  <path d="M70 58h100l18 28v130l-28 42H80l-28-42V86z" fill="#e0a85a"/>
  <path d="M86 86h68v110H86z" fill="#f6e2b8"/>
  <path d="M120 96l16 28h-32z" fill="#8d3b2b"/>
  <circle cx="120" cy="250" r="8" fill="#241910"/>
</svg>
"""


def _creates(files: dict[str, str]) -> list[Operation]:
    return [Operation(op="create", path=path, content=content) for path, content in files.items()]


def studio_plan(mode: str, tree: list[str]):
    from midad.provider import Plan

    if mode == "site":
        if "web/index.html" in tree:
            return Plan(reply="موقع بيت النور موجود في web/index.html. المعاينة من زر المعاينة، والتعديل على نص موجود يبقى في وضع التعديل.")
        return Plan(
            reply="هبني موقع بيت النور: ثلاث أعمال، منهج، ونموذج زيارة. الملفات الجديدة بس، ومش هلمس باقي المشروع.",
            operations=_creates({"web/index.html": SITE_HTML, "web/styles.css": SITE_CSS, "web/site.js": SITE_JS}),
        )
    if mode == "game":
        if "play/index.html" in tree:
            return Plan(reply="لعبة شرارة موجودة في play/index.html. افتح المعاينة والعب بالأسهم.")
        return Plan(
            reply="هبني لعبة شرارة: فانوس يجمع الشرر ويتفادى الرماد، وفيها صوت. الملفات الجديدة تحت play/.",
            operations=_creates({"play/index.html": GAME_HTML, "play/style.css": GAME_CSS, "play/game.js": GAME_JS}),
        )
    if mode == "image":
        if "assets/lantern.svg" in tree:
            return Plan(reply="صورة الفانوس موجودة في assets/lantern.svg. توليد صورة جديدة من Gemini يحتاج مفتاح الصورة.")
        return Plan(
            reply="دي رسمة تجربة لفانوس نحاسي. صورة Gemini 3.1 تتكتب في نفس المجلد لما المفتاح يتوصل، وبعد مراجعتك.",
            operations=_creates({"assets/lantern.svg": LANTERN_SVG}),
        )
    if mode == "sound":
        if "sound/index.html" in tree:
            return Plan(reply="لوحة الصوت موجودة في sound/index.html. اضغط المعاينة وبعدين الأزرار.")
        return Plan(
            reply="هضيف مؤثرات الجمع والخسارة تتولد في المتصفح. Woosh من Sony رخصته العامة غير تجارية، فمش داخلة في البرنامج اللي هيتباع.",
            operations=_creates({"sound/index.html": SOUND_HTML, "sound/sfx.js": SOUND_JS}),
        )
    return None

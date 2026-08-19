/* プロンプトメーカー — 画面まわりの処理 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const HIST_KEY = "promptmaker.history.v1";

  let cat = null;      // 選択中のカテゴリ
  let qs = [];         // 表示対象の質問
  let idx = 0;         // いま何問目か
  let answers = {};    // {質問id: 値}
  let extras = [];     // 追加ルールの値
  let mode = "direct"; // direct | interview

  /* ---------------- 共通 ---------------- */
  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function show(pageId) {
    ["pHome", "pAsk", "pResult"].forEach((p) => $(p).classList.toggle("on", p === pageId));
    window.scrollTo(0, 0);
  }
  let toastTimer = null;
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.add("on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("on"), 1800);
  }

  /* ---------------- 回答の読み取りヘルパー ---------------- */
  function optOf(q, v) {
    return (q.opts || []).find((o) => o.v === v) || null;
  }
  function promptTextOf(q, v) {
    const o = optOf(q, v);
    if (!o) return "";
    return o.p === undefined ? o.l : o.p; // p:"" は「指定なし」＝出力しない
  }
  function labelOf(q, v) {
    const o = optOf(q, v);
    return o ? o.l : "";
  }
  function makeH() {
    const find = (id) => qs.find((q) => q.id === id) || cat.questions.find((q) => q.id === id);
    const list = (id) => {
      const q = find(id);
      const a = answers[id];
      if (!q || a === undefined || a === null || a === "") return [];
      if (q.type === "multi") return a.map((v) => promptTextOf(q, v)).filter(Boolean);
      if (q.type === "choice") { const s = promptTextOf(q, a); return s ? [s] : []; }
      const s = String(a).trim();
      return s ? [s] : [];
    };
    return {
      raw: (id) => answers[id],
      has: (id, v) => {
        const a = answers[id];
        return Array.isArray(a) ? a.indexOf(v) >= 0 : a === v;
      },
      list: list,
      t: (id) => list(id).join("、")
    };
  }
  /* 画面に見せるとき用（インタビュー版・履歴タイトル） */
  function displayAnswer(q) {
    const a = answers[q.id];
    if (a === undefined || a === null || a === "") return "";
    if (q.type === "multi") return a.map((v) => labelOf(q, v)).filter(Boolean).join("、");
    if (q.type === "choice") return labelOf(q, a);
    return String(a).trim();
  }

  /* ---------------- ホーム ---------------- */
  function renderHome() {
    $("cats").innerHTML = CATEGORIES.map((c) =>
      '<button class="cat" data-id="' + c.id + '">' +
        '<span class="ic">' + c.icon + "</span>" +
        '<span class="ti">' + esc(c.title) + "</span>" +
        '<span class="de">' + esc(c.desc) + "</span>" +
      "</button>").join("");
    $("cats").querySelectorAll(".cat").forEach((b) => {
      b.addEventListener("click", () => start(b.dataset.id));
    });
    renderHistory();
  }

  /* ---------------- 履歴 ---------------- */
  function loadHistory() {
    try { return JSON.parse(localStorage.getItem(HIST_KEY)) || []; } catch (e) { return []; }
  }
  function saveHistory(list) {
    try { localStorage.setItem(HIST_KEY, JSON.stringify(list.slice(0, 20))); } catch (e) { /* 容量オーバーは無視 */ }
  }
  function pushHistory() {
    const title = historyTitle();
    const list = loadHistory().filter((h) => !(h.catId === cat.id && h.title === title));
    list.unshift({ catId: cat.id, title: title, answers: answers, extras: extras, ts: Date.now() });
    saveHistory(list);
  }
  function historyTitle() {
    for (const q of cat.questions) {
      if (q.type === "text" || q.type === "textarea") {
        const v = (answers[q.id] || "").trim();
        if (v) return v.length > 26 ? v.slice(0, 26) + "…" : v;
      }
    }
    return cat.title;
  }
  function renderHistory() {
    const list = loadHistory();
    $("histWrap").style.display = list.length ? "" : "none";
    if (!list.length) return;
    $("hist").innerHTML = list.map((h, i) => {
      const c = CATEGORIES.find((x) => x.id === h.catId);
      const d = new Date(h.ts);
      const when = (d.getMonth() + 1) + "/" + d.getDate();
      return '<div class="hist">' +
        '<button class="open" data-i="' + i + '">' +
          '<div class="ht">' + (c ? c.icon : "📄") + " " + esc(h.title) + "</div>" +
          '<div class="hd">' + (c ? esc(c.title) : "") + " ・ " + when + "</div>" +
        "</button>" +
        '<button class="del" data-del="' + i + '" aria-label="削除">✕</button>' +
      "</div>";
    }).join("");
    $("hist").querySelectorAll(".open").forEach((b) => b.addEventListener("click", () => {
      const h = loadHistory()[+b.dataset.i];
      if (!h) return;
      const c = CATEGORIES.find((x) => x.id === h.catId);
      if (!c) return;
      cat = c; answers = h.answers || {}; extras = h.extras || [];
      refresh(); idx = qs.length - 1; mode = "direct";
      renderResult(); show("pResult");
    }));
    $("hist").querySelectorAll(".del").forEach((b) => b.addEventListener("click", () => {
      const list2 = loadHistory();
      list2.splice(+b.dataset.del, 1);
      saveHistory(list2);
      renderHistory();
    }));
  }

  /* ---------------- 質問フロー ---------------- */
  /* when を持つ質問は、条件を満たすときだけ表示する（例：チラシを選んだときだけ聞く） */
  function refresh() {
    qs = cat.questions.filter(function (q) { return !q.when || q.when(answers); });
  }
  /* 質問を1つ進む／戻る。表示対象が変わっても迷子にならないよう、
     いまの質問のIDを基準に位置を数え直す */
  function move(dir) {
    const cur = qs[idx];
    refresh();
    let at = qs.findIndex(function (q) { return q.id === cur.id; });
    if (at < 0) at = Math.min(idx, qs.length - 1); /* いまの質問が隠れた場合 */
    return at + dir;
  }

  function start(catId) {
    cat = CATEGORIES.find((c) => c.id === catId);
    if (!cat) return;
    answers = {};
    refresh();
    extras = []; idx = 0; mode = "direct";
    renderQuestion();
    show("pAsk");
  }

  function renderQuestion() {
    refresh();
    if (idx > qs.length - 1) idx = qs.length - 1;
    const q = qs[idx];
    $("barIn").style.width = Math.round((idx / qs.length) * 100) + "%";
    $("stepTxt").textContent = cat.icon + " " + cat.title + " ・ " + (idx + 1) + " / " + qs.length;
    $("qText").textContent = q.q;
    $("qNote").textContent = q.note || "";
    $("qNote").style.display = q.note ? "" : "none";
    $("btnBack").textContent = idx === 0 ? "← やめる" : "← もどる";
    $("btnNext").textContent = idx === qs.length - 1 ? "プロンプトをつくる ✨" : "つぎへ";
    $("skipWrap").style.display = q.optional ? "" : "none";

    const body = $("qBody");
    body.innerHTML = "";

    if (q.type === "choice" || q.type === "multi") {
      const wrap = document.createElement("div");
      wrap.className = "opts";
      q.opts.forEach((o) => {
        const b = document.createElement("button");
        b.className = "opt";
        b.type = "button";
        b.innerHTML = esc(o.l) + (o.hint ? '<span class="oh">' + esc(o.hint) + "</span>" : "");
        const selected = q.type === "multi"
          ? (answers[q.id] || []).indexOf(o.v) >= 0
          : answers[q.id] === o.v;
        if (selected) b.classList.add("on");
        b.addEventListener("click", () => {
          if (q.type === "multi") {
            const cur = answers[q.id] || [];
            const at = cur.indexOf(o.v);
            if (at >= 0) cur.splice(at, 1); else cur.push(o.v);
            answers[q.id] = cur;
            b.classList.toggle("on");
            updateNext();
          } else {
            answers[q.id] = o.v;
            wrap.querySelectorAll(".opt").forEach((x) => x.classList.remove("on"));
            b.classList.add("on");
            setTimeout(next, 130); // 単一選択は押したら自動で進む
          }
        });
        wrap.appendChild(b);
      });
      body.appendChild(wrap);
    } else {
      const el = document.createElement(q.type === "textarea" ? "textarea" : "input");
      if (q.type !== "textarea") el.type = "text";
      el.placeholder = q.ph || "";
      el.value = answers[q.id] || "";
      el.addEventListener("input", () => { answers[q.id] = el.value; updateNext(); });
      if (q.type !== "textarea") {
        el.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); next(); } });
      }
      body.appendChild(el);
      setTimeout(() => el.focus(), 60);
    }
    updateNext();
  }

  function answered(q) {
    const a = answers[q.id];
    if (a === undefined || a === null) return false;
    if (Array.isArray(a)) return a.length > 0;
    return String(a).trim() !== "";
  }
  function updateNext() {
    const q = qs[idx];
    $("btnNext").disabled = !q.optional && !answered(q);
  }
  function next() {
    const q = qs[idx];
    if (!q.optional && !answered(q)) { toast("この質問は答えが必要です"); return; }
    const at = move(1);
    if (at < qs.length) { idx = at; renderQuestion(); }
    else { idx = qs.length - 1; finish(); }
  }
  function back() {
    if (idx === 0) { show("pHome"); renderHistory(); return; }
    const at = move(-1);
    idx = Math.max(0, at);
    renderQuestion();
  }
  function finish() {
    pushHistory();
    renderResult();
    show("pResult");
    renderHistory();
  }

  /* ---------------- プロンプト生成 ---------------- */
  function extraLines() {
    return extras
      .map((v) => (EXTRAS.find((e) => e.v === v) || {}).p)
      .filter(Boolean)
      .map((s) => "- " + s);
  }
  function buildDirect() {
    let text = cat.build(makeH());
    const ex = extraLines();
    if (ex.length) text += "\n\n【追加のルール】\n" + ex.join("\n");
    return text;
  }
  function buildInterview() {
    const known = qs.map((q) => {
      const v = displayAnswer(q);
      if (!v) return null;
      const label = q.q.replace(/（いくつでも）/g, "").replace(/[？?]\s*$/, "");
      return "- " + label + "： " + v;
    }).filter(Boolean);

    const ex = extraLines();

    return [
      "あなたは一流のプロンプトエンジニアです。\n" +
      "私はAIに、" + (cat.goal || cat.title) + "つもりです。そのための最高のプロンプトを、私に質問しながら一緒に作ってください。",

      "【いま分かっていること】\n" + (known.length ? known.join("\n") : "- まだほとんど決まっていません"),

      ex.length ? "【完成するプロンプトに必ず入れてほしいルール】\n" + ex.join("\n") : null,

      "【進めかた】\n" +
      "1. 足りない情報を、1回につき3問までにしぼって質問してください。私が選ぶだけで答えられるよう、必ず選択肢（A/B/C…）と「おまかせ」を付けてください。\n" +
      "2. 私の答えを見て、必要ならもう1〜2回だけ質問を重ねてください。長引かせないでください。\n" +
      "3. 情報がそろったら「これで作ります」と宣言し、完成したプロンプトをコピーしやすいようにコードブロックで出してください。\n" +
      "4. 最後に、そのプロンプトをどのAIサービスに貼るのがよいか、使うときのコツを3つ教えてください。",

      "専門用語は使わず、やさしい日本語でお願いします。では、1つ目の質問からどうぞ。"
    ].filter(Boolean).join("\n\n");
  }
  function currentPrompt() {
    return mode === "interview" ? buildInterview() : buildDirect();
  }

  /* ---------------- 結果画面 ---------------- */
  function renderResult() {
    $("tabDirect").classList.toggle("on", mode === "direct");
    $("tabInterview").classList.toggle("on", mode === "interview");
    $("modeNote").textContent = mode === "interview"
      ? "AIがあなたに質問して、最後にプロンプトを仕上げてくれます。イメージが固まっていないときはこちら。"
      : "コピーしてAIに貼るだけ。画像やファイルがある場合は一緒に添付してください。";
    $("promptBox").textContent = currentPrompt();

    $("chips").innerHTML = EXTRAS.map((e) =>
      '<button class="chip' + (extras.indexOf(e.v) >= 0 ? " on" : "") + '" data-v="' + e.v + '">' + esc(e.l) + "</button>"
    ).join("");
    $("chips").querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => {
      const v = b.dataset.v;
      const at = extras.indexOf(v);
      if (at >= 0) extras.splice(at, 1); else extras.push(v);
      b.classList.toggle("on");
      $("promptBox").textContent = currentPrompt();
    }));

    $("tools").innerHTML = cat.tools.map((t, i) =>
      '<div class="tool"><div class="no">' + (i + 1) + "</div><div>" +
        '<div class="nm">' + esc(t.name) + "</div>" +
        '<div class="wh">' + esc(t.why) + "</div>" +
      "</div></div>").join("") +
      '<div class="wh" style="font-size:.72rem;color:var(--ink-light);margin-top:8px">' +
      "※ おすすめは目安です。使い慣れたAIがあれば、それに貼っても十分に効きます。</div>";

    $("tips").innerHTML = cat.tips.map((t) => "<li>" + esc(t) + "</li>").join("");
  }

  async function copyPrompt() {
    const text = currentPrompt();
    try {
      await navigator.clipboard.writeText(text);
      toast("コピーしました！AIに貼ってください");
      return;
    } catch (e) { /* 下のやり方で再挑戦 */ }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    toast(ok ? "コピーしました！AIに貼ってください" : "コピーできませんでした。長押しして選択してください");
  }

  /* ---------------- イベント ---------------- */
  $("btnNext").addEventListener("click", next);
  $("btnBack").addEventListener("click", back);
  $("btnSkip").addEventListener("click", () => { delete answers[qs[idx].id]; next(); });
  $("btnCopy").addEventListener("click", copyPrompt);
  $("tabDirect").addEventListener("click", () => { mode = "direct"; renderResult(); });
  $("tabInterview").addEventListener("click", () => { mode = "interview"; renderResult(); });
  $("btnEdit").addEventListener("click", () => { idx = qs.length - 1; renderQuestion(); show("pAsk"); });
  $("btnHome").addEventListener("click", () => { show("pHome"); renderHistory(); });

  renderHome();
})();

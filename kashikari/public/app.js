/* 家族の貸し借りノート — 画面まわり
   サーバーにつながっていれば家族みんなで共有、
   つながらないときは「この端末だけ」で動きます。 */

/* ============================================================
   小さな道具
   ============================================================ */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const yen = (n) => "¥" + Math.round(n).toLocaleString("ja-JP");
const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

function todayStr() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
}
function jpDate(s) {
  const [y, m, d] = s.split("-");
  return Number(m) + "月" + Number(d) + "日";
}
function jpDateFull(s) {
  const [y, m, d] = s.split("-");
  return y + "年" + Number(m) + "月" + Number(d) + "日";
}

let toastTimer = null;
function toast(msg, isError) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("err", !!isError);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}

/* ============================================================
   データの置き場所
   ------------------------------------------------------------
   記録は、家族のパソコン（サーバー）だけに置きます。
   端末ごとに別々の記録ができてしまうと混乱するので、
   つながっていないときは「見るだけ」にして、記録はさせません。
   ============================================================ */
let online = true; // 家族のパソコン（サーバー）につながっているか
let data = { version: 0, members: [], entries: [] };

/* つながっていないときのエラー。
   お金の記録なので、共有できないまま入力させてしまわないようにします。 */
function offlineError() {
  const err = new Error("いま家族のパソコンにつながっていません。パソコンが起動しているか確かめてください");
  err.offline = true;
  return err;
}

/* 受け取った内容を、かならず決まった形にそろえてから使う */
function setData(got) {
  data = {
    version: Number(got && got.version) || 0,
    members: Array.isArray(got && got.members) ? got.members : [],
    entries: Array.isArray(got && got.entries) ? got.entries : [],
  };
}

async function api(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (_) {
    throw offlineError(); // 電波が切れた・パソコンが止まった
  }
  let json = null;
  try {
    json = await res.json();
  } catch (_) {}
  if (!res.ok) throw new Error((json && json.error) || "うまく保存できませんでした");
  return json || {};
}

/* 画面から呼ぶのはこの store だけ */
const store = {
  async refresh() {
    const got = await api("GET", "/api/state?since=" + data.version);
    if (got.unchanged) return false;
    setData(got);
    return true;
  },
  async addMember(name) {
    requireOnline();
    setData(await api("POST", "/api/members", { name }));
  },
  async renameMember(id, name) {
    requireOnline();
    setData(await api("PATCH", "/api/members/" + id, { name }));
  },
  async deleteMember(id) {
    requireOnline();
    setData(await api("DELETE", "/api/members/" + id));
  },
  async addEntry(entry) {
    requireOnline();
    setData(await api("POST", "/api/entries", entry));
  },
  async updateEntry(id, patch) {
    requireOnline();
    setData(await api("PATCH", "/api/entries/" + id, patch));
  },
  async deleteEntry(id) {
    requireOnline();
    setData(await api("DELETE", "/api/entries/" + id));
  },
};

/* つながっていないときは、記録も修正もさせない */
function requireOnline() {
  if (!online) throw offlineError();
}

/* ============================================================
   計算
   ------------------------------------------------------------
   返したお金は「古い貸しから順に」自動であてていきます。
   そうすると、1件ごとに「いつ借りて、いつ返し終わったか」が
   わかるようになります。
   ============================================================ */

const nameOf = (id) => {
  const m = data.members.find((x) => x.id === id);
  return m ? m.name : "（消えた人）";
};

function cmpEntry(a, b) {
  if (a.date !== b.date) return a.date < b.date ? -1 : 1;
  const ac = a.createdAt || "", bc = b.createdAt || "";
  if (ac !== bc) return ac < bc ? -1 : 1;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/* 「貸した人 → 借りた人」の向きごとにまとめる */
function analyze() {
  const groups = new Map();
  for (const e of data.entries) {
    const lender = e.kind === "loan" ? e.from : e.to;
    const borrower = e.kind === "loan" ? e.to : e.from;
    const key = lender + "|" + borrower;
    if (!groups.has(key)) groups.set(key, { lender, borrower, events: [] });
    groups.get(key).events.push(e);
  }

  const result = new Map();
  for (const [key, g] of groups) {
    g.events.sort(cmpEntry);
    const loans = [];
    let advance = []; // 貸すより先に渡していた分（前払い）

    for (const e of g.events) {
      if (e.kind === "loan") {
        const lo = { entry: e, total: e.amount, paid: 0, payments: [], settledDate: null };
        while (advance.length && lo.paid < lo.total) {
          const c = advance[0];
          const use = Math.min(c.left, lo.total - lo.paid);
          lo.paid += use;
          c.left -= use;
          lo.payments.push({ entry: c.entry, amount: use });
          if (c.left === 0) advance.shift();
        }
        loans.push(lo);
      } else {
        let rest = e.amount;
        for (const lo of loans) {
          if (rest <= 0) break;
          if (lo.paid >= lo.total) continue;
          const use = Math.min(rest, lo.total - lo.paid);
          lo.paid += use;
          rest -= use;
          lo.payments.push({ entry: e, amount: use });
        }
        if (rest > 0) advance.push({ entry: e, left: rest });
      }
    }

    for (const lo of loans) {
      if (lo.paid >= lo.total && lo.payments.length) {
        lo.settledDate = lo.payments.reduce((acc, p) => (p.entry.date > acc ? p.entry.date : acc), lo.payments[0].entry.date);
      }
    }

    result.set(key, {
      lender: g.lender,
      borrower: g.borrower,
      loans,
      outstanding: loans.reduce((s, l) => s + (l.total - l.paid), 0),
      advance: advance.reduce((s, c) => s + c.left, 0),
    });
  }
  return result;
}

/* 2人のあいだの差引をまとめる */
function summarize() {
  const analysis = analyze();
  const rawNet = new Map(); // "A|B" → B が A に返していない額
  for (const [key, g] of analysis) rawNet.set(key, g.outstanding - g.advance);

  const pairs = [];
  const seen = new Set();
  for (const [key, g] of analysis) {
    const a = g.lender, b = g.borrower;
    const unordered = [a, b].sort().join("::");
    if (seen.has(unordered)) continue;
    seen.add(unordered);
    const net = (rawNet.get(a + "|" + b) || 0) - (rawNet.get(b + "|" + a) || 0);
    if (Math.round(net) === 0) continue;
    // net > 0 なら b が a に返す側
    pairs.push(net > 0 ? { creditor: a, debtor: b, amount: net } : { creditor: b, debtor: a, amount: -net });
  }
  pairs.sort((x, y) => y.amount - x.amount);

  const people = new Map();
  const touch = (id) => {
    if (!people.has(id)) people.set(id, { id, lent: 0, borrowed: 0 });
    return people.get(id);
  };
  for (const m of data.members) touch(m.id);
  for (const p of pairs) {
    touch(p.creditor).lent += p.amount;
    touch(p.debtor).borrowed += p.amount;
  }

  return {
    analysis,
    pairs,
    people: data.members.map((m) => {
      const p = people.get(m.id);
      return { member: m, lent: p.lent, borrowed: p.borrowed, net: p.lent - p.borrowed };
    }),
    total: pairs.reduce((s, p) => s + p.amount, 0),
  };
}

const AVATAR_COLORS = ["#4fc49b", "#ff8fab", "#ffb86b", "#8ab6ff", "#b48ae0", "#5fc4c4", "#e0a04f"];
function avatarColor(id) {
  const idx = data.members.findIndex((m) => m.id === id);
  return AVATAR_COLORS[(idx < 0 ? 0 : idx) % AVATAR_COLORS.length];
}
function avatarHtml(id) {
  const n = nameOf(id);
  return '<span class="avatar" style="background:' + avatarColor(id) + '">' + esc(n.slice(0, 1)) + "</span>";
}

/* ============================================================
   画面の描きかえ
   ============================================================ */

let lastMemberSig = "";

function renderAll() {
  const sum = summarize();
  renderBalance(sum);
  renderSelects();
  renderHistory();
  renderMembers();
  updatePreview();
  updateSaveAvailability();
}

function renderBalance(sum) {
  $("#totalOutstanding").textContent = yen(sum.total);

  if (!data.members.length) {
    $("#personList").innerHTML = online
      ? '<div class="empty">まだ家族が登録されていません。<br>下の「⚙️ 設定」から名前を追加してください。</div>'
      : '<div class="empty">家族のパソコンにつながっていないため、<br>記録を読みこめませんでした。<br>パソコンが起動しているか確かめてください。</div>';
    $("#pairList").innerHTML = '<div class="empty">記録がありません</div>';
    return;
  }

  $("#personList").innerHTML = sum.people
    .map((p) => {
      const cls = p.net > 0 ? "plus" : p.net < 0 ? "minus" : "zero";
      const label = p.net > 0 ? "貸している" : p.net < 0 ? "借りている" : "貸し借りなし";
      const sub =
        p.lent || p.borrowed
          ? "貸し " + yen(p.lent) + " ／ 借り " + yen(p.borrowed)
          : "いまは貸し借りなし";
      return (
        '<div class="person-row">' +
        avatarHtml(p.member.id) +
        '<div class="person-main"><div class="person-name">' + esc(p.member.name) + "</div>" +
        '<div class="person-sub">' + sub + "</div></div>" +
        '<div class="person-amt ' + cls + '">' + (p.net === 0 ? "—" : yen(Math.abs(p.net))) +
        '<div class="person-sub" style="text-align:right">' + label + "</div></div></div>"
      );
    })
    .join("");

  if (!sum.pairs.length) {
    $("#pairList").innerHTML =
      '<div class="empty">返していないお金はありません 🎉<br>ぜんぶ精算ずみです。</div>';
    return;
  }

  $("#pairList").innerHTML = sum.pairs
    .map(
      (p) =>
        '<button type="button" class="pair-row" data-pair="' + esc(p.creditor) + "::" + esc(p.debtor) + '">' +
        avatarHtml(p.debtor) +
        '<span class="pair-text"><b>' + esc(nameOf(p.debtor)) + "</b> が <b>" + esc(nameOf(p.creditor)) +
        "</b> に返す</span>" +
        '<span class="pair-amt minus">' + yen(p.amount) + "</span>" +
        '<span class="chev">›</span></button>'
    )
    .join("");
}

function renderSelects() {
  const sig = data.members.map((m) => m.id + ":" + m.name).join(",");
  if (sig === lastMemberSig) return;
  lastMemberSig = sig;

  const opts = data.members.map((m) => '<option value="' + esc(m.id) + '">' + esc(m.name) + "</option>").join("");
  const from = $("#fromSel"), to = $("#toSel");
  const keepFrom = from.value, keepTo = to.value;
  from.innerHTML = opts;
  to.innerHTML = opts;
  if (data.members.some((m) => m.id === keepFrom)) from.value = keepFrom;
  if (data.members.some((m) => m.id === keepTo)) to.value = keepTo;
  if (!from.value && data.members[0]) from.value = data.members[0].id;
  if ((!to.value || to.value === from.value) && data.members[1]) to.value = data.members[1].id;

  const fm = $("#filterMember");
  const keep = fm.value;
  fm.innerHTML = '<option value="all">全員</option>' + opts;
  fm.value = data.members.some((m) => m.id === keep) ? keep : "all";
}

function monthsInData() {
  const set = new Set(data.entries.map((e) => e.date.slice(0, 7)));
  return Array.from(set).sort().reverse();
}

function renderHistory() {
  const fm = $("#filterMember").value;
  const fk = $("#filterKind").value;

  // 月の選択肢を作り直す（選んでいた月は残す）
  const monthSel = $("#filterMonth");
  const keepMonth = monthSel.value;
  const months = monthsInData();
  monthSel.innerHTML =
    '<option value="all">すべての月</option>' +
    months.map((m) => {
      const [y, mm] = m.split("-");
      return '<option value="' + m + '">' + y + "年" + Number(mm) + "月</option>";
    }).join("");
  monthSel.value = months.includes(keepMonth) ? keepMonth : "all";

  const list = data.entries
    .filter((e) => (fm === "all" ? true : e.from === fm || e.to === fm))
    .filter((e) => (fk === "all" ? true : e.kind === fk))
    .filter((e) => (monthSel.value === "all" ? true : e.date.startsWith(monthSel.value)))
    .sort((a, b) => -cmpEntry(a, b));

  $("#historyCount").textContent = list.length ? list.length + "件" : "";

  if (!list.length) {
    $("#historyList").innerHTML = '<div class="empty">この条件の記録はありません</div>';
    return;
  }

  let html = "";
  let currentMonth = "";
  for (const e of list) {
    const m = e.date.slice(0, 7);
    if (m !== currentMonth) {
      currentMonth = m;
      const [y, mm] = m.split("-");
      html += '<div class="month-head">' + y + "年" + Number(mm) + "月</div>";
    }
    const isLoan = e.kind === "loan";
    const lender = isLoan ? e.from : e.to;
    const borrower = isLoan ? e.to : e.from;
    const title = isLoan
      ? "<b>" + esc(nameOf(lender)) + "</b> が <b>" + esc(nameOf(borrower)) + "</b> に貸した"
      : "<b>" + esc(nameOf(borrower)) + "</b> が <b>" + esc(nameOf(lender)) + "</b> に返した";
    html +=
      '<button type="button" class="entry-row" data-entry="' + esc(e.id) + '">' +
      '<span class="entry-icon ' + e.kind + '">' + (isLoan ? "💸" : "🙏") + "</span>" +
      '<span class="entry-main"><span class="entry-title">' + title + "</span>" +
      '<span class="entry-sub">' + jpDate(e.date) + (e.note ? "・" + esc(e.note) : "") + "</span></span>" +
      '<span class="entry-amt ' + (isLoan ? "minus" : "plus") + '">' + yen(e.amount) + "</span></button>";
  }
  $("#historyList").innerHTML = html;
}

function renderMembers() {
  if (!data.members.length) {
    $("#memberList").innerHTML = '<div class="empty">まだ誰もいません</div>';
    return;
  }
  $("#memberList").innerHTML = data.members
    .map(
      (m) =>
        '<div class="member-row">' +
        avatarHtml(m.id) +
        '<span class="nm">' + esc(m.name) + "</span>" +
        '<button type="button" class="icon-btn" data-rename="' + esc(m.id) + '" title="名前を直す">✏️</button>' +
        '<button type="button" class="icon-btn" data-delmember="' + esc(m.id) + '" title="消す">🗑️</button>' +
        "</div>"
    )
    .join("");
}

/* ============================================================
   記録するページ
   ============================================================ */

let addKind = "loan";

function updateKindLabels() {
  const loan = addKind === "loan";
  $("#fromLabel").textContent = loan ? "貸した人" : "返した人";
  $("#toLabel").textContent = loan ? "借りた人" : "受け取る人";
  $$("#kindSeg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.kind === addKind)));
}

function updatePreview() {
  const from = $("#fromSel").value;
  const to = $("#toSel").value;
  const amt = Number($("#amountInput").value);
  const el = $("#addPreview");
  if (!data.members.length) {
    el.textContent = "先に「⚙️ 設定」で家族の名前を追加してください";
    return;
  }
  if (!from || !to || from === to) {
    el.textContent = "ちがう人どうしを選んでください";
    return;
  }
  if (!amt || amt <= 0) {
    el.textContent = "金額を入れてください";
    return;
  }
  const d = $("#dateInput").value || todayStr();
  el.innerHTML =
    jpDateFull(d) + "<br><b>" + esc(nameOf(from)) + "</b> が <b>" + esc(nameOf(to)) + "</b> に " +
    "<b>" + yen(amt) + "</b> " + (addKind === "loan" ? "貸した" : "返した");
}

async function saveEntry() {
  const from = $("#fromSel").value;
  const to = $("#toSel").value;
  const amount = Math.round(Number($("#amountInput").value));
  const date = $("#dateInput").value || todayStr();
  const note = $("#noteInput").value.trim();

  if (!online) return toast("いま家族のパソコンにつながっていません。記録できません", true);
  if (!from || !to) return toast("人を選んでください", true);
  if (from === to) return toast("ちがう人どうしを選んでください", true);
  if (!amount || amount <= 0) return toast("金額を入れてください", true);

  const btn = $("#saveBtn");
  btn.disabled = true;
  try {
    await store.addEntry({ kind: addKind, from, to, amount, date, note });
    $("#amountInput").value = "";
    $("#noteInput").value = "";
    $("#dateInput").value = todayStr();
    renderAll();
    toast(addKind === "loan" ? "貸した記録をつけました" : "返した記録をつけました");
    showPage("balance");
  } catch (e) {
    if (e.offline) goOffline();
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

/* ============================================================
   シート（下から出る画面）
   ============================================================ */

function openSheet(title, html, after) {
  $("#sheetTitle").textContent = title;
  $("#sheetBody").innerHTML = html;
  $("#sheetBg").classList.add("show");
  if (after) after($("#sheetBody"));
}
function closeSheet() {
  $("#sheetBg").classList.remove("show");
  $("#sheetBody").innerHTML = "";
}

/* --- 2人の貸し借り明細 --- */
function openPairSheet(creditorId, debtorId) {
  const sum = summarize();
  const pair = sum.pairs.find((p) => p.creditor === creditorId && p.debtor === debtorId);
  const amount = pair ? pair.amount : 0;

  const dirs = [
    { g: sum.analysis.get(creditorId + "|" + debtorId), lender: creditorId, borrower: debtorId },
    { g: sum.analysis.get(debtorId + "|" + creditorId), lender: debtorId, borrower: creditorId },
  ];

  let html =
    '<div class="preview" style="background:var(--mint-soft)">' +
    (amount > 0
      ? "<b>" + esc(nameOf(debtorId)) + "</b> が <b>" + esc(nameOf(creditorId)) + "</b> に<br><b>" + yen(amount) + "</b> 返す予定です"
      : "いまは貸し借りなしです 🎉") +
    "</div>";

  if (amount > 0) {
    html +=
      '<button type="button" class="btn primary" id="settleBtn" style="margin-bottom:14px">🙏 ' +
      yen(amount) + " ぜんぶ返した記録をつける</button>";
  }

  for (const d of dirs) {
    if (!d.g || !d.g.loans.length) continue;
    html += '<div class="card"><h2>💸 ' + esc(nameOf(d.lender)) + " → " + esc(nameOf(d.borrower)) + " の貸し</h2>";
    const loans = d.g.loans.slice().sort((a, b) => {
      const aOpen = a.paid < a.total ? 0 : 1;
      const bOpen = b.paid < b.total ? 0 : 1;
      if (aOpen !== bOpen) return aOpen - bOpen;
      return -cmpEntry(a.entry, b.entry);
    });
    for (const lo of loans) {
      const left = lo.total - lo.paid;
      const done = left <= 0;
      html +=
        '<div class="loan-item"><div class="loan-top">' +
        '<span class="loan-date">' + jpDateFull(lo.entry.date) + " に貸した</span>" +
        '<span class="loan-amt">' + yen(lo.total) + "</span></div>" +
        (lo.entry.note ? '<div class="loan-note">' + esc(lo.entry.note) + "</div>" : "") +
        '<div class="bar"><span style="width:' + Math.min(100, Math.round((lo.paid / lo.total) * 100)) + '%"></span></div>' +
        (done
          ? '<span class="badge done">✅ ' + jpDateFull(lo.settledDate || lo.entry.date) + " に完済</span>"
          : '<span class="badge open">残り ' + yen(left) + "</span>") +
        (lo.payments.length
          ? '<div class="pay-list">' +
            lo.payments.map((p) => "・" + jpDate(p.entry.date) + " に " + yen(p.amount) + " 返済").join("<br>") +
            "</div>"
          : "");
      html += "</div>";
    }
    if (d.g.advance > 0) {
      html += '<p class="note-text">※ ' + esc(nameOf(d.borrower)) + " が " + yen(d.g.advance) +
        " 多めに返しています（次の貸しに自動であてられます）</p>";
    }
    html += "</div>";
  }

  openSheet(nameOf(creditorId) + " と " + nameOf(debtorId), html, (root) => {
    const btn = $("#settleBtn", root);
    if (!btn) return;
    btn.addEventListener("click", () => {
      closeSheet();
      addKind = "repay";
      updateKindLabels();
      $("#fromSel").value = debtorId;
      $("#toSel").value = creditorId;
      $("#amountInput").value = String(amount);
      $("#dateInput").value = todayStr();
      $("#noteInput").value = "";
      updatePreview();
      showPage("add");
      toast("内容を確認して記録してください");
    });
  });
}

/* --- 記録の修正・削除 --- */
function openEntrySheet(id) {
  const e = data.entries.find((x) => x.id === id);
  if (!e) return toast("その記録は見つかりません", true);

  const opts = (selected) =>
    data.members.map((m) => '<option value="' + esc(m.id) + '"' + (m.id === selected ? " selected" : "") + ">" + esc(m.name) + "</option>").join("");

  const html =
    '<div class="seg" id="editKind">' +
    '<button type="button" data-kind="loan" aria-pressed="' + (e.kind === "loan") + '"><span class="big">💸</span>貸した</button>' +
    '<button type="button" data-kind="repay" aria-pressed="' + (e.kind === "repay") + '"><span class="big">🙏</span>返した</button>' +
    "</div>" +
    '<div class="who-grid">' +
    '<div class="field" style="margin-bottom:0"><label id="editFromLabel"></label><select id="editFrom">' + opts(e.from) + "</select></div>" +
    '<div class="arrow">→</div>' +
    '<div class="field" style="margin-bottom:0"><label id="editToLabel"></label><select id="editTo">' + opts(e.to) + "</select></div>" +
    "</div>" +
    '<div class="field" style="margin-top:12px"><label>金額（円）</label><input type="number" id="editAmount" inputmode="numeric" min="1" step="1" value="' + e.amount + '"></div>' +
    '<div class="field"><label>日付</label><input type="date" id="editDate" value="' + esc(e.date) + '"></div>' +
    '<div class="field"><label>メモ</label><input type="text" id="editNote" maxlength="200" value="' + esc(e.note || "") + '"></div>' +
    '<div class="btn-row"><button type="button" class="btn danger" id="editDelete">🗑️ 消す</button>' +
    '<button type="button" class="btn primary" id="editSave">直す</button></div>';

  openSheet("記録を直す", html, (root) => {
    let kind = e.kind;
    const labels = () => {
      $("#editFromLabel", root).textContent = kind === "loan" ? "貸した人" : "返した人";
      $("#editToLabel", root).textContent = kind === "loan" ? "借りた人" : "受け取る人";
      $$("#editKind button", root).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.kind === kind)));
    };
    labels();
    $$("#editKind button", root).forEach((b) =>
      b.addEventListener("click", () => {
        kind = b.dataset.kind;
        labels();
      })
    );

    $("#editSave", root).addEventListener("click", async () => {
      const patch = {
        kind,
        from: $("#editFrom", root).value,
        to: $("#editTo", root).value,
        amount: Math.round(Number($("#editAmount", root).value)),
        date: $("#editDate", root).value,
        note: $("#editNote", root).value.trim(),
      };
      if (patch.from === patch.to) return toast("ちがう人どうしを選んでください", true);
      if (!patch.amount || patch.amount <= 0) return toast("金額を入れてください", true);
      if (!patch.date) return toast("日付を入れてください", true);
      try {
        await store.updateEntry(id, patch);
        closeSheet();
        renderAll();
        toast("直しました");
      } catch (err) {
        if (err.offline) goOffline();
        toast(err.message, true);
      }
    });

    $("#editDelete", root).addEventListener("click", async () => {
      if (!confirm("この記録を消します。よろしいですか？")) return;
      try {
        await store.deleteEntry(id);
        closeSheet();
        renderAll();
        toast("消しました");
      } catch (err) {
        if (err.offline) goOffline();
        toast(err.message, true);
      }
    });
  });
}

/* ============================================================
   書き出し
   ============================================================ */

function download(filename, text, type) {
  const blob = new Blob([text], { type: type || "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvOf(entries) {
  const cell = (v) => '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"';
  const rows = [["日付", "種類", "お金を出した人", "受け取った人", "金額", "メモ"]];
  for (const e of entries.slice().sort(cmpEntry)) {
    rows.push([e.date, e.kind === "loan" ? "貸した" : "返した", nameOf(e.from), nameOf(e.to), e.amount, e.note || ""]);
  }
  // Excelでそのまま開けるように BOM をつける
  return "﻿" + rows.map((r) => r.map(cell).join(",")).join("\r\n");
}

function visibleEntries() {
  const fm = $("#filterMember").value;
  const fk = $("#filterKind").value;
  const mo = $("#filterMonth").value;
  return data.entries
    .filter((e) => (fm === "all" ? true : e.from === fm || e.to === fm))
    .filter((e) => (fk === "all" ? true : e.kind === fk))
    .filter((e) => (mo === "all" ? true : e.date.startsWith(mo)));
}

/* ============================================================
   ページの切り替え・イベント
   ============================================================ */

function showPage(name) {
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + name));
  $$("nav button").forEach((b) => b.classList.toggle("active", b.dataset.page === name));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setConnState() {
  const el = $("#connState");
  const note = $("#offlineNote");
  if (online) {
    el.textContent = "家族みんなで共有中";
    el.classList.remove("offline");
    note.hidden = true;
    $("#modeText").textContent = "家族のパソコンに記録をためています。同じWi-Fiにつないだ家族みんなで、同じ内容が見られます。";
    $("#shareUrl").textContent = location.origin + "/";
  } else {
    el.textContent = "⚠️ つながっていません（いまは見るだけ）";
    el.classList.add("offline");
    note.hidden = false;
    $("#modeText").textContent =
      "家族のパソコンにつながっていません。記録するには、パソコンでサーバーを起動してください。つながると自動でもどります。";
    $("#shareUrl").textContent = location.origin + "/";
  }
  updateSaveAvailability();
}

/* つながっていないあいだは、記録・修正のボタンを押せなくする */
function updateSaveAvailability() {
  $("#saveBtn").disabled = !online || !data.members.length;
  $("#addMemberBtn").disabled = !online;
  $("#newMemberName").disabled = !online;
  $$("#memberList .icon-btn").forEach((b) => (b.disabled = !online));
  $("#saveBtn").textContent = online ? "この内容で記録する" : "つながるまで記録できません";
}

function goOffline() {
  if (!online) return;
  online = false;
  setConnState();
}
function goOnline() {
  if (online) return;
  online = true;
  setConnState();
  toast("家族のパソコンにつながりました");
}

function bindEvents() {
  $$("nav button").forEach((b) => b.addEventListener("click", () => showPage(b.dataset.page)));

  $$("#kindSeg button").forEach((b) =>
    b.addEventListener("click", () => {
      addKind = b.dataset.kind;
      updateKindLabels();
      updatePreview();
    })
  );

  $("#swapBtn").addEventListener("click", () => {
    const f = $("#fromSel").value;
    $("#fromSel").value = $("#toSel").value;
    $("#toSel").value = f;
    updatePreview();
  });

  ["#fromSel", "#toSel", "#amountInput", "#dateInput"].forEach((s) =>
    $(s).addEventListener("input", updatePreview)
  );

  $$(".quick-amounts button").forEach((b) =>
    b.addEventListener("click", () => {
      const input = $("#amountInput");
      if (b.dataset.clear) input.value = "";
      else input.value = String((Number(input.value) || 0) + Number(b.dataset.add));
      updatePreview();
    })
  );

  $("#saveBtn").addEventListener("click", saveEntry);

  $("#pairList").addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-pair]");
    if (!btn) return;
    const [creditor, debtor] = btn.dataset.pair.split("::");
    openPairSheet(creditor, debtor);
  });

  $("#historyList").addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-entry]");
    if (btn) openEntrySheet(btn.dataset.entry);
  });

  ["#filterMember", "#filterKind", "#filterMonth"].forEach((s) =>
    $(s).addEventListener("change", renderHistory)
  );

  $("#csvBtn").addEventListener("click", () => {
    const list = visibleEntries();
    if (!list.length) return toast("保存する記録がありません", true);
    download("kashikari-" + todayStr() + ".csv", csvOf(list), "text/csv;charset=utf-8");
    toast("CSVを保存しました");
  });

  $("#exportAllCsvBtn").addEventListener("click", () => {
    if (!data.entries.length) return toast("記録がありません", true);
    download("kashikari-all-" + todayStr() + ".csv", csvOf(data.entries), "text/csv;charset=utf-8");
    toast("CSVを保存しました");
  });

  $("#exportJsonBtn").addEventListener("click", () => {
    download("kashikari-backup-" + todayStr() + ".json", JSON.stringify(data, null, 2), "application/json");
    toast("バックアップを保存しました");
  });

  $("#addMemberBtn").addEventListener("click", addMemberFromInput);
  $("#newMemberName").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") addMemberFromInput();
  });

  $("#memberList").addEventListener("click", async (ev) => {
    const ren = ev.target.closest("[data-rename]");
    const del = ev.target.closest("[data-delmember]");
    try {
      if (ren) {
        const m = data.members.find((x) => x.id === ren.dataset.rename);
        const name = prompt("新しい名前", m ? m.name : "");
        if (name === null) return;
        const trimmed = name.trim();
        if (!trimmed) return toast("名前を入れてください", true);
        await store.renameMember(ren.dataset.rename, trimmed);
        lastMemberSig = "";
        renderAll();
        toast("名前を直しました");
      } else if (del) {
        const m = data.members.find((x) => x.id === del.dataset.delmember);
        if (!m) return;
        if (!confirm("「" + m.name + "」を消します。よろしいですか？")) return;
        await store.deleteMember(del.dataset.delmember);
        lastMemberSig = "";
        renderAll();
        toast("消しました");
      }
    } catch (e) {
      if (e.offline) goOffline();
      toast(e.message, true);
    }
  });

  $("#retryBtn").addEventListener("click", async () => {
    toast("つなぎなおしています…");
    await syncNow();
    if (!online) toast("まだつながりません。パソコンが起動しているか確かめてください", true);
  });

  $("#sheetClose").addEventListener("click", closeSheet);
  $("#sheetBg").addEventListener("click", (ev) => {
    if (ev.target === $("#sheetBg")) closeSheet();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closeSheet();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") syncNow();
  });
}

async function addMemberFromInput() {
  const input = $("#newMemberName");
  const name = input.value.trim();
  if (!name) return toast("名前を入れてください", true);
  // 送信中に次の名前を打たれても消さないよう、先に空にしておく
  input.value = "";
  try {
    await store.addMember(name);
    lastMemberSig = "";
    renderAll();
    toast("「" + name + "」を追加しました");
  } catch (e) {
    if (!input.value) input.value = name; // 失敗したら書きもどす
    if (e.offline) goOffline();
    toast(e.message, true);
  }
}

/* ============================================================
   ほかの端末の更新を取りこむ
   ============================================================ */

let syncing = false;
async function syncNow() {
  if (syncing) return;
  if ($("#sheetBg").classList.contains("show")) return; // シートを開いている間は動かさない
  syncing = true;
  try {
    const changed = await store.refresh();
    if (changed) renderAll();
    goOnline();
  } catch (_) {
    goOffline();
  } finally {
    syncing = false;
  }
}

/* ============================================================
   スタート
   ============================================================ */

async function start() {
  $("#dateInput").value = todayStr();
  bindEvents();
  updateKindLabels();

  try {
    setData(await api("GET", "/api/state"));
    online = true;
  } catch (_) {
    online = false;
  }

  setConnState();
  renderAll();

  // 5秒ごとに、ほかの端末の更新を取りこむ（切れているときは再接続もかねる）
  setInterval(() => {
    if (document.visibilityState === "visible") syncNow();
  }, 5000);
}

start();

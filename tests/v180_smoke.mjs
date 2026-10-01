// v1.8.0 の動作確認: 請求書・見積書の発行元(ロゴの大きさ・住所・TEL・登録番号)と
// 振込先の支店名、A4 1枚に収まるかを実ブラウザで確かめる。
// あわせて v1.7.5〜v1.7.9 で入れたものを見る:
//   受託品をレジのピッカーに出す / レジ入出金の取消 / DM宛名の印刷順とCSV /
//   売上伝票明細CSVの下代 / 在庫品の商品情報の修正
//
//   python3 server/app.py 8760 &            # 機器は不要(OFFで可)
//   node tests/v180_smoke.mjs
//
// ★実ブラウザで動かす確認(動作確認モード用)。蓄積モードでは実行しない。
//   管理者ユーザー admin のパスワードをテスト用に設定するので、★本番機では実行しないこと。
//   画面の写真は logs/shots/ に残る(.gitignore 済み)。
import fs from "fs";
const _pw = await import(
  process.env.PLAYWRIGHT_PKG || "/opt/node22/lib/node_modules/playwright/index.js");
const chromium = (_pw.default || _pw).chromium;

const BASE = "http://127.0.0.1:8760";
const SHOT = "logs/shots";
fs.mkdirSync(SHOT, { recursive: true });
const results = [];
const check = (name, ok, detail = "") => {
  results.push([name, !!ok, detail]);
  console.log((ok ? "  OK  " : "★NG  ") + name + (detail ? "   … " + detail : ""));
};
const MM = 96 / 25.4;   // 1mm が何px か(ブラウザの既定 96dpi)

const br = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" });
const pg = await br.newPage({ viewport: { width: 1280, height: 890 } });
const errors = [];
pg.on("pageerror", (e) => errors.push(String(e)));

await pg.goto(BASE, { waitUntil: "networkidle" });
if (await pg.$("#uid")) {
  await pg.selectOption("#uid", "admin");
  await pg.fill("#pw", "tokiwa-test-1234");
  await pg.click("#btn");
}
await pg.waitForSelector("#app.active", { timeout: 20000 });
await pg.waitForTimeout(1200);
check("バージョン表示が v1.8.0", (await pg.innerText("#app-ver")).trim() === "v1.8.0",
  (await pg.innerText("#app-ver")).trim());

// ══ 請求書(今回の本題)═══════════════════════════════════════
await pg.click('.nav-item[data-screen="estimate"]');
await pg.waitForTimeout(600);
await pg.click("#est-tab-invoice");
await pg.waitForTimeout(300);
await pg.fill("#est-to", "確認用 株式会社");
await pg.selectOption("#est-keisho", "御中");
// 品目を2つ入れる(明細があっても1枚に収まるかを見るため)
for (const [nm, amt] of [["ダイヤリング 修理", "33000"], ["メガネレンズ 交換", "18700"]]) {
  await pg.fill("#est-name-in", nm);
  await pg.fill("#est-amt-in", amt);
  await pg.click('section[data-screen="estimate"] button:has-text("追加")');
  await pg.waitForTimeout(250);
}
await pg.click("#est-print-btn");
await pg.waitForTimeout(1200);

const sheet = ".doc-sheet";
await pg.waitForSelector(sheet, { timeout: 8000 });
const doc = await pg.evaluate(() => {
  const s = document.querySelector(".doc-sheet");
  const img = s.querySelector(".doc-store img");
  const addr = Array.from(s.querySelectorAll(".doc-store .doc-addr")).map((e) => e.textContent.trim());
  const bank = Array.from(s.querySelectorAll(".doc-bank .bk-line")).map((e) => e.textContent.trim());
  const r = s.getBoundingClientRect();
  const headRect = s.querySelector(".doc-head").getBoundingClientRect();
  const toRect = s.querySelector(".doc-to").getBoundingClientRect();
  return {
    text: s.innerText.replace(/\s+/g, " "),
    logo: img ? { w: img.getBoundingClientRect().width, h: img.getBoundingClientRect().height,
                  nat: img.naturalWidth + "x" + img.naturalHeight, src: img.getAttribute("src") } : null,
    addr, bank, sheetH: r.height, sheetW: r.width,
    headBottom: headRect.bottom - r.top, toTop: toRect.top - r.top,
    reg: (s.querySelector(".doc-reg") || {}).textContent || "",
  };
});

// ① ロゴ: 24mm の指定どおりに出ているか(正方形なので幅も24mm)
const logoMm = doc.logo ? doc.logo.h / MM : 0;
check("請求書: ロゴが出ている", !!doc.logo, doc.logo ? doc.logo.src + " 実寸 " + doc.logo.nat : "(無し)");
check("請求書: ロゴの高さが約24mm", Math.abs(logoMm - 24) < 1.0, logoMm.toFixed(1) + "mm");
check("請求書: ロゴが潰れていない(正方形のまま)",
  doc.logo && Math.abs(doc.logo.w - doc.logo.h) < 2,
  doc.logo ? doc.logo.w.toFixed(0) + "x" + doc.logo.h.toFixed(0) + "px" : "");
check("請求書: ロゴが前より大きい(20mm→24mm)", logoMm > 20.5, logoMm.toFixed(1) + "mm");

// ② 住所・TEL・登録番号
check("請求書: 住所が入っている（〒つき）",
  doc.addr.some((a) => a.includes("〒") && a.includes("豊田市")), doc.addr.join(" / "));
check("請求書: 電話番号が入っている",
  doc.addr.some((a) => a.includes("TEL") && a.includes("0565-32-0688")), doc.addr.join(" / "));
check("請求書: 登録番号(インボイス)が入っている",
  doc.reg.includes("T1810816014712"), doc.reg.trim());

// ③ 振込先に支店名
check("請求書: 振込先に「本店営業部」が入っている",
  doc.bank.some((b) => b.includes("本店営業部")), doc.bank.join(" / "));
check("請求書: 振込先の店番・口座番号・名義がそのまま残っている",
  doc.bank.some((b) => b.includes("店番 011") && b.includes("9264690")) &&
  doc.bank.some((b) => b.includes("名義")), doc.bank.join(" / "));

// ④ A4 1枚に収まるか(297mm)。宛名がヘッダに重なっていないか
check("請求書: A4縦1枚に収まる(297mm以内)", doc.sheetH <= 297 * MM + 2,
  (doc.sheetH / MM).toFixed(1) + "mm / 297mm");
check("請求書: 用紙幅がA4(210mm)", Math.abs(doc.sheetW / MM - 210) < 2, (doc.sheetW / MM).toFixed(1) + "mm");
check("請求書: 宛名が発行元の下に来ている(重なっていない)", doc.toTop >= doc.headBottom - 1,
  "宛名 " + (doc.toTop / MM).toFixed(0) + "mm / 発行元の下端 " + (doc.headBottom / MM).toFixed(0) + "mm");
check("請求書: 「御 請 求 書」と宛名の敬称(御中)が出る",
  doc.text.includes("御 請 求 書") && doc.text.includes("確認用 株式会社 御中"), doc.text.slice(0, 60));
await pg.screenshot({ path: SHOT + "/v180_invoice.png", fullPage: true });

// 見積書でも発行元が出て、振込先は出ない(請求書だけ)
await pg.evaluate(() => cancelPrint());
await pg.waitForTimeout(400);
const estOk = await pg.evaluate(() => {
  setEstMode("quote");
  estDoc();
  const s = document.querySelector(".doc-sheet");
  return { addr: s.querySelectorAll(".doc-store .doc-addr").length,
           bank: s.querySelectorAll(".doc-bank").length,
           title: (s.querySelector(".doc-title") || {}).textContent || "" };
});
check("見積書: 発行元の住所・TELも出る", estOk.addr >= 2, "行数 " + estOk.addr);
check("見積書: 振込先は出ない(請求書だけ)", estOk.bank === 0, "枠 " + estOk.bank + "個");
check("見積書: 題字が「御 見 積 書」", estOk.title.includes("御 見 積 書"), estOk.title);
await pg.evaluate(() => cancelPrint());
await pg.waitForTimeout(400);

// ══ v1.7.5 受託品をレジのピッカーに出す ════════════════════
await pg.click('.nav-item[data-screen="register"]');
await pg.waitForTimeout(700);
await pg.click('section[data-screen="register"] button:has-text("商品番号で追加")');
await pg.waitForSelector("#prod-modal.show", { timeout: 8000 });
await pg.waitForTimeout(800);
check("レジ: ピッカーに「受託品も出す」がある", !!(await pg.$("#pm-consign")));
check("レジ: 既定は在庫だけ(チェックOFF)", (await pg.isChecked("#pm-consign")) === false);
const states1 = await pg.evaluate(() => pmResults.map((p) => p[4]));
check("レジ: 既定では受託が出ない", !states1.includes("受託"),
  "状態 " + Array.from(new Set(states1)).join("/") + " (" + states1.length + "件)");
await pg.check("#pm-consign");
await pg.waitForTimeout(900);
check("レジ: ONにすると見出しが変わる",
  (await pg.innerText("#pm-title")).includes("受託品"), await pg.innerText("#pm-title"));
check("レジ: ONの時は注意書きが出る",
  (await pg.innerText("#pm-note")).includes("受託品"), (await pg.innerText("#pm-note")).slice(0, 40));
await pg.uncheck("#pm-consign");
await pg.waitForTimeout(500);
await pg.click("#prod-modal .modal-foot .btn");
await pg.waitForTimeout(300);

// ══ v1.7.6 DM宛名の印刷順 ═══════════════════════════════════
const lbl = await pg.evaluate(() => {
  const ids = D.customers.slice(0, 40).map((c) => String(c[0]));
  openLabelPrint(ids);
  const has = !!document.getElementById("label-sort");
  const opts = Array.from(document.querySelectorAll("#label-sort option")).map((o) => o.value);
  return { has, opts, n: labelCustomers.length,
           csv: !!document.getElementById("label-csv-file"),
           b2: document.querySelector('#label-modal .modal-foot').innerText.includes("クロネコB2") };
});
check("DM宛名: 「印刷順」がある", lbl.has && lbl.opts.join(",") === "screen,kana,staff,zip", lbl.opts.join(","));
check("DM宛名: CSVの読み込み口がある", lbl.csv);
check("DM宛名: この並びでクロネコB2のボタンがある", lbl.b2);
if (lbl.n > 2) {
  const sorted = await pg.evaluate(() => {
    const kanaOf = () => labelCustomers.map((c) => String(c[2] || ""));
    document.getElementById("label-sort").value = "kana"; applyLabelSort();
    const kana = kanaOf();
    document.getElementById("label-sort").value = "zip"; applyLabelSort();
    const zip = labelCustomers.map((c) => String(c[14] || ""));
    document.getElementById("label-sort").value = "screen"; applyLabelSort();
    return { kana, zip, n: labelCustomers.length };
  });
  const asc = (a) => { const v = a.filter((x) => x); return v.every((x, i) => i === 0 || v[i - 1] <= x); };
  const blanksFirst = (a) => { const i = a.findIndex((x) => x); return a.slice(0, i).every((x) => !x); };
  check("DM宛名: カナ順に並ぶ", asc(sorted.kana), sorted.kana.slice(0, 5).join(" ") + " …");
  check("DM宛名: 空欄が先頭にまとまる(カナ)", blanksFirst(sorted.kana));
  check("DM宛名: 郵便番号順に並ぶ", asc(sorted.zip), sorted.zip.slice(0, 5).join(" ") + " …");
}
await pg.evaluate(() => closeLabelPrint());
await pg.waitForTimeout(300);

// ══ v1.7.7 売上伝票明細CSVの下代 / v1.7.4 以前の画面が壊れていないか ══
const slip = await pg.evaluate(async () => {
  const r = await fetch(window.TOKIWA_API + "/slip_lines?from=2000-01-01&to=2099-12-31");
  const j = await r.json();
  const ln = (j.lines || [])[0] || null;
  return { n: (j.lines || []).length, hasCost: ln ? Object.prototype.hasOwnProperty.call(ln, "cost") : false,
           sample: ln };
});
check("売上伝票明細: サーバーが下代(cost)を返す", slip.hasCost,
  slip.n + "件 / " + JSON.stringify(slip.sample || {}).slice(0, 90));

// ══ v1.7.3 レジ入出金の取消 ═════════════════════════════════
await pg.click('.nav-item[data-screen="reports"]');
await pg.waitForTimeout(700);
const cashVoid = await pg.evaluate(async () => {
  const today = TODAY_ISO;
  const r = await fetch(window.TOKIWA_API + "/cash_movement", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category: "両替", amount: -50000, note: "確認用", occurred_at: today }),
  });
  const added = await r.json();
  (D.cashMovements = D.cashMovements || []).unshift(added);
  document.getElementById("rep-date").value = today;
  renderDailyReport();
  await new Promise((s) => setTimeout(s, 900));
  const before = document.getElementById("rep-daily-tbody").innerText;
  return { id: added.id, hasBtn: before.includes("取消"), today };
});
check("日報: レジ入出金の行に「取消」ボタンが出る", cashVoid.hasBtn);
const voided = await pg.evaluate(async (id) => {
  openCashVoid(id);
  document.getElementById("cv-reason").value = "動作確認（金額の入力間違い）";
  submitCashVoid(document.getElementById("cv-submit-btn"));
  await new Promise((s) => setTimeout(s, 1500));
  const list = D.cashMovements || [];
  const orig = list.filter((m) => String(m.id) === String(id))[0];
  const rev = list.filter((m) => String(m.void_of) === String(id))[0];
  const txt = document.getElementById("rep-daily-tbody").innerText;
  return { origVoided: !!(orig && orig.voided_by_id), revAmount: rev ? rev.amount : null,
           revDate: rev ? rev.occurred_at : null, mark: txt.includes("取消済み") && txt.includes("取消の記録") };
}, cashVoid.id);
check("日報: 打ち消しの記録が金額を逆にして入る", voided.revAmount === 50000, "¥" + voided.revAmount);
check("日報: 打ち消しの日付が元の記録と同じ日", voided.revDate === cashVoid.today,
  voided.revDate + " / " + cashVoid.today);
check("日報: 元の記録に取消済みの印が付く", voided.origVoided && voided.mark);
check("日報: 同じ記録は二度取り消せない", await pg.evaluate(async (id) => {
  const r = await fetch(window.TOKIWA_API + "/cash_movement_void", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: id, reason: "二度目" }),
  });
  return (await r.json()).error ? true : false;
}, cashVoid.id));

check("画面のJavaScriptエラーが無い", errors.length === 0, errors.slice(0, 2).join(" / "));
await br.close();

const ng = results.filter((r) => !r[1]);
console.log("\n=== 結果: " + (results.length - ng.length) + "/" + results.length + " OK ===");
if (ng.length) { console.log("★NGあり:"); ng.forEach((r) => console.log("  - " + r[0] + (r[2] ? "  … " + r[2] : ""))); }
process.exit(ng.length ? 1 : 0);

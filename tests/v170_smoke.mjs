// v1.7.0 の動作確認: 組み直したレジ(会計が通るか・1画面に収まるか)、売掛のまとめて入金、
// Enterで次の欄へ、処方箋の用途の追加 を実ブラウザで確かめる。
//
//   python3 server/app.py 8760 kiki &      # 機器モードONで起動しておく
//   RCV_CUST=13 node tests/v170_smoke.mjs
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

// ★本番機と同じ大きさで開く(1280×1024 からブラウザの枠とタスクバーを引いた実寸)
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
await pg.waitForTimeout(1500);
check("バージョン表示が v1.7.0", (await pg.innerText("#app-ver")).trim() === "v1.7.0",
  (await pg.innerText("#app-ver")).trim());

// ══ レジ ══════════════════════════════════════════════════
await pg.click('.nav-item[data-screen="register"]');
await pg.waitForTimeout(900);

check("レジ: テンキーが無い", !(await pg.$(".tenkey")));
// ★[data-screen="register"] は**左メニューのボタンにも当たる**ので section に限定する
const posText = await pg.innerText('section[data-screen="register"]');
// ★今のレジの項目が1つも減っていないこと(減ってよいのはテンキーだけ)
[["会計担当", "会計担当"], ["過去の日付", "過去の日付で登録する"], ["受託品", "受託品"],
 ["レジ入出金", "レジ入出金"], ["明細クリア", "明細クリア"], ["ポイント付与", "ポイント付与"],
 ["加算予定", "加算予定"], ["共通メッセージ", "全レシート共通のメッセージを編集"],
 ["内訳合計", "内訳合計"]]
  .forEach(([label, needle]) => check("レジ: 「" + label + "」が残っている", posText.includes(needle)));

// 顧客と明細を入れて「実際に使う状態」にしてから、はみ出しを見る
const cust = await pg.evaluate(() => {
  const b = document.querySelector("#pos-operator-bar .op-btn"); if (b) b.click();
  const c = D.customers.find((x) => x[1]);
  posCustomer = c; renderPosCustomer(); renderPosReceivable();
  return { id: String(c[0]), name: c[1] };
});
await pg.waitForTimeout(400);
// 「番号なしで追加」は品名の見本を押す形(電池交換など)。押すと明細に1行入る
await pg.click('section[data-screen="register"] button:has-text("番号なしで追加")');
await pg.waitForSelector("#free-modal.show", { timeout: 8000 });
await pg.click('#free-modal .free-grid button:has-text("電池交換")');
await pg.waitForTimeout(700);
check("レジ: 明細を1行足せた", await pg.evaluate(
  () => posLines.length === 1 && String(posLines[0].free_name || posLines[0].name || "").includes("電池交換")),
  await pg.evaluate(() => JSON.stringify(posLines[0] || null).slice(0, 70)));

// ★お預かり・釣銭は「現金の支払行に金額が入った時だけ出る」作り(元からそう)。
//   金額を入れると出ることを確かめる
await pg.evaluate(() => { payRows = [{ method: "現金", amount: 1320 }]; renderPayRows(); });
await pg.waitForTimeout(300);
check("レジ: 「お預かり・釣銭」が現金の時に出る", await pg.evaluate(() => {
  const w = document.getElementById("pos-cash-wrap");
  return !!w && w.offsetHeight > 0 && !!document.getElementById("deposit") && !!document.getElementById("change");
}));

const fit = await pg.evaluate(() => ({
  doc: document.documentElement.scrollHeight, win: window.innerHeight,
  btn: document.getElementById("btn-checkout").getBoundingClientRect().bottom,
}));
check("レジ: 縦スクロールが出ない(1280×890)", fit.doc <= fit.win + 2, fit.doc + " / " + fit.win);
check("レジ: 会計を確定が画面の中にある", fit.btn <= fit.win, Math.round(fit.btn) + " / " + fit.win);
await pg.screenshot({ path: SHOT + "/v170_pos.png" });

// ── Enterで次の欄へ / 会計を確定はEnterで押されない ──
await pg.focus("#deposit");
await pg.keyboard.press("Enter");
await pg.waitForTimeout(250);
const movedTo = await pg.evaluate(() => (document.activeElement || {}).id || "");
check("Enter: 次の欄(または会計を確定)へ移る", movedTo !== "deposit", "移動先 " + (movedTo || "(なし)"));
const before = await pg.evaluate(() => (D.sales[posCustomer[0]] || []).length);
await pg.focus("#btn-checkout");
await pg.keyboard.press("Enter");
await pg.waitForTimeout(900);
check("Enter: 「会計を確定」はEnterで押されない",
  (await pg.evaluate(() => (D.sales[posCustomer[0]] || []).length)) === before);

// ── 実際に会計を通す ──
await pg.evaluate(() => { document.getElementById("deposit").value = "2000"; refreshChange(); });
await pg.click("#btn-checkout");
await pg.waitForTimeout(2500);
const done = await pg.evaluate(() => ({ toast: (document.getElementById("toast") || {}).textContent || "",
  lines: posLines.length }));
check("レジ: 会計が通り、明細が空に戻る", done.lines === 0, done.toast.replace(/\s+/g, " ").slice(0, 90));

// ══ 売掛のまとめて入金 ═══════════════════════════════════════
const rcv = process.env.RCV_CUST;
if (rcv) {
  await pg.evaluate((cid) => openCustomer(cid, { tab: "c-pay" }), rcv);
  await pg.waitForTimeout(1300);
  const payText = await pg.innerText("#c-pay");
  check("売掛: 入金のしかたを選べる", payText.includes("入金のしかた") && payText.includes("まとめて入金"));
  await pg.click('#c-pay button:has-text("まとめて入金")');
  await pg.waitForSelector("#bulkpay-modal.show", { timeout: 8000 });
  const total = await pg.evaluate(() => bpTarget.total);
  const first = await pg.evaluate(() => bpTarget.rows[0].bal);
  const nRows = await pg.evaluate(() => bpTarget.rows.length);
  // ★1件目を完済して次へ少し繰り越す金額。**合計残高は超えないように**する
  //   (超えると確認のポップアップが出て、この場面の確認にならない)
  const amount = Math.max(1, Math.min(first + 1000, total - 1));
  console.log("   (売掛 " + nRows + "件 / 合計 ¥" + total.toLocaleString() +
    " / 1件目 ¥" + first.toLocaleString() + " → 入金 ¥" + amount.toLocaleString() + ")");
  await pg.fill("#bp-amount", String(amount));
  await pg.waitForTimeout(400);
  const calc = await pg.evaluate(() => ({
    before: document.getElementById("bp-before").textContent,
    pay: document.getElementById("bp-pay").textContent,
    after: document.getElementById("bp-after").textContent,
    alloc: document.getElementById("bp-alloc").innerText.replace(/\s+/g, " ").trim(),
  }));
  check("売掛: 残高 − 入金 = 入金後の残高 が出る",
    calc.before.includes(total.toLocaleString()) && calc.after.length > 1,
    calc.before + " " + calc.pay + " → " + calc.after);
  check("売掛: 充当の内訳が出る(古い順・完済が分かる)",
    calc.alloc.includes("完済") || nRows === 1, calc.alloc.slice(0, 80));
  await pg.screenshot({ path: SHOT + "/v170_bulkpay.png" });
  await pg.click("#bp-ok");
  await pg.waitForTimeout(3200);   // 画面が残高を読み直すのを待つ
  const after = await pg.evaluate((cid) => (D.urikake[cid] || [])
    .reduce((t, u) => t + (parseInt(u[4], 10) || 0), 0), rcv);
  check("売掛: 入金すると残高が減る", after === total - amount,
    "¥" + total.toLocaleString() + " → ¥" + after.toLocaleString());

  // 超える入金はポップアップで止まる
  await pg.click('#c-pay button:has-text("まとめて入金")');
  await pg.waitForSelector("#bulkpay-modal.show", { timeout: 8000 });
  await pg.fill("#bp-amount", String(after + 5000));
  await pg.waitForTimeout(300);
  await pg.click("#bp-ok");
  await pg.waitForTimeout(600);
  const warned = await pg.isVisible("#alert-modal.show");
  check("売掛: 残高を超える時はポップアップで止まる", warned,
    warned ? (await pg.innerText("#al-msg")).replace(/\s+/g, " ").slice(0, 70) : "(出なかった)");
  if (warned) await pg.click("#al-cancel");
  await pg.waitForTimeout(300);
  await pg.click('#bulkpay-modal .modal-foot .btn:not(.btn-primary)');
} else {
  check("売掛: 見本の顧客が指定されておらず確認できず", false, "RCV_CUST を渡してください");
}

// ══ 処方箋の用途 ═══════════════════════════════════════════
const purposes = await pg.evaluate(() =>
  Array.from(document.querySelectorAll("#rx-purpose option")).map((o) => o.textContent.trim()));
["フレームのみ", "サングラス", "その他"].forEach((v) =>
  check("処方箋の用途に「" + v + "」がある", purposes.includes(v), purposes.join("/")));

check("画面のJavaScriptエラーが無い", errors.length === 0, errors.slice(0, 2).join(" / "));
await br.close();

const ng = results.filter((r) => !r[1]);
console.log("\n=== 結果: " + (results.length - ng.length) + "/" + results.length + " OK ===");
if (ng.length) { console.log("★NGあり:"); ng.forEach((r) => console.log("  - " + r[0] + (r[2] ? "  … " + r[2] : ""))); }
process.exit(ng.length ? 1 : 0);

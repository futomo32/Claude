// v1.6.0 の動作確認: クリアボタン(8か所)・表の並べ替え(共通の仕組み)・処方箋のメモ・
// 番号を紐づけ・顧客IDの番号検索・機器はレジPCのみ、を実ブラウザで確かめる。
//
//   python3 server/app.py 8760 kiki &      # 機器モードONで起動しておく
//   node tests/v160_smoke.mjs
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
const val = (pg, id) => pg.$eval("#" + id, (e) => (e.type === "checkbox" ? String(e.checked) : e.value));

const br = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" });
const pg = await br.newPage({ viewport: { width: 1500, height: 1000 } });
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
check("バージョン表示が v1.6.0", (await pg.innerText("#app-ver")).trim() === "v1.6.0",
  (await pg.innerText("#app-ver")).trim());

// ── 1. 顧客管理のクリア(店舗は「01 本店」に戻る) ──
await pg.click('.nav-item[data-screen="customers"]');
await pg.waitForTimeout(800);
await pg.fill("#q-name", "ア");
await pg.selectOption("#q-cust-store", "");      // 全店にしてみる
await pg.selectOption("#q-cust-lastbuy", "3");
await pg.waitForTimeout(400);
await pg.click('[data-screen="customers"] button:has-text("クリア")');
await pg.waitForTimeout(500);
check("顧客管理: 条件が空になる", (await val(pg, "q-name")) === "" && (await val(pg, "q-cust-lastbuy")) === "");
check("顧客管理: 店舗が「01」に戻る(空にしない)", (await val(pg, "q-cust-store")) === "01",
  await val(pg, "q-cust-store"));

// ── 2. 顧客IDを「番号だけ」で引ける ──
const someId = await pg.evaluate(() => (D.customers[0] || [])[0]);
// サンプルDBの顧客IDにはハイフンが無い(実データは 01-4269 形式)
const idNum = String(someId).includes("-") ? String(someId).split("-")[1] : String(someId);
await pg.fill("#q-name", idNum);
await pg.waitForTimeout(600);
check("顧客ID: 番号だけで引ける(" + idNum + ")",
  (await pg.innerText("#cust-count")).includes("該当") &&
  !(await pg.innerText("#cust-tbody")).includes("見つかりません"),
  (await pg.innerText("#cust-count")).trim());
await pg.click('[data-screen="customers"] button:has-text("クリア")');
await pg.waitForTimeout(400);

// ── 3. 商品・在庫のクリア(状態は「在庫」に戻る) ──
await pg.click('.nav-item[data-screen="products"]');
await pg.waitForTimeout(1200);
await pg.selectOption("#q-state", "");
await pg.fill("#q-prod", "あ");
await pg.waitForTimeout(500);
await pg.click('#p-stock button:has-text("クリア")');
await pg.waitForTimeout(800);
check("商品在庫: 状態が「在庫」に戻る(空にしない)", (await val(pg, "q-state")) === "在庫",
  await val(pg, "q-state"));
check("商品在庫: 検索語が空になる", (await val(pg, "q-prod")) === "");

// ── 4. 商品一覧: 自前の並べ替えを持つ見出しには触らない(共通の仕組みは空いた列だけ) ──
await pg.waitForTimeout(600);
const decor = await pg.evaluate(() => {
  const t = document.querySelector("#p-stock table.data");
  if (!t) return null;
  const own = [], auto = [];
  t.querySelectorAll("thead th").forEach((h) => {
    const label = (h.textContent || "").trim();
    if (!label) return;
    if (h.hasAttribute("onclick")) own.push(label);
    else if (h.classList.contains("ts-col")) auto.push(label);
  });
  return { own: own, auto: auto };
});
check("商品一覧: 自前の並べ替えはそのまま残る", !!decor && decor.own.length >= 3,
  decor ? decor.own.join("/") : "(表が無い)");
check("商品一覧: 空いていた見出しに自動で付く", !!decor && decor.auto.length >= 1,
  decor ? decor.auto.join("/") : "");

await pg.screenshot({ path: SHOT + "/v160_products.png" });

// ── 5. 並べ替えない表(レジの明細)には付かない ──
await pg.click('.nav-item[data-screen="register"]');
await pg.waitForTimeout(800);
check("レジの明細は並べ替えできない(data-nosort)", await pg.evaluate(() => {
  const t = document.querySelector('#pos-lines') && document.querySelector('#pos-lines').closest("table");
  return !!t && t.getAttribute("data-nosort") === "1" && !t.querySelector("th.ts-col");
}));

// ── 6. 売掛管理: 最終入金で並べ替えできる＋クリア ──
await pg.click('.nav-item[data-screen="receivables"]');
await pg.waitForTimeout(1200);
check("売掛: 最終入金が並べ替えできる",
  await pg.isVisible('th.sortable:has-text("最終入金")'));
await pg.fill("#rcv-search", "あ");
await pg.selectOption("#rcv-aging", "6");
await pg.waitForTimeout(400);
await pg.click('[data-screen="receivables"] button:has-text("クリア")');
await pg.waitForTimeout(500);
check("売掛: クリアで絞り込みが戻る",
  (await val(pg, "rcv-search")) === "" && (await val(pg, "rcv-aging")) === "");

// ── 7. 検索・分析のクリア(チェックは付け直す・結果も戻る) ──
await pg.click('.nav-item[data-screen="search"]');
await pg.waitForTimeout(1000);
await pg.uncheck("#s-exclude");
await pg.fill("#s-name", "ア");
await pg.click('#s-cust button:has-text("検索")');
await pg.waitForTimeout(800);
const hadRows = !(await pg.innerText("#s-cust-tbody")).includes("条件を指定して");

// ★ここで共通の並べ替えを確かめる。この表は**自前の並べ替えを持っていない**ので、
//   仕組みが自動で付いたかどうかがそのまま分かる(商品一覧は自前の分があるため不向き)。
await pg.waitForTimeout(600);
const sIdx = await pg.evaluate(() => {
  const rows = Array.from(document.querySelectorAll("#s-cust-tbody tr")).slice(0, 20);
  let best = -1, bestN = 1;
  document.querySelectorAll("#s-cust thead th.ts-col").forEach((h) => {
    const i = parseInt(h.getAttribute("data-ts-col"), 10);
    const v = new Set(rows.map((r) => (r.children[i] ? r.children[i].textContent.trim() : "")));
    v.delete("");
    if (v.size > bestN) { bestN = v.size; best = i; }
  });
  return best;
});
check("並べ替え: 自前を持たない表に自動で付く", sIdx >= 0, "列 " + sIdx);
if (sIdx >= 0) {
  const keys = () => pg.$$eval("#s-cust-tbody tr", (rs) => rs.map((r) => r.textContent.trim()));
  const before = await keys();
  await pg.click('#s-cust thead th[data-ts-col="' + sIdx + '"]');
  await pg.waitForTimeout(400);
  // ★「順番が変わったか」ではなく「その列が昇順に並んでいるか」で見る
  //   (もともと昇順だった列を押すと順番は変わらないが、それは正しい動き)
  const asc = await pg.evaluate((i) => {
    const vals = Array.from(document.querySelectorAll("#s-cust-tbody tr"))
      .map((r) => (r.children[i] ? r.children[i].textContent.trim() : ""))
      .filter((v) => v && v !== "—");
    for (let k = 1; k < vals.length; k++) if (vals[k - 1].localeCompare(vals[k], "ja") > 0) return false;
    return vals.length > 1;
  }, sIdx);
  check("並べ替え: 押すとその列が昇順に並ぶ", asc);
  check("並べ替え: 「並び:」の案内が出る", await pg.isVisible(".sort-note"),
    (await pg.$(".sort-note")) ? (await pg.innerText(".sort-note")).replace(/\s+/g, " ").trim() : "");
  await pg.click('#s-cust thead th[data-ts-col="' + sIdx + '"]'); await pg.waitForTimeout(300);
  await pg.click('#s-cust thead th[data-ts-col="' + sIdx + '"]'); await pg.waitForTimeout(400);
  check("並べ替え: 3回目で元の並びに戻る", JSON.stringify(await keys()) === JSON.stringify(before));
  check("並べ替え: 戻すと案内が消える", !(await pg.$(".sort-note")));
  await pg.screenshot({ path: SHOT + "/v160_sort.png" });
}
await pg.click('#s-cust button:has-text("クリア")');
await pg.waitForTimeout(500);
check("DM抽出: 検索できていた", hadRows);
check("DM抽出: クリアで条件が空", (await val(pg, "s-name")) === "");
check("DM抽出: 「ななし等を除く」が付け直る(既定)", (await val(pg, "s-exclude")) === "true",
  await val(pg, "s-exclude"));
check("DM抽出: 結果の表も案内に戻る",
  (await pg.innerText("#s-cust-tbody")).includes("条件を指定して"));

await pg.click('.tab[data-tab="s-rank"]');
await pg.waitForTimeout(500);
if (await pg.isVisible("#s-rank-limit")) {
  await pg.selectOption("#s-rank-limit", "300");
  await pg.uncheck("#s-rank-exclude");
  await pg.click('#s-rank button:has-text("クリア")');
  await pg.waitForTimeout(400);
  check("ランキング: 上位が50位に戻る", (await val(pg, "s-rank-limit")) === "50", await val(pg, "s-rank-limit"));
  check("ランキング: 除外のチェックが付け直る", (await val(pg, "s-rank-exclude")) === "true");
}

// ── 8. 処方箋のメモ欄(入力 → 保存 → 詳細に出る) ──
// ★処方箋・購入履歴は**起動時データに無く、顧客を開いた時に読む**ので、
//   先にDBで見つけておいた顧客IDを使う(環境変数で受け取る)。
const rxCust = process.env.RX_CUST || null;
if (rxCust) {
  await pg.evaluate((cid) => openCustomer(cid, { tab: "c-glasses" }), rxCust);
  await pg.waitForTimeout(1200);
  const NOTE = "動作確認メモ " + Date.now();
  // ★「この処方箋を編集」は**折りたたみの中**にあるので、まず行を開く
  await pg.evaluate(() => {
    const row = Array.from(document.querySelectorAll("#c-glasses table.data tbody tr"))
      .find((r) => !r.classList.contains("rx-detail-row"));
    if (row) row.click();
  });
  await pg.waitForTimeout(700);
  await pg.evaluate(() => {
    const b = Array.from(document.querySelectorAll("#c-glasses button"))
      .find((x) => x.textContent.includes("この処方箋を編集"));
    if (b) b.click();
  });
  await pg.waitForTimeout(900);
  check("処方箋: 編集の画面が開く", await pg.isVisible("#rx-modal.show"));
  check("処方箋: メモ欄がある", await pg.isVisible("#rx-note"));
  if (await pg.isVisible("#rx-note")) {
    await pg.fill("#rx-note", NOTE);
    await pg.click("#rx-save");
    await pg.waitForTimeout(1600);
    // ★保存すると一覧が描き直されて折りたたみが閉じるので、**開き直してから**確かめる
    await pg.evaluate(() => {
      const row = Array.from(document.querySelectorAll("#c-glasses table.data tbody tr"))
        .find((r) => !r.classList.contains("rx-detail-row"));
      if (row) row.click();
    });
    await pg.waitForTimeout(700);
    const shown = await pg.evaluate(() => (document.getElementById("c-glasses") || {}).innerText || "");
    check("処方箋: 保存したメモが詳細に出る", shown.includes(NOTE.slice(0, 12)),
      shown.includes("メモ") ? "(メモ欄は描画されている)" : "(出ていない)");
    await pg.screenshot({ path: SHOT + "/v160_rx_note.png" });
  }
} else {
  check("処方箋: 見本データが無く確認できず", false, "サンプルDBに処方箋が無い");
}

// ── 9. 番号なし明細に「番号を紐づけ」ボタンが出る ──
const freeCust = process.env.FREE_CUST || null;
if (freeCust) {
  await pg.evaluate((cid) => openCustomer(cid, { tab: "c-history" }), freeCust);
  await pg.waitForTimeout(1200);
  check("番号なし明細に「番号を紐づけ」が出る",
    (await pg.innerText("#c-history")).includes("番号を紐づけ"));
} else {
  check("番号なし明細の見本が無く確認できず", false, "サンプルDBに番号なし明細が無い");
}

check("画面のJavaScriptエラーが無い", errors.length === 0, errors.slice(0, 2).join(" / "));
await br.close();

const ng = results.filter((r) => !r[1]);
console.log("\n=== 結果: " + (results.length - ng.length) + "/" + results.length + " OK ===");
if (ng.length) { console.log("★NGあり:"); ng.forEach((r) => console.log("  - " + r[0] + (r[2] ? "  … " + r[2] : ""))); }
process.exit(ng.length ? 1 : 0);

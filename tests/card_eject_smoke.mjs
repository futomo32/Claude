// カード排出ボタン・①の帯・クリアボタン・エラーのログ残しを実ブラウザで確かめる(v1.5.0)。
//
//   python3 server/app.py 8760 kiki &      # 機器モードONで起動しておく
//   node tests/card_eject_smoke.mjs
//   ※playwright は環境に入っているものを絶対パスで読む(ESMはNODE_PATHを見ないため)。
//     置き場所が違う環境では PLAYWRIGHT_PKG で指定する。
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

const br = await chromium.launch({ executable_path: undefined,
  executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" });
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

check("バージョン表示が v1.5.0", (await pg.innerText("#app-ver")).trim() === "v1.5.0",
  (await pg.innerText("#app-ver")).trim());
check("機器モードONで動いている", (await pg.innerText("#hw-pill")).includes("機器ON"),
  (await pg.innerText("#hw-pill")).trim());

// ── 画面上部の「⏏ カード排出」が常時出ているか ──
check("上部に「⏏ カード排出」が出ている", await pg.isVisible("#topbar-eject"),
  (await pg.innerText("#topbar-eject")).trim());

// ── レジ ──
await pg.click('.nav-item[data-screen="register"]');
await pg.waitForTimeout(1000);

check("レジに①の帯が出ている", await pg.isVisible("#pos-step1"));
check("①の帯が顧客欄の一番左", await pg.evaluate(
  () => document.querySelector("#pos-cust-search").firstElementChild.id === "pos-step1"));
check("帯に色が付いている", await pg.evaluate(() => {
  const bg = getComputedStyle(document.getElementById("pos-step1")).backgroundColor;
  return bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent";
}), await pg.evaluate(() => getComputedStyle(document.getElementById("pos-step1")).backgroundColor));
check("番号①が出ている", (await pg.innerText("#pos-step1")).includes("①"),
  (await pg.innerText("#pos-step1")).replace(/\s+/g, " ").trim());
check("カード読取ボタンの文言", (await pg.innerText("#card-read-btn")).trim() === "💳 カードを読む",
  (await pg.innerText("#card-read-btn")).trim());
check("検索欄のラベルが②", (await pg.innerText("#pos-cust-search .search-wrap label")).includes("②"),
  (await pg.innerText("#pos-cust-search .search-wrap label")).replace(/\s+/g, " ").trim());
check("レジにも排出ボタンがある",
  await pg.isVisible('#pos-step1 button:has-text("排出")'));

await pg.screenshot({ path: SHOT + "/v150_pos_step1.png" });

// ── 顧客を選んだ後: 「変更」が「クリア」になっているか ──
await pg.evaluate(() => { posCustomer = findCust("2"); renderPosCustomer(); renderPosReceivable(); });
await pg.waitForTimeout(400);
const acts = (await pg.innerText(".pos-cust-card .pc-actions")).replace(/\s+/g, " ").trim();
check("顧客カードのボタンが「クリア」", acts.includes("クリア") && !acts.includes("変更"), acts);
check("顧客カードでもカードボタンが左", await pg.evaluate(
  () => (document.querySelector(".pos-cust-card .pc-actions button") || {}).textContent.includes("カード")),
  acts);
await pg.screenshot({ path: SHOT + "/v150_pos_card.png" });

// ── 「◯◯様」を伏せてからログに送っているか ──
check("名前を伏せてから送る", await pg.evaluate(
  () => maskNames("⚠ 村田和加様のカードが出ませんでした") === "⚠ ◯◯様のカードが出ませんでした"),
  await pg.evaluate(() => maskNames("⚠ 村田和加様のカードが出ませんでした")));
check("「お客様」は伏せない", await pg.evaluate(
  () => maskNames("⚠ お客様のカードが出ません") === "⚠ お客様のカードが出ません"));

// ── 排出ボタンを押す(この環境にカード機は無いので失敗する=エラーのログが残る道) ──
await pg.click("#topbar-eject");
await pg.waitForTimeout(2500);
const toast = (await pg.innerText("#toast")).replace(/\s+/g, " ").trim();
check("排出を押すと結果が出る", toast.length > 0, toast);

// ── 保持中に押した時だけ確認が出るか ──
await pg.evaluate(() => { setCardHeld("2", "ポイント 花子"); });
await pg.waitForTimeout(200);
await pg.evaluate(() => ejectCardAnytime());
await pg.waitForTimeout(500);
const modalOn = await pg.isVisible("#alert-modal.show");
const modalMsg = modalOn ? (await pg.innerText("#al-msg")).replace(/\s+/g, " ").trim() : "";
check("保持中は確認を出す", modalOn && modalMsg.includes("券面のポイントは古いまま"), modalMsg);
await pg.screenshot({ path: SHOT + "/v150_eject_confirm.png" });
if (modalOn) await pg.click("#al-cancel");
await pg.waitForTimeout(300);
check("保持していない時は確認を出さない", await pg.evaluate(async () => {
  setCardHeld(null);
  ejectCardAnytime();
  await new Promise((r) => setTimeout(r, 300));
  return !document.querySelector("#alert-modal.show");
}));
await pg.waitForTimeout(2500);

// ── ログに残ったか ──
const log = fs.existsSync("logs/エラー_今日.txt")
  ? fs.readFileSync("logs/エラー_今日.txt", "utf-8") : "";
check("[カード] の行が残った", /\[カード\]/.test(log),
  (log.match(/\[カード\].*/g) || []).slice(0, 3).join(" | "));
check("[お知らせ](赤帯の文言)が残った", /\[お知らせ\]/.test(log),
  (log.match(/\[お知らせ\].*/g) || []).slice(0, 2).join(" | "));
check("ログに氏名が入っていない", !/花子|太郎|次郎/.test(log));

check("画面のJavaScriptエラーが無い", errors.length === 0, errors.join(" / "));

await br.close();
const ng = results.filter((r) => !r[1]);
console.log("\n=== 結果: " + (results.length - ng.length) + "/" + results.length + " OK ===");
if (ng.length) { console.log("★NGあり:"); ng.forEach((r) => console.log("  - " + r[0])); }
process.exit(ng.length ? 1 : 0);

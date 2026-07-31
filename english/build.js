#!/usr/bin/env node
/* 5教科の問題データを検証し、テンプレートに埋め込んで english/index.html を生成する */
const fs = require('fs');
const path = require('path');

// このスクリプトは english/ 直下に置いて `node build.js` で実行します。
// english/data/*.js の問題データを検証し、template.html に埋め込んで index.html を生成します。
const SCRATCH = path.join(__dirname, 'data');
const OUT = path.join(__dirname, 'index.html');

const SUBJECT_IDS = ['kokugo', 'suugaku', 'eigo', 'rika', 'shakai'];
const NUM_Q = 30;

const problems = [];
const warn = [];
function fail(msg) { problems.push(msg); }

/* ---------- SVGの安全性チェック ---------- */
const ALLOWED_TAGS = new Set(['svg', 'g', 'line', 'path', 'rect', 'circle', 'ellipse', 'polygon', 'polyline', 'text', 'tspan']);
function checkSvg(fig, where) {
  if (typeof fig !== 'string') { fail(`${where}: fig が文字列ではありません`); return; }
  const s = fig.trim();
  if (!s.startsWith('<svg') || !s.endsWith('</svg>')) { fail(`${where}: fig が <svg> で始まり </svg> で終わっていません`); return; }
  if (!/viewBox\s*=/.test(s)) fail(`${where}: fig に viewBox がありません`);
  if (/\son[a-zA-Z]+\s*=/.test(s)) fail(`${where}: fig にイベント属性が含まれています`);
  if (/javascript:/i.test(s)) fail(`${where}: fig に javascript: が含まれています`);
  if (/<!--|-->/.test(s)) fail(`${where}: fig にコメントが含まれています`);
  if (/xlink:|(\s|;)href\s*=/i.test(s)) fail(`${where}: fig に外部参照(href)が含まれています`);
  for (const m of s.matchAll(/<\/?([a-zA-Z][a-zA-Z0-9:-]*)/g)) {
    if (!ALLOWED_TAGS.has(m[1])) fail(`${where}: fig に許可されていないタグ <${m[1]}> が含まれています`);
  }
  // <script や </svg> 以降の余計な要素がないか
  const closes = (s.match(/<\/svg>/g) || []).length;
  const opens = (s.match(/<svg/g) || []).length;
  if (opens !== 1 || closes !== 1) fail(`${where}: fig の <svg> がちょうど1つではありません`);
}

/* ---------- 問題1件の検証 ---------- */
function checkQuestion(q, where) {
  if (typeof q !== 'object' || q === null) { fail(`${where}: 問題がオブジェクトではありません`); return; }
  if (typeof q.t !== 'string' || !q.t.trim()) fail(`${where}: t が空です`);
  else if ([...q.t].length > 12) warn.push(`${where}: t が長い (${q.t})`);
  if (typeof q.q !== 'string' || !q.q.trim()) fail(`${where}: q が空です`);
  if (typeof q.e !== 'string' || !q.e.trim()) fail(`${where}: e(解説) が空です`);
  if (!Array.isArray(q.c) || q.c.length !== 4) { fail(`${where}: 選択肢が4つではありません`); return; }
  if (q.c.some(c => typeof c !== 'string' || !c.trim())) fail(`${where}: 空の選択肢があります`);
  if (new Set(q.c.map(c => String(c).trim())).size !== 4) fail(`${where}: 選択肢が重複しています (${q.c.join(' / ')})`);
  if (q.a !== 0) fail(`${where}: a が 0 ではありません (正解は c[0] に置く規約)`);
  if (q.fig !== undefined) checkSvg(q.fig, where);
  for (const k of Object.keys(q)) {
    if (!['t', 'q', 'c', 'a', 'e', 'fig'].includes(k)) warn.push(`${where}: 未知のフィールド ${k}`);
  }
}

/* ---------- 教科データを読む（英語は退避済みの単一ファイル、他はa/bの2分割） ---------- */
// 書き込み途中のファイルで落ちないよう、読めなければ「未完成」として扱う
function tryRequire(p) {
  if (!fs.existsSync(p)) return null;
  try {
    delete require.cache[require.resolve(p)];
    const m = require(p);
    if (!m || !Array.isArray(m.levels) || typeof m.questions !== 'object') return null;
    return m;
  } catch (e) {
    warn.push(`${path.basename(p)}: 読み込めません（作成途中の可能性）: ${e.message.split('\n')[0]}`);
    return null;
  }
}

function loadSubject(id) {
  const single = path.join(SCRATCH, `data_${id}.js`);
  if (fs.existsSync(single)) {
    const p = tryRequire(single);
    return p ? { levels: p.levels.slice().sort((a, b) => a.n - b.n), questions: p.questions } : null;
  }
  const parts = ['a', 'b'].map(suf => tryRequire(path.join(SCRATCH, `data_${id}_${suf}.js`)));
  if (parts.some(p => p === null)) return null;
  const levels = [];
  const questions = {};
  parts.forEach(p => {
    p.levels.forEach(l => levels.push({ n: l.n, grade: l.grade, title: l.title, desc: l.desc }));
    Object.keys(p.questions).forEach(k => { questions[k] = p.questions[k]; });
  });
  levels.sort((a, b) => a.n - b.n);
  return { levels, questions };
}

/* ---------- 教科データの検証 ---------- */
function checkSubject(id, data) {
  const ns = data.levels.map(l => l.n);
  if (JSON.stringify(ns) !== JSON.stringify([1,2,3,4,5,6,7,8,9,10])) fail(`${id}: レベル番号が 1〜10 になっていません (${ns.join(',')})`);
  data.levels.forEach(l => {
    if (!['中1','中2','中3','受験'].includes(l.grade)) fail(`${id} Lv${l.n}: grade が不正 (${l.grade})`);
    if (!l.title || !l.desc) fail(`${id} Lv${l.n}: title/desc が空です`);
  });
  let figCount = 0;
  for (let n = 1; n <= 10; n++) {
    const bank = data.questions[n];
    if (!Array.isArray(bank)) { fail(`${id} Lv${n}: 問題配列がありません`); continue; }
    if (bank.length !== NUM_Q) fail(`${id} Lv${n}: 問題数が ${bank.length} 問です（${NUM_Q}問必要）`);
    const seen = new Set();
    bank.forEach((q, i) => {
      checkQuestion(q, `${id} Lv${n} #${i + 1}`);
      const key = String(q && q.q).trim();
      if (seen.has(key)) fail(`${id} Lv${n} #${i + 1}: 問題文が重複しています`);
      seen.add(key);
      if (q && q.fig) figCount++;
    });
  }
  return figCount;
}

/* ---------- 実行 ---------- */
const SUBJECT_DATA = {};
const summary = [];

for (const id of SUBJECT_IDS) {
  const data = loadSubject(id);
  if (!data) { summary.push(`${id}: データなし（準備中のまま）`); continue; }
  const figs = checkSubject(id, data);
  const total = Object.keys(data.questions).reduce((s, k) => s + data.questions[k].length, 0);
  summary.push(`${id}: ${data.levels.length}レベル / ${total}問 / 図つき ${figs}問`);
  SUBJECT_DATA[id] = data;
}

console.log('--- 集計 ---');
summary.forEach(s => console.log('  ' + s));
if (warn.length) {
  console.log(`--- 注意 (${warn.length}件) ---`);
  warn.slice(0, 15).forEach(w => console.log('  ' + w));
}
if (problems.length) {
  console.log(`--- エラー (${problems.length}件) ---`);
  problems.slice(0, 40).forEach(p => console.log('  ' + p));
  console.log('エラーがあるため index.html は生成しませんでした。');
  process.exit(1);
}

const template = fs.readFileSync(path.join(__dirname, 'template.html'), 'utf8');
const json = JSON.stringify(SUBJECT_DATA, null, 0);
if (!template.includes('/*__SUBJECT_DATA__*/')) throw new Error('テンプレートに差し込み位置がありません');
const html = template.replace('/*__SUBJECT_DATA__*/', () => json);
fs.writeFileSync(OUT, html);
console.log(`--- 生成完了 ---`);
console.log(`  ${OUT}  (${(Buffer.byteLength(html) / 1024).toFixed(0)} KB)`);

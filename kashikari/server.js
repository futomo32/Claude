#!/usr/bin/env node
/* 家族の貸し借りノート — おうちのネットワークで使う小さなサーバー
   Node.js の標準機能だけで動きます（npm install は不要）。
   起動:  node server.js         （ポートを変えるとき: PORT=8080 node server.js）
   保存先: このフォルダの data.json                                        */

const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const crypto = require("crypto");

const PORT = Number(process.env.PORT || 3000);
const PUBLIC_DIR = path.join(__dirname, "public");
const DATA_FILE = process.env.KASHIKARI_DATA || path.join(__dirname, "data.json");

/* ============================================================
   データの読み書き
   ------------------------------------------------------------
   家族数人ぶんの記録なので、まるごと1つのJSONファイルに入れます。
   書き込みは「別名で書いてから rename」にして、
   途中で電源が切れてもファイルが壊れないようにしています。
   ============================================================ */

const EMPTY = { version: 0, members: [], entries: [] };
let state = null;

function loadState() {
  try {
    const raw = fs.readFileSync(DATA_FILE, "utf8");
    const parsed = JSON.parse(raw);
    state = {
      version: Number(parsed.version) || 0,
      members: Array.isArray(parsed.members) ? parsed.members : [],
      entries: Array.isArray(parsed.entries) ? parsed.entries : [],
    };
  } catch (e) {
    if (e.code !== "ENOENT") {
      console.error("⚠️  data.json を読めませんでした:", e.message);
      // 壊れたファイルを消さずに残しておく（あとで中身を救えるように）
      try {
        const backup = DATA_FILE + ".broken-" + Date.now();
        fs.copyFileSync(DATA_FILE, backup);
        console.error("   いまの中身を " + path.basename(backup) + " に退避しました");
      } catch (_) {}
    }
    state = { ...EMPTY, members: [], entries: [] };
  }
}

let saveQueued = false;
function saveState() {
  state.version += 1;
  // 連続で書き換えたときに書き込みが重ならないよう、次のターンにまとめる
  if (saveQueued) return;
  saveQueued = true;
  process.nextTick(() => {
    saveQueued = false;
    const tmp = DATA_FILE + ".tmp";
    try {
      fs.writeFileSync(tmp, JSON.stringify(state, null, 2), "utf8");
      fs.renameSync(tmp, DATA_FILE);
    } catch (e) {
      console.error("⚠️  保存に失敗しました:", e.message);
    }
  });
}

/* ============================================================
   入力のチェック
   ============================================================ */

class BadRequest extends Error {}

function str(value, { max = 100, required = false, label = "項目" } = {}) {
  if (value === undefined || value === null) {
    if (required) throw new BadRequest(label + "を入力してください");
    return "";
  }
  if (typeof value !== "string") throw new BadRequest(label + "の形式が正しくありません");
  const s = value.trim();
  if (required && !s) throw new BadRequest(label + "を入力してください");
  if (s.length > max) throw new BadRequest(label + "は" + max + "文字までです");
  return s;
}

function amount(value) {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) throw new BadRequest("金額を数字で入力してください");
  if (n <= 0) throw new BadRequest("金額は1円以上にしてください");
  if (n > 1000000000) throw new BadRequest("金額が大きすぎます");
  return n;
}

function dateStr(value) {
  const s = str(value, { max: 10, required: true, label: "日付" });
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) throw new BadRequest("日付は YYYY-MM-DD の形で入力してください");
  const d = new Date(s + "T00:00:00");
  if (Number.isNaN(d.getTime())) throw new BadRequest("その日付は存在しません");
  return s;
}

function memberId(value, label) {
  const id = str(value, { max: 60, required: true, label });
  if (!state.members.some((m) => m.id === id)) throw new BadRequest(label + "が見つかりません");
  return id;
}

function kindOf(value) {
  const k = str(value, { max: 10, required: true, label: "種類" });
  if (k !== "loan" && k !== "repay") throw new BadRequest("種類は loan か repay です");
  return k;
}

/* ============================================================
   API
   ============================================================ */

function publicState() {
  return { version: state.version, members: state.members, entries: state.entries };
}

function buildEntry(body, base) {
  const kind = kindOf(body.kind);
  const from = memberId(body.from, "お金を出した人");
  const to = memberId(body.to, "お金を受け取った人");
  if (from === to) throw new BadRequest("同じ人どうしでは記録できません");
  return {
    id: base ? base.id : crypto.randomUUID(),
    kind,
    from,
    to,
    amount: amount(body.amount),
    date: dateStr(body.date),
    note: str(body.note, { max: 200, label: "メモ" }),
    createdAt: base ? base.createdAt : new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

const routes = [
  {
    method: "GET",
    pattern: /^\/api\/state$/,
    handle(_m, _body, query) {
      const since = Number(query.get("since"));
      // 変わっていなければ中身を返さない（数秒おきの確認を軽くするため）
      if (Number.isFinite(since) && since === state.version) {
        return { version: state.version, unchanged: true };
      }
      return publicState();
    },
  },
  {
    method: "POST",
    pattern: /^\/api\/members$/,
    handle(_m, body) {
      const name = str(body.name, { max: 20, required: true, label: "名前" });
      if (state.members.some((x) => x.name === name)) throw new BadRequest("「" + name + "」はもういます");
      if (state.members.length >= 30) throw new BadRequest("メンバーは30人までです");
      state.members.push({ id: crypto.randomUUID(), name, color: str(body.color, { max: 20 }) || "" });
      saveState();
      return publicState();
    },
  },
  {
    method: "PATCH",
    pattern: /^\/api\/members\/([\w-]+)$/,
    handle(m, body) {
      const target = state.members.find((x) => x.id === m[1]);
      if (!target) throw new BadRequest("そのメンバーは見つかりません");
      if (body.name !== undefined) {
        const name = str(body.name, { max: 20, required: true, label: "名前" });
        if (state.members.some((x) => x.name === name && x.id !== target.id)) {
          throw new BadRequest("「" + name + "」はもういます");
        }
        target.name = name;
      }
      if (body.color !== undefined) target.color = str(body.color, { max: 20 });
      saveState();
      return publicState();
    },
  },
  {
    method: "DELETE",
    pattern: /^\/api\/members\/([\w-]+)$/,
    handle(m) {
      const id = m[1];
      if (!state.members.some((x) => x.id === id)) throw new BadRequest("そのメンバーは見つかりません");
      if (state.entries.some((e) => e.from === id || e.to === id)) {
        throw new BadRequest("記録が残っている人は消せません。先に記録を消してください");
      }
      state.members = state.members.filter((x) => x.id !== id);
      saveState();
      return publicState();
    },
  },
  {
    method: "POST",
    pattern: /^\/api\/entries$/,
    handle(_m, body) {
      if (state.entries.length >= 20000) throw new BadRequest("記録が多すぎます。古い記録を整理してください");
      state.entries.push(buildEntry(body, null));
      saveState();
      return publicState();
    },
  },
  {
    method: "PATCH",
    pattern: /^\/api\/entries\/([\w-]+)$/,
    handle(m, body) {
      const i = state.entries.findIndex((e) => e.id === m[1]);
      if (i < 0) throw new BadRequest("その記録は見つかりません（ほかの人が消したかもしれません）");
      state.entries[i] = buildEntry({ ...state.entries[i], ...body }, state.entries[i]);
      saveState();
      return publicState();
    },
  },
  {
    method: "DELETE",
    pattern: /^\/api\/entries\/([\w-]+)$/,
    handle(m) {
      const before = state.entries.length;
      state.entries = state.entries.filter((e) => e.id !== m[1]);
      if (state.entries.length === before) throw new BadRequest("その記録は見つかりません");
      saveState();
      return publicState();
    },
  },
];

/* ============================================================
   HTTP サーバー
   ============================================================ */

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".webmanifest": "application/manifest+json",
};

function sendJson(res, status, obj) {
  const buf = Buffer.from(JSON.stringify(obj));
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": buf.length,
    "cache-control": "no-store",
  });
  res.end(buf);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (c) => {
      size += c.length;
      if (size > 1000000) {
        reject(new BadRequest("送られたデータが大きすぎます"));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8").trim();
      if (!raw) return resolve({});
      try {
        const parsed = JSON.parse(raw);
        resolve(parsed && typeof parsed === "object" ? parsed : {});
      } catch (_) {
        reject(new BadRequest("データの形式が正しくありません"));
      }
    });
    req.on("error", reject);
  });
}

function serveStatic(req, res, pathname) {
  const rel = pathname === "/" ? "index.html" : decodeURIComponent(pathname).replace(/^\/+/, "");
  const file = path.join(PUBLIC_DIR, rel);
  // public フォルダの外に出ていないことを必ず確認する
  if (!file.startsWith(PUBLIC_DIR + path.sep) && file !== PUBLIC_DIR) {
    res.writeHead(403).end("Forbidden");
    return;
  }
  fs.stat(file, (err, stat) => {
    if (err || !stat.isFile()) {
      res.writeHead(404, { "content-type": "text/plain; charset=utf-8" }).end("ページが見つかりません");
      return;
    }
    res.writeHead(200, {
      "content-type": MIME[path.extname(file).toLowerCase()] || "application/octet-stream",
      "content-length": stat.size,
      "cache-control": "no-cache",
    });
    fs.createReadStream(file).pipe(res);
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const pathname = url.pathname;

  if (!pathname.startsWith("/api/")) {
    if (req.method === "GET" || req.method === "HEAD") return serveStatic(req, res, pathname);
    res.writeHead(405).end();
    return;
  }

  try {
    for (const route of routes) {
      const m = pathname.match(route.pattern);
      if (!m) continue;
      if (route.method !== req.method) continue;
      const body = req.method === "GET" ? {} : await readBody(req);
      return sendJson(res, 200, route.handle(m, body, url.searchParams));
    }
    sendJson(res, 404, { error: "そのURLはありません" });
  } catch (e) {
    if (e instanceof BadRequest) return sendJson(res, 400, { error: e.message });
    console.error(e);
    sendJson(res, 500, { error: "サーバーで問題が起きました" });
  }
});

/* ============================================================
   起動
   ============================================================ */

function lanAddresses() {
  const list = [];
  for (const nets of Object.values(os.networkInterfaces())) {
    for (const net of nets || []) {
      if (net.family === "IPv4" && !net.internal) list.push(net.address);
    }
  }
  return list;
}

loadState();
server.listen(PORT, "0.0.0.0", () => {
  const urls = lanAddresses().map((ip) => "http://" + ip + ":" + PORT + "/");
  console.log("");
  console.log("  💰 家族の貸し借りノート を開きました");
  console.log("");
  console.log("  このパソコンから  : http://localhost:" + PORT + "/");
  if (urls.length) {
    console.log("  同じWi-Fiのスマホ : " + urls[0]);
    urls.slice(1).forEach((u) => console.log("                    : " + u));
  } else {
    console.log("  ⚠️ ネットワークに つながっていないようです（Wi-Fiを確認してください）");
  }
  console.log("");
  console.log("  保存先: " + DATA_FILE);
  console.log("  終わるときは Ctrl + C");
  console.log("");
});

server.on("error", (e) => {
  if (e.code === "EADDRINUSE") {
    console.error("⚠️ ポート " + PORT + " はすでに使われています。");
    console.error("   PORT=3001 node server.js のように、別の番号で起動してください。");
    process.exit(1);
  }
  throw e;
});

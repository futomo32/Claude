/* ヤナセぱっと勤怠 service worker — オフラインでも動くようにキャッシュします
   リポジトリ直下の3アプリ（勤怠 / english / prompt）をまとめて受け持ちます */
const CACHE = "patto-kintai-v7";
const ASSETS = ["./", "./index.html", "./guide.html", "./manifest.json", "./logo.png", "./icon.png", "./icon-maskable.png",
  "./prompt/", "./prompt/index.html", "./prompt/app.js", "./prompt/data.js", "./prompt/manifest.json"];

/* 1件でも取れないファイルがあっても install を失敗させない。
   （addAll だと全部やり直しになり、更新が届かなくなるため1件ずつ入れる） */
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) =>
      Promise.all(ASSETS.map((url) => c.add(url).catch(() => null)))
    )
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

/* network first, cache fallback — 更新があれば取り込み、圏外でも動く */
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() =>
        caches.match(e.request).then((m) => {
          if (m) return m;
          /* 圏外でキャッシュにもない場合。ページ遷移のときだけ、
             そのアプリのトップを返す（別アプリの画面が出るのを防ぐ） */
          if (e.request.mode === "navigate") {
            const path = new URL(e.request.url).pathname;
            if (path.indexOf("/prompt/") >= 0) return caches.match("./prompt/index.html");
            return caches.match("./index.html");
          }
          return Response.error();
        })
      )
  );
});

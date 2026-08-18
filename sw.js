/* ヤナセぱっと勤怠 service worker — オフラインでも動くようにキャッシュします */
const CACHE = "patto-kintai-v7";
const ASSETS = ["./", "./index.html", "./guide.html", "./manifest.json", "./logo.png", "./icon.png", "./icon-maskable.png",
  "./prompt/", "./prompt/index.html", "./prompt/app.js", "./prompt/data.js", "./prompt/manifest.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
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
      .catch(() => caches.match(e.request).then((m) => m || caches.match("./index.html")))
  );
});

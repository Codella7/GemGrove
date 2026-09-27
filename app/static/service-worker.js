const CACHE_NAME = "gemgrove-shell-v1";
const SHELL_ASSETS = [
  "/static/offline.html",
  "/static/css/style.css",
  "/static/images/GemGrove%20Favicon.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => caches.match("/static/offline.html")));
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { body: event.data ? event.data.text() : "A payment is due today." };
  }
  event.waitUntil(self.registration.showNotification(payload.title || "GemGrove reminder", {
    body: payload.body || "An unpaid payment is due today.",
    icon: "/static/images/GemGrove%20Favicon.png",
    badge: "/static/images/GemGrove%20Favicon.png",
    tag: "gemgrove-due-payments",
    data: { url: payload.url || "/reminders" }
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const destination = new URL(event.notification.data.url || "/reminders", self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
    const openClient = clients.find((client) => new URL(client.url).origin === self.location.origin);
    if (openClient) {
      openClient.navigate(destination);
      return openClient.focus();
    }
    return self.clients.openWindow(destination);
  }));
});
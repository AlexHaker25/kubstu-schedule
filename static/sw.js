// Service worker: кэширует "оболочку" приложения (HTML/манифест/иконки),
// чтобы страница открывалась даже без интернета. Сами данные расписания
// кэшируются отдельно в localStorage внутри index.html — сюда их специально
// не пускаем, чтобы логика недели/дня не путалась со старым кэшем API.

const CACHE = 'kubstu-shell-v1';
const ASSETS = [
  './',
  'index.html',
  'manifest.json',
  'favicon.png',
  'apple-touch-icon.png',
  'icons/icon-192.png',
  'icons/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  let url;
  try { url = new URL(req.url); } catch (e) { return; }

  // Запросы к API не кэшируем здесь — их обрабатывает index.html сам
  if (url.pathname.startsWith('/api/')) return;
  if (url.origin !== self.location.origin) return;

  // Переход на саму страницу: сеть, а если её нет — последняя сохранённая версия
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE).then((cache) => cache.put('index.html', copy));
          return resp;
        })
        .catch(() => caches.match('index.html'))
    );
    return;
  }

  // Прочие свои файлы (манифест, иконки): сначала кэш, потом сеть
  event.respondWith(
    caches.match(req).then((cached) => {
      const fetchPromise = fetch(req).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((cache) => cache.put(req, copy));
        return resp;
      }).catch(() => cached);
      return cached || fetchPromise;
    })
  );
});

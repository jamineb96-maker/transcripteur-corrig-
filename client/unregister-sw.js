/*
 * Utilitaire manuel pour désinscrire tous les Service Workers et purger les caches.
 * À exécuter via un import direct, la console DevTools ou un script de maintenance.
 */
(async () => {
  try {
    const { navigator } = globalThis;
    if (navigator && 'serviceWorker' in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      if (registrations.length > 0) {
        await Promise.all(registrations.map((registration) => registration.unregister()));
      }
      console.info(`[unregister-sw] ${registrations.length} service worker(s) désinscrit(s).`);
    } else {
      console.info('[unregister-sw] API serviceWorker indisponible.');
    }

    if ('caches' in globalThis) {
      const cacheStorage = globalThis.caches;
      const keys = await cacheStorage.keys();
      if (keys.length > 0) {
        await Promise.all(keys.map((key) => cacheStorage.delete(key)));
      }
      console.info(`[unregister-sw] ${keys.length} cache(s) supprimé(s).`);
    } else {
      console.info('[unregister-sw] API CacheStorage indisponible.');
    }
  } catch (error) {
    console.error('[unregister-sw] Échec de la purge des caches', error);
  }
})();

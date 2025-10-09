(async () => {
  try {
    if (!('serviceWorker' in navigator)) {
      console.warn('navigator.serviceWorker n\'est pas disponible dans ce contexte.');
      return;
    }

    const registrations = await navigator.serviceWorker.getRegistrations();
    for (const registration of registrations) {
      try {
        const success = await registration.unregister();
        console.info('Service worker', registration.scope, success ? 'supprimé' : 'non supprimé');
      } catch (error) {
        console.error('Échec de la suppression du service worker', registration.scope, error);
      }
    }

    if ('caches' in self) {
      const cacheKeys = await caches.keys();
      await Promise.all(
        cacheKeys.map(async (key) => {
          try {
            await caches.delete(key);
            console.info('Cache', key, 'supprimé');
          } catch (error) {
            console.error('Impossible de supprimer le cache', key, error);
          }
        })
      );
    }
  } finally {
    // Laisse le temps aux logs d\'être flushés avant de fermer la fenêtre.
    setTimeout(() => {
      if (typeof window !== 'undefined' && typeof window.close === 'function') {
        window.close();
      }
    }, 500);
  }
})();

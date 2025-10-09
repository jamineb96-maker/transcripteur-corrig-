export function nanoid(prefix = "id") {
  const cryptoApi = globalThis.crypto || (typeof window !== "undefined" ? window.crypto : null);
  const raw = cryptoApi
    ? Array.from(cryptoApi.getRandomValues(new Uint32Array(2)), value => value.toString(36)).join("")
    : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${raw.slice(0, 12)}`;
}

export function downloadFile(content, filename, type = "application/octet-stream") {
  const blob = content instanceof Blob ? content : new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function debounce(fn, delay = 150) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

export function lerp(a, b, t) {
  return a + (b - a) * t;
}

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

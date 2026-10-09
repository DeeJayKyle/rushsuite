// Local browser test stub for @capacitor/core (the real package is used in the Android build).
export const Capacitor = { isNativePlatform: () => false, getPlatform: () => 'web' };
export function registerPlugin(name) {
  return new Proxy({}, { get: (_t, m) => () => Promise.reject(new Error(`${name}.${String(m)} is not available on web`)) });
}

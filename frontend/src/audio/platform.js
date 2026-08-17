// iPadOS reports platform as "MacIntel" (like a real Mac) unless we also
// check for touch support, so a plain userAgent check isn't enough.
export function isIOS() {
  const ua = navigator.userAgent;
  const isIPhoneOrIPod = /iPhone|iPod/.test(ua);
  const isIPad = /iPad/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  return isIPhoneOrIPod || isIPad;
}

export function isAndroid() {
  return /Android/.test(navigator.userAgent);
}

export function getOS() {
  if (isIOS()) return 'iOS';
  if (isAndroid()) return 'Android';
  if (/Win/.test(navigator.userAgent)) return 'Windows';
  if (/Mac/.test(navigator.userAgent)) return 'macOS';
  if (/Linux/.test(navigator.userAgent)) return 'Linux';
  return 'Unknown';
}

export function getDeviceType() {
  const ua = navigator.userAgent;
  if (isIOS()) return /iPad/.test(ua) || navigator.platform === 'MacIntel' ? 'Tablet' : 'Mobile';
  if (isAndroid()) return /Mobile/.test(ua) ? 'Mobile' : 'Tablet';
  return 'Desktop';
}

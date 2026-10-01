const SESSION_ID = crypto.randomUUID?.() || Math.random().toString(36).slice(2);

export function trackPageView(screen: string) {
  try {
    navigator.sendBeacon?.('/api/analytics/pageview', JSON.stringify({
      screen,
      sessionId: SESSION_ID,
      timestamp: new Date().toISOString(),
      userAgent: navigator.userAgent,
      viewport: `${window.innerWidth}x${window.innerHeight}`,
    }));
  } catch {}
}

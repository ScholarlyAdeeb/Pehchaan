// Session plumbing for every /api call.
//
// The session lives in HttpOnly cookies the page cannot read, so there is no
// token to attach. This wrapper around window.fetch:
//   * echoes the CSRF cookie in X-CSRF-Token (the server requires it on every
//     state-changing request made with the session cookie);
//   * when a request comes back 401 because the 15-minute access token ran
//     out, renews the session once and repeats the request;
//   * tells the app when the session really is over.
//
// Components still pass `Authorization: Bearer ${token}`; `token` is now just
// the marker below, and the header is dropped here so nothing secret-looking
// leaves the page.
export const SESSION_MARKER = 'session';
export const SESSION_EXPIRED_EVENT = 'pehchaan:session-expired';

const NO_RENEW = ['/api/auth/login', '/api/auth/refresh', '/api/auth/logout', '/api/auth/setup'];

function csrfToken(): string {
  const m = document.cookie.match(/(?:^|;\s*)pehchaan_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : '';
}

let renewing: Promise<boolean> | null = null;

/** Renews the session; concurrent callers share one request. */
export function renewSession(nativeFetch: typeof fetch = window.fetch): Promise<boolean> {
  renewing ??= nativeFetch('/api/auth/refresh', { method: 'POST', credentials: 'same-origin' })
    .then((res) => res.ok)
    .catch(() => false)
    .finally(() => { renewing = null; });
  return renewing;
}

export function installApiFetch(): void {
  const nativeFetch = window.fetch.bind(window);
  if ((window as any).__pehchaanFetchInstalled) return;
  (window as any).__pehchaanFetchInstalled = true;

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url;
    const path = url.startsWith('http') ? new URL(url).pathname : url;
    if (!path.startsWith('/api/')) return nativeFetch(input, init);

    const prepare = (): RequestInit => {
      const headers = new Headers(init?.headers || {});
      if (headers.get('Authorization') === `Bearer ${SESSION_MARKER}`) headers.delete('Authorization');
      const method = (init?.method || 'GET').toUpperCase();
      if (!['GET', 'HEAD'].includes(method)) headers.set('X-CSRF-Token', csrfToken());
      return { ...init, headers, credentials: 'same-origin' };
    };

    let res = await nativeFetch(input, prepare());
    if (res.status !== 401 || NO_RENEW.some((p) => path.startsWith(p))) return res;

    if (await renewSession(nativeFetch)) {
      res = await nativeFetch(input, prepare()); // new cookies, new CSRF value
      if (res.status !== 401) return res;
    }
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    return res;
  };
}

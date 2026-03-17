/*
 * OpenMates CLI HTTP transport.
 *
 * Purpose: shared fetch client with lightweight cookie jar support.
 * Architecture: Node fetch + explicit Cookie header for authenticated endpoints.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: cookie parsing stores name/value only; attributes are discarded.
 * Tests: covered via client and CLI integration-style tests.
 */

export interface HttpClientOptions {
  apiUrl: string;
  cookies?: Record<string, string>;
}

export interface HttpResponse<T = unknown> {
  ok: boolean;
  status: number;
  data: T;
}

export class OpenMatesHttpClient {
  private readonly apiUrl: string;
  private readonly cookies: Map<string, string>;

  constructor(options: HttpClientOptions) {
    this.apiUrl = options.apiUrl.replace(/\/$/, "");
    this.cookies = new Map<string, string>(
      Object.entries(options.cookies ?? {}),
    );
  }

  getCookieMap(): Record<string, string> {
    return Object.fromEntries(this.cookies.entries());
  }

  async get<T>(
    path: string,
    headers: Record<string, string> = {},
  ): Promise<HttpResponse<T>> {
    return this.request<T>("GET", path, undefined, headers);
  }

  async post<T>(
    path: string,
    body?: unknown,
    headers: Record<string, string> = {},
  ): Promise<HttpResponse<T>> {
    return this.request<T>("POST", path, body, headers);
  }

  private async request<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
    headers: Record<string, string> = {},
  ): Promise<HttpResponse<T>> {
    const url = `${this.apiUrl}${path.startsWith("/") ? path : `/${path}`}`;
    const requestHeaders: Record<string, string> = {
      Accept: "application/json",
      ...headers,
    };
    const cookieHeader = this.formatCookieHeader();
    if (cookieHeader) {
      requestHeaders.Cookie = cookieHeader;
    }
    if (body !== undefined) {
      requestHeaders["Content-Type"] = "application/json";
    }

    const response = await fetch(url, {
      method,
      headers: requestHeaders,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    this.captureCookies(response);

    let data: unknown = {};
    try {
      data = await response.json();
    } catch {
      data = {};
    }

    return {
      ok: response.ok,
      status: response.status,
      data: data as T,
    };
  }

  private formatCookieHeader(): string {
    if (this.cookies.size === 0) {
      return "";
    }
    return Array.from(this.cookies.entries())
      .map(([key, value]) => `${key}=${value}`)
      .join("; ");
  }

  private captureCookies(response: Response): void {
    const setCookieValues = this.getSetCookieValues(response);
    for (const setCookie of setCookieValues) {
      const [cookiePair] = setCookie.split(";");
      const separator = cookiePair.indexOf("=");
      if (separator <= 0) {
        continue;
      }
      const name = cookiePair.slice(0, separator).trim();
      const value = cookiePair.slice(separator + 1).trim();
      if (!name) {
        continue;
      }
      this.cookies.set(name, value);
    }
  }

  private getSetCookieValues(response: Response): string[] {
    const headersAny = response.headers as Headers & {
      getSetCookie?: () => string[];
      raw?: () => Record<string, string[]>;
    };
    if (typeof headersAny.getSetCookie === "function") {
      return headersAny.getSetCookie();
    }
    if (typeof headersAny.raw === "function") {
      const raw = headersAny.raw();
      return raw["set-cookie"] ?? [];
    }
    const single = response.headers.get("set-cookie");
    return single ? [single] : [];
  }
}

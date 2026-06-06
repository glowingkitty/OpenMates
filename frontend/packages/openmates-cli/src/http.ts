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

export interface HttpBinaryResponse {
  ok: boolean;
  status: number;
  data: Uint8Array;
  headers: Headers;
}

export interface SseMessage {
  id?: string;
  event?: string;
  data: string;
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

  async delete<T>(
    path: string,
    body?: unknown,
    headers: Record<string, string> = {},
  ): Promise<HttpResponse<T>> {
    return this.request<T>("DELETE", path, body, headers);
  }

  async patch<T>(
    path: string,
    body?: unknown,
    headers: Record<string, string> = {},
  ): Promise<HttpResponse<T>> {
    return this.request<T>("PATCH", path, body, headers);
  }

  async getBinary(
    path: string,
    headers: Record<string, string> = {},
  ): Promise<HttpBinaryResponse> {
    const url = `${this.apiUrl}${path.startsWith("/") ? path : `/${path}`}`;
    const requestHeaders: Record<string, string> = {
      Accept: "application/pdf,application/octet-stream",
      ...headers,
    };
    const cookieHeader = this.formatCookieHeader();
    if (cookieHeader) requestHeaders.Cookie = cookieHeader;

    const response = await fetch(url, { method: "GET", headers: requestHeaders });
    this.captureCookies(response);
    return {
      ok: response.ok,
      status: response.status,
      data: new Uint8Array(await response.arrayBuffer()),
      headers: response.headers,
    };
  }

  async *streamSse(
    path: string,
    headers: Record<string, string> = {},
  ): AsyncGenerator<SseMessage> {
    const url = `${this.apiUrl}${path.startsWith("/") ? path : `/${path}`}`;
    const requestHeaders: Record<string, string> = {
      Accept: "text/event-stream",
      ...headers,
    };
    const cookieHeader = this.formatCookieHeader();
    if (cookieHeader) requestHeaders.Cookie = cookieHeader;

    const response = await fetch(url, { method: "GET", headers: requestHeaders });
    this.captureCookies(response);
    if (!response.ok) {
      throw new Error(`SSE request failed with HTTP ${response.status}`);
    }
    if (!response.body) {
      throw new Error("SSE response body is not readable");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let separatorIndex = buffer.indexOf("\n\n");
        while (separatorIndex >= 0) {
          const rawEvent = buffer.slice(0, separatorIndex);
          buffer = buffer.slice(separatorIndex + 2);
          const message = parseSseMessage(rawEvent);
          if (message) yield message;
          separatorIndex = buffer.indexOf("\n\n");
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  private async request<T>(
    method: "GET" | "POST" | "DELETE" | "PATCH",
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

function parseSseMessage(rawEvent: string): SseMessage | null {
  const message: SseMessage = { data: "" };
  for (const line of rawEvent.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator >= 0 ? line.slice(0, separator) : line;
    const value = separator >= 0 ? line.slice(separator + 1).replace(/^ /, "") : "";
    if (field === "id") message.id = value;
    if (field === "event") message.event = value;
    if (field === "data") message.data += `${message.data ? "\n" : ""}${value}`;
  }
  return message.data ? message : null;
}

/*
 * OpenMates npm SDK facade.
 *
 * Purpose: provide an ergonomic API-key client for Node integrations.
 * Architecture: thin REST facade over public /v1 endpoints; CLI client remains separate.
 * Security: API keys are bearer credentials and are never persisted by this class.
 * Tests: frontend/packages/openmates-cli/tests/sdk.test.ts
 */

const DEFAULT_API_URL = "https://api.openmates.org";

export interface OpenMatesOptions {
  apiKey?: string;
  apiUrl?: string;
}

export interface ChatCreateOptions {
  saveToAccount?: boolean;
}

export interface ChatListOptions {
  limit?: number;
  offset?: number;
}

export interface EncryptedChatMetadata {
  id: string;
  encrypted_title?: string;
  encrypted_chat_key?: string;
  updated_at?: string | number;
  created_at?: string | number;
  [key: string]: unknown;
}

export interface ChatResponse {
  content?: string;
  [key: string]: unknown;
}

export class OpenMatesConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OpenMatesConfigError";
  }
}

export class OpenMatesApiError extends Error {
  readonly status: number;
  readonly data: unknown;

  constructor(status: number, data: unknown) {
    super(`OpenMates API request failed with HTTP ${status}`);
    this.name = "OpenMatesApiError";
    this.status = status;
    this.data = data;
  }
}

export class OpenMates {
  readonly apps: OpenMatesApps;
  readonly chats: OpenMatesChats;
  private readonly apiKey?: string;
  private readonly apiUrl: string;

  constructor(options: OpenMatesOptions = {}) {
    this.apiKey = options.apiKey ?? process.env.OPENMATES_API_KEY;
    this.apiUrl = (options.apiUrl ?? DEFAULT_API_URL).replace(/\/$/, "");
    this.apps = new OpenMatesApps(this);
    this.chats = new OpenMatesChats(this);
  }

  async request<T>(path: string, body?: unknown): Promise<T> {
    if (!this.apiKey) {
      throw new OpenMatesConfigError("OpenMates API key is required");
    }

    const response = await fetch(`${this.apiUrl}${path}`, {
      method: "POST",
      headers: this.headers(),
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    return this.parseResponse<T>(response);
  }

  async get<T>(path: string): Promise<T> {
    if (!this.apiKey) {
      throw new OpenMatesConfigError("OpenMates API key is required");
    }

    const response = await fetch(`${this.apiUrl}${path}`, {
      method: "GET",
      headers: this.headers(false),
    });

    return this.parseResponse<T>(response);
  }

  private headers(hasBody = true): Record<string, string> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${this.apiKey}`,
      "X-OpenMates-SDK": "npm",
      "X-OpenMates-Device-Identity": `${process.platform}:${process.arch}`,
    };
    if (hasBody) {
      headers["Content-Type"] = "application/json";
    }
    return headers;
  }

  private async parseResponse<T>(response: Response): Promise<T> {
    let data: unknown = {};
    try {
      data = await response.json();
    } catch {
      data = {};
    }

    if (!response.ok) {
      throw new OpenMatesApiError(response.status, data);
    }

    return data as T;
  }
}

export class OpenMatesApps {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async run<T = unknown>(appId: string, skillId: string, input: unknown): Promise<T> {
    return this.client.request<T>(`/v1/apps/${appId}/skills/${skillId}`, {
      input_data: input,
      parameters: {},
    });
  }
}

export class OpenMatesChats {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async create(options: ChatCreateOptions = {}): Promise<OpenMatesChat> {
    return new OpenMatesChat(this.client, options.saveToAccount === true);
  }

  async list(options: ChatListOptions = {}): Promise<EncryptedChatMetadata[]> {
    const params = new URLSearchParams();
    params.set("limit", String(options.limit ?? 10));
    if (options.offset !== undefined) params.set("offset", String(options.offset));
    const query = params.toString();
    const result = await this.client.get<{ chats: EncryptedChatMetadata[] }>(
      `/v1/sdk/chats${query ? `?${query}` : ""}`,
    );
    return result.chats;
  }
}

export class OpenMatesChat {
  private readonly client: OpenMates;
  private readonly saveToAccount: boolean;

  constructor(client: OpenMates, saveToAccount: boolean) {
    this.client = client;
    this.saveToAccount = saveToAccount;
  }

  async send(message: string): Promise<ChatResponse> {
    const result = await this.client.request<{ response?: ChatResponse }>("/v1/sdk/chats", {
      message,
      save_to_account: this.saveToAccount,
    });
    return result.response ?? result;
  }
}

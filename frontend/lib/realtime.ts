import type { HeartbeatEvent, RealtimeEvent, StaffRole } from "./contracts";
import { nextSequence, reconnectDelay } from "./realtime-policy";

export { nextSequence, reconnectDelay } from "./realtime-policy";

export type RealtimeState = "connecting" | "live" | "polling" | "offline" | "stopped";
export type RealtimeMessage = RealtimeEvent | HeartbeatEvent;

export type RealtimeClientOptions = {
  url: string;
  lastSequence?: number;
  onEvent: (event: RealtimeEvent) => void;
  onStateChange?: (state: RealtimeState) => void;
  onGap?: (expectedSequence: number, receivedSequence: number) => Promise<void> | void;
  pollSnapshot?: () => Promise<void>;
  webSocketFactory?: (url: string) => WebSocket;
  minReconnectMs?: number;
  maxReconnectMs?: number;
};

function withLastSequence(url: string, sequence: number) {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}last_sequence=${encodeURIComponent(sequence)}`;
}

export class RealtimeClient {
  private readonly options: RealtimeClientOptions;
  private socket?: WebSocket;
  private stopped = true;
  private reconnectAttempt = 0;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private pollTimer?: ReturnType<typeof setInterval>;
  private sequence: number;

  constructor(options: RealtimeClientOptions) {
    this.options = options;
    this.sequence = options.lastSequence ?? 0;
  }

  start() {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
  }

  stop() {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.socket?.close(1000, "Client stopped");
    this.emitState("stopped");
  }

  getLastSequence() {
    return this.sequence;
  }

  private connect() {
    if (this.stopped) return;
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      this.emitState("offline");
      this.startPolling();
      this.scheduleReconnect();
      return;
    }
    this.emitState("connecting");
    const factory = this.options.webSocketFactory ?? ((url: string) => new WebSocket(url));
    this.socket = factory(withLastSequence(this.options.url, this.sequence));
    this.socket.addEventListener("open", () => {
      this.reconnectAttempt = 0;
      this.stopPolling();
      this.emitState("live");
    });
    this.socket.addEventListener("message", (message) => this.consume(message.data));
    this.socket.addEventListener("close", (event) => {
      if (this.stopped) return;
      if (event.code === 4401 || event.code === 4403) {
        this.emitState("stopped");
        this.stopped = true;
        return;
      }
      this.startPolling();
      this.scheduleReconnect();
    });
    this.socket.addEventListener("error", () => this.socket?.close());
  }

  private consume(raw: string | ArrayBuffer | Blob) {
    if (typeof raw !== "string") return;
    let message: RealtimeMessage;
    try {
      message = JSON.parse(raw) as RealtimeMessage;
    } catch {
      return;
    }
    if (message.type === "system.heartbeat") {
      this.socket?.send(JSON.stringify({ type: "system.pong" }));
      return;
    }
    const transition = nextSequence(this.sequence, message.sequence);
    if (transition.action === "duplicate") return;
    if (transition.action === "gap") {
      const expected = this.sequence + 1;
      this.sequence = transition.sequence;
      void Promise.resolve(this.options.onGap?.(expected, message.sequence)).finally(() => this.options.onEvent(message));
      this.startPolling();
      this.socket?.close(4000, "Sequence gap; refreshing snapshot");
      return;
    }
    this.sequence = transition.sequence;
    this.options.onEvent(message);
  }

  private scheduleReconnect() {
    if (this.stopped || this.reconnectTimer) return;
    const delay = reconnectDelay(
      this.reconnectAttempt++,
      this.options.minReconnectMs,
      this.options.maxReconnectMs,
    );
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      this.connect();
    }, delay);
  }

  private startPolling() {
    if (!this.options.pollSnapshot || this.pollTimer) {
      if (this.options.pollSnapshot) this.emitState("polling");
      return;
    }
    this.emitState("polling");
    void this.options.pollSnapshot();
    this.pollTimer = setInterval(() => void this.options.pollSnapshot?.(), 5000);
  }

  private stopPolling() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = undefined;
  }

  private emitState(state: RealtimeState) {
    this.options.onStateChange?.(state);
  }
}

export function staffRealtimeUrl(input: { tenantId: string; locationId: string; role: StaffRole; grant: string }) {
  const base = (process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/api/v1").replace(/\/$/, "");
  return `${base}/ws/staff/tenants/${encodeURIComponent(input.tenantId)}/locations/${encodeURIComponent(input.locationId)}?token=${encodeURIComponent(input.grant)}&role=${encodeURIComponent(input.role)}`;
}

export function publicOrderRealtimeUrl(input: { orderId: string; accessToken: string }) {
  const base = (process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/api/v1").replace(/\/$/, "");
  return `${base}/ws/public/orders/${encodeURIComponent(input.orderId)}?access_token=${encodeURIComponent(input.accessToken)}`;
}

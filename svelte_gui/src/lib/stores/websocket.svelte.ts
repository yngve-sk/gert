// Define the shape of the status events we expect to receive
export interface RealizationStatus {
	iteration: number;
	realization_id: number;
	status: string;
	start_time?: string | null;
	end_time?: string | null;
}

export class ExecutionWebSocketStore {
	private ws: WebSocket | null = null;
	private url: string;
	private reconnectAttempts = 0;
	private maxReconnectAttempts = 5;
	private baseBackoffMs = 1000;
	private isIntentionallyClosed = false;

	// Reactive state using Svelte 5 runes
	statusEvents = $state<RealizationStatus[]>([]);
	isConnected = $state(false);
	error = $state<string | null>(null);

	constructor(
		experimentId: string,
		executionId: string,
		initialStatus: RealizationStatus[] = [],
	) {
		const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
		this.url = `${protocol}//${window.location.host}/api/experiments/${experimentId}/executions/${executionId}/events`;
		this.statusEvents = initialStatus;
	}

	connect() {
		this.isIntentionallyClosed = false;
		if (
			this.ws?.readyState === WebSocket.OPEN ||
			this.ws?.readyState === WebSocket.CONNECTING
		) {
			return;
		}

		this.ws = new WebSocket(this.url);

		this.ws.onopen = () => {
			this.isConnected = true;
			this.error = null;
			this.reconnectAttempts = 0;
		};

		this.ws.onmessage = (event) => {
			try {
				const data = JSON.parse(event.data);
				// The server sends the entire array of statuses every 1s if it changed
				if (Array.isArray(data)) {
					this.statusEvents = data;
				}
			} catch (e) {
				console.error("Failed to parse websocket message", e);
			}
		};

		this.ws.onclose = () => {
			this.isConnected = false;
			this.ws = null;

			if (!this.isIntentionallyClosed) {
				this.handleReconnect();
			}
		};

		this.ws.onerror = (_err) => {
			this.error = "WebSocket connection error";
			// onclose will be called after onerror, triggering the reconnect logic
		};
	}

	private handleReconnect() {
		if (this.reconnectAttempts >= this.maxReconnectAttempts) {
			this.error =
				"Maximum reconnection attempts reached. Please refresh the page.";
			return;
		}

		const backoff = this.baseBackoffMs * 2 ** this.reconnectAttempts;
		this.reconnectAttempts++;

		console.log(
			`Reconnecting in ${backoff}ms (Attempt ${this.reconnectAttempts})`,
		);
		setTimeout(() => this.connect(), backoff);
	}

	disconnect() {
		this.isIntentionallyClosed = true;
		if (this.ws) {
			this.ws.close();
			this.ws = null;
		}
		this.isConnected = false;
	}
}

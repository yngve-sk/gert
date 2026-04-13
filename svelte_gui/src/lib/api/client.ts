export interface Experiment {
	id: string;
	name: string;
}

export interface ExperimentConfig {
	name: string;
	base_working_directory: string;
	updates?: any[];
	forward_model_steps?: any[];
	observations?: any[];
}

export interface ExecutionState {
	experiment_id: string;
	execution_id: string;
	status: string;
	current_iteration: number;
	active_job_ids: string[];
	active_realizations: number[];
	completed_realizations: number[];
	failed_realizations: number[];
	error: string | null;
}

export interface ObservationSummary {
	average_absolute_residual: number;
	average_misfit: number;
	average_absolute_misfit: number;
	// details omitted for brevity in UI
}

export interface SystemInfo {
	version: string;
	server_url: string;
	start_time: string;
	num_experiments: number;
	num_active_executions: number;
	total_events: number;
}

export interface UpdateMetadata {
	status: string;
	algorithm_name: string;
	configuration: Record<string, any>;
	metrics: Record<string, any>;
	error?: string | null;
	duration_seconds?: number | null;
	start_time?: string | null;
	end_time?: string | null;
}

/**
 * Fetch all experiments from the API.
 * Thanks to the Vite proxy, we can use the relative path '/experiments'
 */
export async function listExperiments(
	fetchInstance: typeof fetch = fetch,
): Promise<Experiment[]> {
	const response = await fetchInstance("/experiments");
	if (!response.ok) {
		throw new Error(`Failed to fetch experiments: ${response.statusText}`);
	}
	return response.json();
}

/**
 * Fetch general system information.
 */
export async function getSystemInfo(
	fetchInstance: typeof fetch = fetch,
): Promise<SystemInfo> {
	const response = await fetchInstance("/system/info");
	if (!response.ok) {
		throw new Error(`Failed to fetch system info: ${response.statusText}`);
	}
	return response.json();
}

/**
 * Fetch the configuration for a specific experiment to get its name and metadata.
 */
export async function getExperimentConfig(
	experimentId: string,
	fetchInstance: typeof fetch = fetch,
): Promise<ExperimentConfig> {
	const response = await fetchInstance(`/experiments/${experimentId}/config`);
	if (!response.ok) {
		throw new Error(
			`Failed to fetch experiment config: ${response.statusText}`,
		);
	}
	return response.json();
}

/**
 * Fetch all executions for a specific experiment.
 */
export async function listExecutions(
	experimentId: string,
	fetchInstance: typeof fetch = fetch,
): Promise<ExecutionState[]> {
	const response = await fetchInstance(
		`/experiments/${experimentId}/executions`,
	);
	if (!response.ok) {
		throw new Error(`Failed to fetch executions: ${response.statusText}`);
	}
	return response.json();
}

/**
 * Pause a running execution.
 */
export async function pauseExecution(
	experimentId: string,
	executionId: string,
	fetchInstance: typeof fetch = fetch,
	force = false,
): Promise<void> {
	const url = `/experiments/${experimentId}/executions/${executionId}/pause${force ? "?force=true" : ""}`;
	const response = await fetchInstance(url, {
		method: "POST",
	});
	if (!response.ok) {
		throw new Error(`Failed to pause execution: ${response.statusText}`);
	}
}

/**
 * Resume a paused execution.
 */
export async function resumeExecution(
	experimentId: string,
	executionId: string,
	fetchInstance: typeof fetch = fetch,
): Promise<void> {
	const response = await fetchInstance(
		`/experiments/${experimentId}/executions/${executionId}/resume`,
		{
			method: "POST",
		},
	);
	if (!response.ok) {
		throw new Error(`Failed to resume execution: ${response.statusText}`);
	}
}

/**
 * Fetch observation summary for a specific iteration.
 */
export async function getObservationSummary(
	experimentId: string,
	executionId: string,
	iteration: number,
	fetchInstance: typeof fetch = fetch,
): Promise<ObservationSummary | null> {
	const response = await fetchInstance(
		`/experiments/${experimentId}/executions/${executionId}/ensembles/${iteration}/observation_summary`,
	);
	if (response.status === 404) {
		return null;
	}
	if (!response.ok) {
		throw new Error(
			`Failed to fetch observation summary: ${response.statusText}`,
		);
	}
	return response.json();
}

/**
 * Get the URL to stream parameters for a specific iteration as Parquet.
 * SvelteKit's Vite proxy will forward this to the Python backend automatically.
 */
export function getParametersUrl(
	experimentId: string,
	executionId: string,
	iteration: number,
): string {
	return `/experiments/${experimentId}/executions/${executionId}/ensembles/${iteration}/parameters`;
}

/**
 * Fetch the status of all realizations for a specific execution.
 */
export async function getExecutionStatus(
	experimentId: string,
	executionId: string,
	fetchInstance: typeof fetch = fetch,
): Promise<any[]> {
	const response = await fetchInstance(
		`/experiments/${experimentId}/executions/${executionId}/status`,
	);
	if (!response.ok) {
		throw new Error(`Failed to fetch execution status: ${response.statusText}`);
	}
	return response.json();
}

export interface StepLogs {
	stdout: string;
	stderr: string;
}

/**
 * Fetch the metadata for a specific mathematical update step.
 */
export async function getUpdateMetadata(
	experimentId: string,
	executionId: string,
	iteration: number,
	fetchInstance: typeof fetch = fetch,
): Promise<UpdateMetadata> {
	const response = await fetchInstance(
		`/experiments/${experimentId}/executions/${executionId}/ensembles/${iteration}/update/metadata`,
	);
	if (!response.ok) {
		throw new Error(`Failed to fetch update metadata: ${response.statusText}`);
	}
	return response.json();
}

/**
 * Fetch logs for a specific forward model step.
 */
export async function getStepLogs(
	experimentId: string,
	executionId: string,
	iteration: number,
	realizationId: number,
	stepName: string,
	fetchInstance: typeof fetch = fetch,
): Promise<StepLogs> {
	const response = await fetchInstance(
		`/experiments/${experimentId}/executions/${executionId}/ensembles/${iteration}/realizations/${realizationId}/steps/${stepName}/logs`,
	);
	if (!response.ok) {
		throw new Error(`Failed to fetch step logs: ${response.statusText}`);
	}
	return response.json();
}

export async function fetchParquet(
	experimentId: string,
	executionId: string,
	iteration: number,
	dataType: "responses" | "parameters",
	fetchInstance: typeof fetch = fetch,
): Promise<any[]> {
	const response = await fetchInstance(
		`/experiments/${experimentId}/executions/${executionId}/ensembles/${iteration}/${dataType}`,
		{
			headers: {
				Accept: "application/json",
			},
		}
	);
	if (!response.ok) {
		throw new Error(`Failed to fetch ${dataType}: ${response.statusText}`);
	}

	const text = await response.text();
	const lines = text.trim().split("\n");
	return lines.map(l => JSON.parse(l));
}

/**
 * Start a new execution for an experiment.
 */
export async function startExperiment(
	experimentId: string,
	fetchInstance: typeof fetch = fetch,
): Promise<{ execution_id: string; iteration: number }> {
	const response = await fetchInstance(`/experiments/${experimentId}/start`, {
		method: "POST",
	});
	if (!response.ok) {
		throw new Error(`Failed to start experiment: ${response.statusText}`);
	}
	return response.json();
}

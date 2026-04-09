export interface Experiment {
	id: string;
	name: string;
}

export interface ExperimentConfig {
	name: string;
	base_working_directory: string;
	// Omitted other fields for brevity as we mainly need the name right now
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
): Promise<void> {
	const response = await fetchInstance(
		`/experiments/${experimentId}/executions/${executionId}/pause`,
		{
			method: "POST",
		},
	);
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

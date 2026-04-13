import { getExecutionStatus, getExperimentConfig, listExecutions } from "$lib/api/client";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params, fetch, url }) => {
	const experimentId = params.id;
	const executionId = params.execution_id;

	try {
		let apiFetch = typeof window !== "undefined" ? window.fetch : fetch;
		const isFastApiMount = url.pathname.includes("/_app/");

		if (isFastApiMount && typeof window !== "undefined") {
			apiFetch = (input: RequestInfo | URL, init?: RequestInit) => {
				const targetUrl = new URL(input.toString(), url.origin);
				return window.fetch(targetUrl, init);
			};
		}

		// Fetch config, execution state, and initial status list
		const [config, executions, initialStatus] = await Promise.all([
			getExperimentConfig(experimentId, apiFetch),
			listExecutions(experimentId, apiFetch),
			getExecutionStatus(experimentId, executionId, apiFetch),
		]);

		const execution = executions.find(e => e.execution_id === executionId) || null;

		return {
			experimentId,
			executionId,
			config,
			execution,
			initialStatus,
		};
	} catch (error) {
		console.error(`Failed to load data for execution ${executionId}:`, error);
		return {
			experimentId,
			executionId,
			config: null,
			execution: null,
			initialStatus: [],
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
};

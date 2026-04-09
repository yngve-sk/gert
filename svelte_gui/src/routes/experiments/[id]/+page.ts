import {
	getExperimentConfig,
	getObservationSummary,
	listExecutions,
} from "$lib/api/client";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params, fetch, url }) => {
	const experimentId = params.id;

	try {
		const isFastApiMount = url.pathname.includes("/_app/");

		let apiFetch = fetch;
		if (isFastApiMount) {
			apiFetch = (input: RequestInfo | URL, init?: RequestInit) => {
				const targetUrl = new URL(input.toString(), url.origin);
				return fetch(targetUrl, init);
			};
		}

		// Fetch config and executions concurrently
		const [config, executions] = await Promise.all([
			getExperimentConfig(experimentId, apiFetch),
			listExecutions(experimentId, apiFetch),
		]);

		// To fulfill M10 (Pluggable Plotting), we need observation summary data for convergence plots.
		// We'll pick the most recent execution, or you could do it for all executions depending on UI design.
		// Here, we grab it for the latest execution to power a "Latest Convergence" chart on the overview.
		const latestExecution = executions.length > 0 ? executions[0] : null;

		const summaries: {
			iteration: number;
			data: import("$lib/api/client").ObservationSummary;
		}[] = [];
		if (latestExecution) {
			const iterationsToFetch = Array.from(
				{ length: latestExecution.current_iteration + 1 },
				(_, i) => i,
			);

			const summaryResults = await Promise.all(
				iterationsToFetch.map(async (iter) => {
					try {
						const data = await getObservationSummary(
							experimentId,
							latestExecution.execution_id,
							iter,
							apiFetch,
						);
						return { iteration: iter, data };
					} catch (_e) {
						return { iteration: iter, data: null };
					}
				}),
			);

			for (const res of summaryResults) {
				if (res.data) {
					summaries.push({ iteration: res.iteration, data: res.data });
				}
			}
		}

		return {
			experimentId,
			config,
			executions,
			latestExecutionId: latestExecution?.execution_id || null,
			summaries,
		};
	} catch (error) {
		console.error(`Failed to load data for experiment ${experimentId}:`, error);
		return {
			experimentId,
			config: null,
			executions: [],
			latestExecutionId: null,
			summaries: [],
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
};

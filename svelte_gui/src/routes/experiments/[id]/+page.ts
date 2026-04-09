import { getExperimentConfig, listExecutions } from "$lib/api/client";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params, fetch }) => {
	const experimentId = params.id;

	try {
		// Fetch config and executions concurrently
		const [config, executions] = await Promise.all([
			getExperimentConfig(experimentId, fetch),
			listExecutions(experimentId, fetch),
		]);

		return {
			experimentId,
			config,
			executions,
		};
	} catch (error) {
		console.error(`Failed to load data for experiment ${experimentId}:`, error);
		return {
			experimentId,
			config: null,
			executions: [],
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
};

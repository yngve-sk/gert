import { getStepLogs } from "$lib/api/client";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params, fetch, url }) => {
	const experimentId = params.id;
	const executionId = params.execution_id;
	const iteration = parseInt(params.iter, 10);
	const realizationId = parseInt(params.real_id, 10);
	const stepName = params.step_name;

	try {
		let apiFetch = typeof window !== "undefined" ? window.fetch : fetch;
		const isFastApiMount = url.pathname.includes("/_app/");

		if (isFastApiMount && typeof window !== "undefined") {
			apiFetch = (input: RequestInfo | URL, init?: RequestInit) => {
				const targetUrl = new URL(input.toString(), url.origin);
				return window.fetch(targetUrl, init);
			};
		}

		const stepLogs = await getStepLogs(
			experimentId,
			executionId,
			iteration,
			realizationId,
			stepName,
			apiFetch
		);

		return {
			experimentId,
			executionId,
			iteration,
			realizationId,
			stepName,
			logs: stepLogs,
		};
	} catch (error) {
		console.error(`Failed to load step logs for ${stepName}:`, error);
		return {
			experimentId,
			executionId,
			iteration,
			realizationId,
			stepName,
			logs: null,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
};

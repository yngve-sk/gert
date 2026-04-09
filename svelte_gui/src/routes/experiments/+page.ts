import { listExperiments } from "$lib/api/client";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ fetch }) => {
	try {
		const experiments = await listExperiments(fetch);
		return {
			experiments,
		};
	} catch (error) {
		console.error("Failed to load experiments:", error);
		// Return empty list on failure rather than crashing the route completely
		// This handles the case where the Python server isn't running yet.
		return {
			experiments: [],
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
};

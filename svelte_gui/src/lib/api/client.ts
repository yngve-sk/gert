export interface Experiment {
	id: string;
	name: string;
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

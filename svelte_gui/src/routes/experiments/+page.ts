import { listExperiments } from "$lib/api/client";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ fetch, url }) => {
	try {
		// In the browser, always use the native fetch to bypass SvelteKit's SPA router
		// intercepting API calls and incorrectly returning the index.html fallback.
		let apiFetch = typeof window !== "undefined" ? window.fetch : fetch;

		// When mounted under /_app/ in FastAPI, standard fetch() doesn't auto-resolve
		// base paths in SPA mode the way it does under Vite. We force absolute routing logic.
		const isFastApiMount = url.pathname.includes("/_app/");

		if (isFastApiMount && typeof window !== "undefined") {
			apiFetch = (input: RequestInfo | URL, init?: RequestInit) => {
				const targetUrl = new URL(input.toString(), url.origin);
				return window.fetch(targetUrl, init);
			};
		}

		const experiments = await listExperiments(apiFetch);
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

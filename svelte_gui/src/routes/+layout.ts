import { getSystemInfo } from "$lib/api/client";
import type { LayoutLoad } from "./$types";

export const prerender = false;
export const ssr = false;

export const load: LayoutLoad = async ({ fetch, url }) => {
	try {
		let apiFetch = typeof window !== "undefined" ? window.fetch : fetch;
		const isFastApiMount = url.pathname.includes("/_app/");

		if (isFastApiMount && typeof window !== "undefined") {
			apiFetch = (input: RequestInfo | URL, init?: RequestInit) => {
				const targetUrl = new URL(input.toString(), url.origin);
				return window.fetch(targetUrl, init);
			};
		}

		const systemInfo = await getSystemInfo(apiFetch);
		return { systemInfo };
	} catch (error) {
		console.error("Failed to load system info:", error);
		return {
			systemInfo: null,
		};
	}
};

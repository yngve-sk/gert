export function formatMetric(v: number | null | undefined): string {
	if (v == null || isNaN(v)) return "";
	if (v === 0) return "0";

	const abs = Math.abs(v);
	if (abs >= 1000) {
		const suffixes = ["", "K", "M", "B", "T", "P"];
		const suffixIndex = Math.min(Math.floor(Math.log10(abs) / 3), suffixes.length - 1);
		const scaled = v / Math.pow(10, suffixIndex * 3);
		return `${Number(scaled.toFixed(2))}${suffixes[suffixIndex]}`;
	}

	if (abs < 0.01) {
		return v.toExponential(2);
	}

	return Number(v.toFixed(3)).toString();
}

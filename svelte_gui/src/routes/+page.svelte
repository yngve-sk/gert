<!-- Dummy nesting to verify M2 optical nesting -->
<div class="flex flex-col gap-4 max-w-4xl">

	<!-- L2: Container -->
	<section class="bg-surface-800 border border-surface-700 rounded-lg overflow-hidden shadow-lg">
		<header class="p-3 border-b border-surface-700 bg-surface-800 flex justify-between items-center">
			<h2 class="text-sm font-bold text-surface-100">Global Convergence Status</h2>
			<span class="badge bg-success-500 text-black text-xs font-bold px-2 py-0.5 rounded">CONVERGED</span>
		</header>

		<div class="p-4 flex flex-col gap-4">
			<p class="text-xs text-surface-300">
				Optical nesting verification for the M2 Industrial Dark Theme.
				This L2 container holds L3 insets below.
			</p>

			<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
				<!-- L3: Inset (Data Card) -->
				<div class="bg-surface-700 border border-surface-600 rounded p-3">
					<h4 class="text-[10px] uppercase tracking-widest text-surface-400 mb-2">Data Misfit</h4>
					<div class="flex items-baseline justify-between">
						<span class="text-xs text-surface-300">Sum(abs)</span>
						<span class="text-lg text-primary-400 font-mono">1.24e-03</span>
					</div>
					<div class="flex items-baseline justify-between mt-1">
						<span class="text-xs text-surface-300">Variance</span>
						<span class="text-lg text-secondary-400 font-mono">0.0045</span>
					</div>
				</div>

				<!-- L3: Inset (Parameter Card) -->
				<div class="bg-surface-700 border border-surface-600 rounded p-3">
					<h4 class="text-[10px] uppercase tracking-widest text-surface-400 mb-2">Key Multiplier</h4>
					<div class="flex items-baseline justify-between">
						<span class="text-xs text-surface-300">FAULT_F1</span>
						<span class="text-lg text-tertiary-400 font-mono">0.892</span>
					</div>
					<div class="flex items-baseline justify-between mt-1">
						<span class="text-xs text-surface-300">FAULT_F2</span>
						<span class="text-lg text-surface-100 font-mono">1.045</span>
					</div>
				</div>
			</div>
		</div>
	</section>

	<!-- Another L2 Container -->
	<section class="bg-surface-800 border border-surface-700 rounded-lg overflow-hidden shadow-lg">
		<header class="p-3 border-b border-surface-700 bg-surface-800">
			<h2 class="text-sm font-bold text-surface-100">Live Terminal (Dummy)</h2>
		</header>
		<!-- L3 Inset simulating a terminal window -->
		<div class="bg-surface-950 p-3 h-32 overflow-y-auto font-mono text-xs text-surface-300 leading-tight">
			<div class="text-surface-500">[14:32:01] <span class="text-info-500">INFO</span> Starting EnKF iteration 4</div>
			<div class="text-surface-500">[14:32:02] <span class="text-info-500">INFO</span> Assimilating 450 observations...</div>
			<div class="text-surface-500">[14:32:05] <span class="text-success-500">SUCCESS</span> State update completed in 3.1s.</div>
			<div class="text-surface-500 mt-2 animate-pulse">_</div>
		</div>
	</section>

</div>

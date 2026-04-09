import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
		runes: ({ filename }) => filename.split(/[/\\]/).includes('node_modules') ? undefined : true
	},
	kit: {
		adapter: adapter({
			pages: '../src/gert/server/static',
			assets: '../src/gert/server/static',
			fallback: 'index.html',
			precompress: false,
			strict: true
		}),
		prerender: {
		        entries: ['*'],
		        handleHttpError: 'ignore',
		        handleMissingId: 'ignore',
		        handleUnseenRoutes: 'ignore'
		}	}
};

export default config;

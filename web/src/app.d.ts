// Ver https://svelte.dev/docs/kit/types#app.d.ts
declare global {
	namespace App {
		interface Error { code?: string }
		// interface Locals {}
		// interface PageData {}
		interface PageState { marketTab?: string; leagueFilters?: string }
		// interface Platform {}
	}
}

export {};

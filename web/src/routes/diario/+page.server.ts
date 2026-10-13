import { journal } from '$lib/server/queries';
import { journalSummary } from '$lib/journal';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const j = await journal();
	return { ...j, summary: journalSummary(j.entries) };
};

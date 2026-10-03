/** Shared "is a trailer job running?" signal for the topbar lamp (trailer jobs run one at a time). */
import { api } from '$lib/api/client';
import { unwrapLoose, type ApiJob } from '$lib/jobs';
import { JobActivityStore } from '$lib/stores/syncActivity.svelte';

export const trailerActivity = new JobActivityStore('trailer', async () => {
	const { job } = await unwrapLoose<{ job: ApiJob | null }>(
		api.GET('/api/v2/trailers/jobs/current')
	);
	return job?.is_active ? [job] : [];
});

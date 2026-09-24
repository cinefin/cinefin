import { redirect } from '@sveltejs/kit';
import { base } from '$app/paths';
import type { PageLoad } from './$types';

export const load: PageLoad = ({ params }) => {
	redirect(302, `${base}/library?movie=${encodeURIComponent(params.id)}`);
};

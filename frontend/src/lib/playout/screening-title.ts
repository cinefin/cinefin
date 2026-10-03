/** How a screening is named: a programme of one film called after it is just the film. */

export interface Titled {
	title: string;
}

export interface ScreeningTitle<F extends Titled> {
	/** The name to show large. */
	title: string;
	/** The film when the programme is named after it: show its facts, not its name again. */
	film: F | null;
	/** The films to list under the title (none when `film` is set). */
	films: F[];
}

// "Coral Skies (2021)", "coral skies" and "Coral Skies!" all name the same film.
const key = (name: string) =>
	name
		.toLowerCase()
		.replace(/\(?\b(19|20)\d{2}\)?\s*$/, '')
		.replace(/[^\p{L}\p{N}]+/gu, '');

export function screeningTitle<F extends Titled>(programme: string, films: F[]): ScreeningTitle<F> {
	if (films.length === 1 && key(films[0].title) === key(programme))
		return { title: films[0].title, film: films[0], films: [] };
	return { title: programme || films[0]?.title || '', film: null, films };
}

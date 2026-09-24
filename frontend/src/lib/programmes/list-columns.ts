// Column widths shared by the programme list's flex rows and the header strip:
// they only line up if header and every row use the SAME classes.

export const CHECK_COL = 'flex w-4 shrink-0 items-center self-center';

// CONSTANT width whatever the bill: up to three thumbs fan into the same cell.
export const POSTER_COL = 'w-20 shrink-0';

export const NUM_CELL = 'w-20 shrink-0 text-right md:w-auto md:min-w-20 md:flex-1 md:shrink';

export const NUM_CELL_NARROW = 'hidden md:block md:min-w-12 md:flex-[0.6] md:text-right';

export const NUM_CELL_WIDE = 'hidden lg:block lg:min-w-20 lg:flex-1 lg:text-right';

export const NUM_GROUP =
	'flex shrink-0 items-baseline gap-6 md:min-w-0 md:flex-[4] md:shrink md:gap-4';

export const NAME_COL = 'flex min-w-0 flex-1 items-baseline gap-2 md:flex-[3]';

// Fixed width reserved even while the actions are hidden, so hover reflows nothing.
export const ACTION_COL = 'w-44 shrink-0';

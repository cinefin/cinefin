// The button look, shared by Button and Menu's trigger.
export type ButtonVariant = 'primary' | 'default' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

const BASE =
	'inline-flex items-center justify-center gap-1.5 rounded-md font-medium select-none ' +
	'transition-colors active:brightness-90 disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap';
const SIZES: Record<ButtonSize, string> = {
	sm: 'h-7 px-2.5 text-xs',
	md: 'h-8 px-3.5 text-[0.84375rem]',
	lg: 'h-11 px-5 text-[0.9375rem]'
};
const VARIANTS: Record<ButtonVariant, string> = {
	primary: 'bg-accent text-on-accent hover:bg-accent-hover',
	default:
		'bg-surface-2 text-text border border-border-strong hover:bg-surface-3 active:bg-shell active:brightness-100',
	ghost: 'text-muted hover:text-text hover:bg-surface-2',
	danger:
		'bg-transparent text-danger border border-border-strong hover:bg-danger/10 hover:border-danger/60'
};

export function buttonClasses(variant: ButtonVariant, size: ButtonSize): string {
	return `${BASE} ${SIZES[size]} ${VARIANTS[variant]}`;
}

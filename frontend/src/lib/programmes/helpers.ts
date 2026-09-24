export function formatDuration(seconds: number | null | undefined): string {
	if (!seconds || seconds <= 0) return '-';
	const total = Math.round(seconds);
	const h = Math.floor(total / 3600);
	const m = Math.floor((total % 3600) / 60);
	const s = total % 60;
	if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
	if (m > 0) return s > 0 ? `${m}m ${s}s` : `${m}m`;
	return `${s}s`;
}

export function formatLongRuntime(totalMinutes: number): string {
	const total = Math.floor(totalMinutes);
	if (total >= 60) {
		const hours = Math.floor(total / 60);
		const minutes = total % 60;
		const hoursText = `${hours} hour${hours !== 1 ? 's' : ''}`;
		return minutes > 0 ? `${hoursText} ${minutes} minute${minutes !== 1 ? 's' : ''}` : hoursText;
	}
	return `${total} minute${total !== 1 ? 's' : ''}`;
}

export function formatFileSize(bytes: number): string {
	if (!bytes) return '0 Bytes';
	const k = 1024;
	const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
	const i = Math.floor(Math.log(bytes) / Math.log(k));
	return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

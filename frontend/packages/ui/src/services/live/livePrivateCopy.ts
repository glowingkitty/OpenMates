/**
 * Presents private copies prepared by the live core after access is lost.
 * Text stays in this page until downloaded or the admitted Worker port closes.
 */
import { get } from 'svelte/store';
import { text } from '../../i18n/translations';
import { notificationStore } from '../../stores/notificationStore';
import type { LiveItemKind } from './liveItemTypes';

interface PrivateCopy { copyId: string; kind: LiveItemKind; text: string }

const FILENAMES: Record<LiveItemKind, string> = {
	doc: 'Recovered document.txt',
	sheet: 'Recovered spreadsheet.md',
	deck: 'Recovered slides.txt',
	code: 'Recovered code.txt'
};

export function createLivePrivateCopyNotice(isCurrent: () => boolean) {
	const copies = new Map<string, PrivateCopy>();
	const downloaded = new Set<string>();
	let notice: string | undefined;

	function dismiss() {
		if (notice) notificationStore.removeNotification(notice);
		notice = undefined;
	}

	function clear() {
		copies.clear();
		downloaded.clear();
		dismiss();
	}

	function download() {
		if (!isCurrent()) { clear(); return; }
		const copy = copies.values().next().value;
		if (!copy) return;
		const url = URL.createObjectURL(new Blob([copy.text], { type: 'text/plain;charset=utf-8' }));
		const link = document.createElement('a');
		link.href = url;
		link.download = FILENAMES[copy.kind];
		document.body.appendChild(link);
		link.click();
		link.remove();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
		downloaded.add(copy.copyId);
		copies.delete(copy.copyId);
		if (!copies.size) dismiss();
	}

	function offer(payload: unknown) {
		if (!isCurrent() || !payload || typeof payload !== 'object') return;
		const value = payload as Partial<PrivateCopy>;
		if (typeof value.copyId !== 'string' || downloaded.has(value.copyId) || typeof value.text !== 'string' ||
			!value.kind || !Object.hasOwn(FILENAMES, value.kind)) return;
		copies.set(value.copyId, { copyId: value.copyId, kind: value.kind, text: value.text });
		notice ??= notificationStore.addNotificationWithOptions('warning', {
			message: get(text)('embed_user_edits.live_private_copy_ready'),
			actionLabel: get(text)('embed_user_edits.live_private_copy_download'),
			duration: 0,
			dismissible: false,
			keepOnAction: true,
			onAction: download
		});
	}

	return { offer, clear };
}

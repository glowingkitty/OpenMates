/**
 * Literal transcription of the flag-off TypeScript indicator decisions of
 * ActiveChat.svelte (`typingIndicatorLines`, `typingIndicatorStatusType`) and
 * chats/Chat.svelte (`typingIndicatorInTitleView`), with each `$text(key)` call
 * replaced by the token it would localise. It is the TS side of the parity
 * vectors: keep it in step with those Svelte blocks.
 */
import type { IndicatorState } from '../../chatState/transitionInput';
import type { IndicatorLine } from '../../chatState/transitionProtocol';

const FLAGS: Record<string, string> = { EU: '🇪🇺', US: '🇺🇸', APAC: '🌏', global: '🌐', Local: '🏠' };

export function referenceComposer(s: IndicatorState): { lines: IndicatorLine[]; statusType: 'typing' | 'processing' | null } {
	const typing = s.typing;
	const matches = typing?.isTyping === true && typing.chatId === s.chatId && typing.userMessageId === s.turn?.userMessageId
		&& s.turn?.chatId === s.chatId && s.activeTaskMatches;
	const literal = (text: string): IndicatorLine => ({ k: 'literal', text });
	const lines = ((): IndicatorLine[] => {
		if (s.projectKey !== null) return [{ k: 'key', key: `embeds.projects.progress.${s.projectKey}` }];
		if (s.terminal) return [];
		if (s.turn && s.turn.chatId === s.chatId && !matches) {
			return [{ k: 'key', key: s.turn.explicitMateCategory ? 'enter_message.status.selecting_model' : 'enter_message.status.selecting_mate_and_model' }];
		}
		if (s.phase !== null && s.phase.phase !== 'compressing' && !matches) return s.anonymous ? s.phase.statusLines.map(literal) : [];
		if (s.phase?.phase === 'compressing') return s.phase.statusLines.map(literal);
		if (typing?.isTyping && typing.chatId === s.chatId && typing.category && (!s.turn || matches)) {
			const out: IndicatorLine[] = [{ k: 'mate', category: typing.category, thinking: s.reasoning }];
			const modelName = typing.modelName || '';
			const providerName = typing.providerName || '';
			const serverRegion = typing.serverRegion || '';
			if (modelName && s.displayModelName) out.push(literal(`Powered by ${s.displayModelName}`));
			if (providerName) {
				const flag = serverRegion ? (FLAGS[serverRegion] ?? '') : '';
				out.push(literal(flag ? `via ${providerName} ${flag}` : `via ${providerName}`));
			}
			return out;
		}
		return [];
	})();
	const statusType = ((): 'typing' | 'processing' | null => {
		if (s.projectKey !== null) return 'processing';
		if (s.terminal) return null;
		if (s.turn && s.turn.chatId === s.chatId) return matches ? 'typing' : 'processing';
		if (s.phase !== null && s.phase.phase !== 'compressing') return s.anonymous ? 'typing' : null;
		if (s.phase?.phase === 'compressing') return 'typing';
		if (typing?.isTyping && typing.chatId === s.chatId) return 'typing';
		return null;
	})();
	return { lines, statusType };
}

export function referenceTitle(typing: { isTyping: boolean; category: string | null } | null, skill: { appId: string; skillId: string } | null, reasoning: boolean): IndicatorLine | null {
	if (typing?.isTyping && typing.category) {
		if (skill) return { k: 'skill', appId: skill.appId, skillId: skill.skillId };
		return { k: 'mate', category: typing.category, thinking: reasoning };
	}
	return null;
}

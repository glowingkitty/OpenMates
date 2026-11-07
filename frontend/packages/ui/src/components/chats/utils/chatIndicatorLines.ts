/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) typing/processing indicator support for
 * ActiveChat.svelte and chats/Chat.svelte: the Rust `chatState` unit decides
 * which lines show (packages/openmates-rust/src/web_chat_state/indicators.rs);
 * this module only localises the answer, reactively, on the page.
 */
import type { IndicatorLine } from '../../../services/rustCore/chatState/transitionProtocol';

type Translate = (key: string) => string;

/** Localised text of one Rust indicator line (`$text` is passed in so the caller's store subscription tracks locale changes). */
export function localizeIndicatorLine(line: IndicatorLine, t: Translate): string {
	switch (line.k) {
		case 'key': return t(line.key);
		case 'literal': return line.text;
		case 'mate': return t(line.thinking ? 'enter_message.is_thinking' : 'enter_message.is_typing').replace('{mate}', t(`mates.${line.category}`));
		case 'skill': return t('enter_message.using_skill').replace('{skill}', t(`app_skills.${line.appId}.${line.skillId}`));
	}
}

/**
 * Static allowlist of namespace installers for the shared Rust core Worker.
 *
 * S0 registers no unit: each unit adds exactly one line here when its installer
 * is extracted from its old dedicated `*.worker.ts` entry (which is then deleted).
 * A namespace without an installer is refused as `unit_unavailable`.
 */
import type { UnitInstallers } from '@openmates/ui/src/services/rustCore/host/sharedWorkerProtocol';
import { installCoreUnit } from './coreUnit';
import { installCryptoUnit } from '@openmates/ui/src/services/rustCore/crypto/cryptoUnitInstaller';

export const SHARED_UNIT_INSTALLERS: UnitInstallers = Object.freeze({
	core: installCoreUnit,
	crypto: installCryptoUnit,
	auth: (context) => import('@openmates/ui/src/services/rustCore/auth/authUnit').then((unit) => unit.installAuthUnit(context)),
	apps: (context) => import('@openmates/ui/src/services/rustCore/apps/appsUnit').then((unit) => unit.installAppsUnit(context)),
	embedData: (context) => import('@openmates/ui/src/services/rustCore/embeds/embedDataUnit').then((unit) => unit.installEmbedDataUnit(context)),
	embedWrite: (context) => import('@openmates/ui/src/services/rustCore/embeds/embedWriteUnit').then((unit) => unit.installEmbedWriteUnit(context)),
	search: (context) => import('@openmates/ui/src/services/rustCore/search/searchUnit').then((unit) => unit.installSearchUnit(context)),
	transfer: (context) => import('@openmates/ui/src/services/rustCore/transfer/transferUnit').then((unit) => unit.installTransferUnit(context)),
	sync: (context) => import('@openmates/ui/src/services/rustCore/sync/syncUnit').then((unit) => unit.installSyncUnit(context)),
	ws: (context) => import('@openmates/ui/src/services/rustCore/ws/wsUnit').then((unit) => unit.installWsUnit(context)),
	drafts: (context) => import('@openmates/ui/src/services/rustCore/drafts/draftsUnit').then((unit) => unit.installDraftsUnit(context)),
	parse: (context) => import('@openmates/ui/src/services/rustCore/parse/parseUnit').then((unit) => unit.installParseUnit(context)),
	chatState: (context) => import('@openmates/ui/src/services/rustCore/chatState/chatListUnit').then((unit) => unit.installChatStateUnit(context)),
	persist: (context) => import('@openmates/ui/src/services/rustCore/persist/persistUnit').then((unit) => unit.installPersistUnit(context)),
	sendPrep: (context) => import('@openmates/ui/src/services/rustCore/send/sendPrepUnit').then((unit) => unit.installSendPrepUnit(context)),
	settings: (context) => import('@openmates/ui/src/services/rustCore/settings/settingsUnit').then((unit) => unit.installSettingsUnit(context)),
	composer: (context) => import('@openmates/ui/src/services/rustCore/composer/composerUnit').then((unit) => unit.installComposerUnit(context)),
	deckDocument: (context) => import('@openmates/ui/src/services/rustCore/deckDocument/deckDocumentUnit').then((unit) => unit.installDeckDocumentUnit(context)),
});

/**
 * Loads every lazily imported unit module while the app is online, without installing
 * anything. A unit first opened offline (a draft saved after the connection dropped) then
 * finds its module already loaded instead of failing to fetch it. A module that cannot be
 * loaded now is fetched again, and its error reported, when the unit is opened.
 */
export function preloadSharedUnitModules(): void {
	const modules: Promise<unknown>[] = [
		import('@openmates/ui/src/services/rustCore/auth/authUnit'),
		import('@openmates/ui/src/services/rustCore/apps/appsUnit'),
		import('@openmates/ui/src/services/rustCore/embeds/embedDataUnit'),
		import('@openmates/ui/src/services/rustCore/embeds/embedWriteUnit'),
		import('@openmates/ui/src/services/rustCore/search/searchUnit'),
		import('@openmates/ui/src/services/rustCore/transfer/transferUnit'),
		import('@openmates/ui/src/services/rustCore/sync/syncUnit'),
		import('@openmates/ui/src/services/rustCore/ws/wsUnit'),
		import('@openmates/ui/src/services/rustCore/drafts/draftsUnit'),
		import('@openmates/ui/src/services/rustCore/parse/parseUnit'),
		import('@openmates/ui/src/services/rustCore/chatState/chatListUnit'),
		import('@openmates/ui/src/services/rustCore/persist/persistUnit'),
		import('@openmates/ui/src/services/rustCore/send/sendPrepUnit'),
		import('@openmates/ui/src/services/rustCore/settings/settingsUnit'),
		import('@openmates/ui/src/services/rustCore/composer/composerUnit'),
		import('@openmates/ui/src/services/rustCore/deckDocument/deckDocumentUnit'),
	];
	for (const module of modules) module.catch(() => undefined);
}

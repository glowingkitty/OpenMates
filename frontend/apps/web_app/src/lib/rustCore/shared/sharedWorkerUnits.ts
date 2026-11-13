/**
 * Static allowlist of namespace installers for the shared Rust core Worker.
 *
 * Each unit adds exactly one import and one line here. A namespace without an
 * installer is refused as `unit_unavailable`.
 *
 * Every installer is imported statically, so the Worker is one module graph that
 * is complete when the Worker starts. Units were loaded with `import()` inside
 * the Worker before. In Safari 26 a unit first opened after startup then never
 * answered (every request ended in `unit_timeout`) while units opened earlier
 * kept answering. A static graph also keeps units available after the
 * connection drops.
 */
import type { UnitInstallers } from '@openmates/ui/src/services/rustCore/host/sharedWorkerProtocol';
import { installCoreUnit } from './coreUnit';
import { installCryptoUnit } from '@openmates/ui/src/services/rustCore/crypto/cryptoUnitInstaller';
import { installAuthUnit } from '@openmates/ui/src/services/rustCore/auth/authUnit';
import { installAppsUnit } from '@openmates/ui/src/services/rustCore/apps/appsUnit';
import { installEmbedDataUnit } from '@openmates/ui/src/services/rustCore/embeds/embedDataUnit';
import { installEmbedWriteGuestUnit, installEmbedWriteUnit } from '@openmates/ui/src/services/rustCore/embeds/embedWriteUnit';
import { installSearchUnit } from '@openmates/ui/src/services/rustCore/search/searchUnit';
import { installTransferUnit } from '@openmates/ui/src/services/rustCore/transfer/transferUnit';
import { installSyncUnit } from '@openmates/ui/src/services/rustCore/sync/syncUnit';
import { installWsUnit } from '@openmates/ui/src/services/rustCore/ws/wsUnit';
import { installDraftsUnit } from '@openmates/ui/src/services/rustCore/drafts/draftsUnit';
import { installParseUnit } from '@openmates/ui/src/services/rustCore/parse/parseUnit';
import { installChatStateUnit } from '@openmates/ui/src/services/rustCore/chatState/chatListUnit';
import { installPersistUnit } from '@openmates/ui/src/services/rustCore/persist/persistUnit';
import { installSendPrepUnit } from '@openmates/ui/src/services/rustCore/send/sendPrepUnit';
import { installSettingsUnit } from '@openmates/ui/src/services/rustCore/settings/settingsUnit';
import { installComposerUnit } from '@openmates/ui/src/services/rustCore/composer/composerUnit';
import { installDeckDocumentUnit } from '@openmates/ui/src/services/rustCore/deckDocument/deckDocumentUnit';
import { installEmbedEditUnit } from '@openmates/ui/src/services/rustCore/embeds/embedEditUnit';

export const SHARED_UNIT_INSTALLERS: UnitInstallers = Object.freeze({
	core: installCoreUnit,
	crypto: installCryptoUnit,
	auth: installAuthUnit,
	apps: installAppsUnit,
	embedData: installEmbedDataUnit,
	embedWrite: installEmbedWriteUnit,
	embedWriteGuest: installEmbedWriteGuestUnit,
	search: installSearchUnit,
	transfer: installTransferUnit,
	sync: installSyncUnit,
	ws: installWsUnit,
	drafts: installDraftsUnit,
	parse: installParseUnit,
	chatState: installChatStateUnit,
	persist: installPersistUnit,
	sendPrep: installSendPrepUnit,
	settings: installSettingsUnit,
	composer: installComposerUnit,
	deckDocument: installDeckDocumentUnit,
	embedEdit: (context) => installEmbedEditUnit(context),
});

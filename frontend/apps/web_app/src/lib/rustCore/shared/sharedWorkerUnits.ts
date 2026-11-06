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
});

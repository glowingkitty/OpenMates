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
});

//! Source side of the server's remote-command job protocol (`remote_command_*`
//! frames): strict wire types and the portable-request check, shared core.
//!
//! Ports `frontend/packages/openmates-cli/src/remoteCommandSource.ts` (frame
//! validation, portable request verification); runtime and launch live in
//! sibling modules added by later lanes. Server contract:
//! `backend/core/api/app/schemas/remote_command_schemas.py`.
//! spec: specifications/features/app-skills/code-run code-run.remote.*

pub(crate) mod approval;
pub(crate) mod driver;
mod driver_job;
pub(crate) mod events;
pub(crate) mod launch;
pub(crate) mod portable;
pub(crate) mod transport;
pub(crate) mod wire;

#[cfg(test)]
mod approval_tests;
#[cfg(test)]
mod driver_tests;
#[cfg(test)]
mod events_tests;
#[cfg(test)]
mod launch_tests;
#[cfg(test)]
mod portable_tests;
#[cfg(test)]
mod transport_tests;
#[cfg(test)]
mod wire_tests;

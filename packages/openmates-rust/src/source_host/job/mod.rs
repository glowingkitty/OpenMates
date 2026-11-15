//! Source side of the server's remote-command job protocol (`remote_command_*`
//! frames): strict wire types and the portable-request check, shared core.
//!
//! Ports `frontend/packages/openmates-cli/src/remoteCommandSource.ts` (frame
//! validation, portable request verification); runtime and launch live in
//! sibling modules added by later lanes. Server contract:
//! `backend/core/api/app/schemas/remote_command_schemas.py`.
//! spec: specifications/features/app-skills/code-run code-run.remote.*

#![allow(dead_code)] // reason: consumed by the job driver added in a later lane

pub(crate) mod portable;
pub(crate) mod wire;

#[cfg(test)]
mod portable_tests;
#[cfg(test)]
mod wire_tests;

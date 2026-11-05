/** Typed encrypted Project source authoring; local filesystem approval is separate. */
export type SessionProjectSourceType='local_folder'|'local_git_repository'|'remote_folder'|'remote_git_repository';
export type SessionProjectSourceCapability='read'|'search'|'import'|'write_request'|'run_command';
export type SessionProjectSourceStatus='connected'|'offline'|'permission_required'|'revoked';
export type SessionProjectSourceCreate={sourceId:string;sourceType:SessionProjectSourceType;displayName:string;metadata:Record<string,unknown>;capabilities:SessionProjectSourceCapability[];status:SessionProjectSourceStatus;createdAt:number;updatedAt:number;lastIndexedAt?:number|null};
export type SessionProjectSourceCapabilitiesPatch={capabilities:SessionProjectSourceCapability[];updatedAt:number};
/** Rust DTO keys match existing Session work results; metadata keys remain data. */
export type SessionProjectSource={source_id:string;source_type:SessionProjectSourceType;display_name:string;metadata:Record<string,unknown>;capabilities:SessionProjectSourceCapability[];status:SessionProjectSourceStatus;created_at:number;updated_at:number;last_indexed_at:number|null};
export class OpenMatesProjectSourceAuthoringUnavailableError extends Error {
  readonly code='project_source_authoring_unavailable';
  readonly reason='PROJECT_SOURCE_AUTHORING_REQUIRES_COOKIE_SESSION';
  constructor(){super('PROJECT_SOURCE_AUTHORING_REQUIRES_COOKIE_SESSION');this.name='OpenMatesProjectSourceAuthoringUnavailableError';}
}

/** Canonical resolved ID plus raw rows with only decoded display_name added. */
export type SessionProjectSourcesDecodedNames={project_id:string;sources:unknown[]};

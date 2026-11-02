/** Optional capture from deployed stores for ordinary retention composition.
 * This derives the current account/session; a JSON owner label grants nothing.
 * Rust factory provenance is still required by the one-use prepared handoff.
 * The owned key-write phase handles lifecycle events; current() watches actual
 * auth/login/session/team/request state and permits its own storage preference.
 * No login UI, bootstrap path or automatic Worker activation is replaced.
 */
export async function captureBrowserOrdinaryRetentionContext(signal:AbortSignal){
 if(typeof window==="undefined"||signal.aborted)throw Error("unavailable");
 const [{get},auth,profile,team,signup,bootstrap,{browserProfileLifecycle},cryptoService]=await Promise.all([
  import("svelte/store"),import("../../stores/authStore"),import("../../stores/userProfile"),import("../../stores/teamStore"),
  import("../../stores/signupState"),import("../../stores/authBootstrapReadiness"),import("./platformLifecycle"),import("../cryptoService")]);
 await bootstrap.waitForAuthBootstrapReadiness(signal);if(signal.aborted)throw Error("cancelled");
 const context=()=>{const state=get(auth.authStore),user=get(profile.userProfile),active=get(team.activeTeamContext);return{owner:user.user_id,authenticated:state.isAuthenticated,
  initialized:state.isInitialized,checking:get(auth.isCheckingAuth),verification:get(auth.needsDeviceVerification),loggingOut:get(signup.isLoggingOut),forced:get(signup.forcedLogoutInProgress),
  login:auth.getLoginSessionGeneration(),teamId:active.teamId,teamEpoch:active.epoch,sessionId:sessionStorage.getItem("session_id")};};
 const prior=context();if(!prior.authenticated||!prior.initialized||prior.checking||prior.verification||prior.loggingOut||prior.forced||prior.teamId!==null
  ||typeof prior.owner!=="string"||!prior.owner||!prior.sessionId)throw Error("unavailable");
 const lifecycleGeneration=browserProfileLifecycle.current();
 const current=()=>{if(signal.aborted)throw Error("cancelled");const now=context();if(Object.keys(prior).some(key=>now[key as keyof typeof now]!==prior[key as keyof typeof prior]))throw Error("invalidated_snapshot");};
 current();return Object.freeze({principal:prior.owner,sessionId:prior.sessionId,loginGeneration:prior.login,lifecycleGeneration,current,afterOrdinarySave(){current();cryptoService.setupMasterKeyUnloadHandler();cryptoService.startMasterKeyValidation();current();}});
}

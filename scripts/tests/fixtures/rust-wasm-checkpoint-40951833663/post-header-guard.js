/* @ts-self-types="./openmates_browser.d.ts" */
import { recoveryCancel, recoveryCapture, recoveryInventoryRequest, recoveryListen, recoveryRead, recoveryRequest, recoveryStop } from './snippets/openmates-sdk-c8cc119936fa2be8/inline0.js';
import * as import3 from "./snippets/openmates-sdk-c8cc119936fa2be8/inline0.js"
import * as import4 from "./snippets/openmates-sdk-c8cc119936fa2be8/inline0.js"


/**
 * Keyless actual-socket wait resource. No mutable Client or auth lock is held
 * while changed() waits. close/free affects only this original socket.
 */
export class BrowserCacheMonitor {
    static __wrap(ptr) {
        const obj = Object.create(BrowserCacheMonitor.prototype);
        obj.__wbg_ptr = ptr;
        BrowserCacheMonitorFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserCacheMonitorFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browsercachemonitor_free(ptr, 0);
    }
    /**
     * @returns {Promise<boolean>}
     */
    changed() {
        const ret = wasm.browsercachemonitor_changed(this.__wbg_ptr);
        return ret;
    }
    close() {
        wasm.browsercachemonitor_close(this.__wbg_ptr);
    }
    /**
     * @returns {string}
     */
    get id() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browsercachemonitor_id(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
}
if (Symbol.dispose) BrowserCacheMonitor.prototype[Symbol.dispose] = BrowserCacheMonitor.prototype.free;

export class BrowserCacheMonitorStartControl {
    static __wrap(ptr) {
        const obj = Object.create(BrowserCacheMonitorStartControl.prototype);
        obj.__wbg_ptr = ptr;
        BrowserCacheMonitorStartControlFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserCacheMonitorStartControlFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browsercachemonitorstartcontrol_free(ptr, 0);
    }
    cancel() {
        wasm.browsercachemonitorstartcontrol_cancel(this.__wbg_ptr);
    }
    /**
     * @param {BrowserCoreClient} client
     */
    ensure_current(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browsercachemonitorstartcontrol_ensure_current(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @returns {Promise<void>}
     */
    retire() {
        const ret = wasm.browsercachemonitorstartcontrol_retire(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {BrowserCacheMonitorStartTerminal | undefined}
     */
    terminal() {
        const ret = wasm.browsercachemonitorstartcontrol_terminal(this.__wbg_ptr);
        return ret === 0 ? undefined : BrowserCacheMonitorStartTerminal.__wrap(ret);
    }
}
if (Symbol.dispose) BrowserCacheMonitorStartControl.prototype[Symbol.dispose] = BrowserCacheMonitorStartControl.prototype.free;

export class BrowserCacheMonitorStartStep {
    static __wrap(ptr) {
        const obj = Object.create(BrowserCacheMonitorStartStep.prototype);
        obj.__wbg_ptr = ptr;
        BrowserCacheMonitorStartStepFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserCacheMonitorStartStepFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browsercachemonitorstartstep_free(ptr, 0);
    }
    /**
     * @param {BrowserCoreClient} client
     */
    apply(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browsercachemonitorstartstep_apply(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @returns {string}
     */
    get kind() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browsercachemonitorstartstep_kind(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @param {BrowserCoreClient} client
     * @returns {BrowserCacheMonitor}
     */
    retain(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browsercachemonitorstartstep_retain(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserCacheMonitor.__wrap(ret[0]);
    }
}
if (Symbol.dispose) BrowserCacheMonitorStartStep.prototype[Symbol.dispose] = BrowserCacheMonitorStartStep.prototype.free;

export class BrowserCacheMonitorStartTerminal {
    static __wrap(ptr) {
        const obj = Object.create(BrowserCacheMonitorStartTerminal.prototype);
        obj.__wbg_ptr = ptr;
        BrowserCacheMonitorStartTerminalFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserCacheMonitorStartTerminalFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browsercachemonitorstartterminal_free(ptr, 0);
    }
    /**
     * @returns {boolean}
     */
    acquisition_io_quiescent() {
        const ret = wasm.browsercachemonitorstartterminal_acquisition_io_quiescent(this.__wbg_ptr);
        return ret !== 0;
    }
}
if (Symbol.dispose) BrowserCacheMonitorStartTerminal.prototype[Symbol.dispose] = BrowserCacheMonitorStartTerminal.prototype.free;

export class BrowserCachedReadPublication {
    static __wrap(ptr) {
        const obj = Object.create(BrowserCachedReadPublication.prototype);
        obj.__wbg_ptr = ptr;
        BrowserCachedReadPublicationFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserCachedReadPublicationFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browsercachedreadpublication_free(ptr, 0);
    }
    /**
     * @returns {string}
     */
    get id() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browsercachedreadpublication_id(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @param {BrowserCoreClient} client
     * @returns {string}
     */
    take(client) {
        let deferred2_0;
        let deferred2_1;
        try {
            _assertClass(client, BrowserCoreClient);
            const ret = wasm.browsercachedreadpublication_take(this.__wbg_ptr, client.__wbg_ptr);
            var ptr1 = ret[0];
            var len1 = ret[1];
            if (ret[3]) {
                ptr1 = 0; len1 = 0;
                throw takeFromExternrefTable0(ret[2]);
            }
            deferred2_0 = ptr1;
            deferred2_1 = len1;
            return getStringFromWasm0(ptr1, len1);
        } finally {
            wasm.__wbindgen_free(deferred2_0, deferred2_1, 1);
        }
    }
}
if (Symbol.dispose) BrowserCachedReadPublication.prototype[Symbol.dispose] = BrowserCachedReadPublication.prototype.free;

export class BrowserCoreClient {
    static __wrap(ptr) {
        const obj = Object.create(BrowserCoreClient.prototype);
        obj.__wbg_ptr = ptr;
        BrowserCoreClientFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserCoreClientFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browsercoreclient_free(ptr, 0);
    }
    /**
     * First authoritative status; there is no caller-supplied owner/generation.
     * @returns {BrowserCoreStatus}
     */
    admitted_status() {
        const ret = wasm.browsercoreclient_admitted_status(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserCoreStatus.__wrap(ret[0]);
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {BrowserOwnedSendStep} step
     * @returns {Promise<BrowserOwnedSendResume>}
     */
    apply_owned_send(handle, generation, step) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        _assertClass(step, BrowserOwnedSendStep);
        var ptr1 = step.__destroy_into_raw();
        const ret = wasm.browsercoreclient_apply_owned_send(this.__wbg_ptr, ptr0, len0, generation, ptr1);
        return ret;
    }
    /**
     * UI selects the initial-sync operation. Authentication/owner/backend and
     * connection admission come only from actual Rust Client/monitor resources.
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} monitor_id
     * @returns {BrowserInitialSyncHandle}
     */
    begin_initial_sync(handle, generation, owner, monitor_id) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(monitor_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_begin_initial_sync(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserInitialSyncHandle.__wrap(ret[0]);
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} id
     * @param {string} selector_json
     * @param {string} scope_json
     * @param {number} now_seconds
     * @returns {BrowserOwnedMessageReadHandle}
     */
    begin_owned_cache_cold_read(handle, generation, owner, id, selector_json, scope_json, now_seconds) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(selector_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ptr4 = passStringToWasm0(scope_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len4 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_begin_owned_cache_cold_read(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, ptr4, len4, now_seconds);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOwnedMessageReadHandle.__wrap(ret[0]);
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} monitor_id
     * @param {string} id
     * @param {string} selector_json
     * @param {string} scope_json
     * @param {number} now_seconds
     * @returns {BrowserOwnedMessageReadHandle}
     */
    begin_owned_cache_incoming_read(handle, generation, owner, monitor_id, id, selector_json, scope_json, now_seconds) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(monitor_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ptr4 = passStringToWasm0(selector_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len4 = WASM_VECTOR_LEN;
        const ptr5 = passStringToWasm0(scope_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len5 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_begin_owned_cache_incoming_read(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, ptr4, len4, ptr5, len5, now_seconds);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOwnedMessageReadHandle.__wrap(ret[0]);
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} id
     * @param {string} selector_json
     * @param {string} scope_json
     * @param {number} now_seconds
     * @returns {BrowserOwnedMessageReadHandle}
     */
    begin_owned_cache_local_first_read(handle, generation, owner, id, selector_json, scope_json, now_seconds) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(selector_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ptr4 = passStringToWasm0(scope_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len4 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_begin_owned_cache_local_first_read(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, ptr4, len4, now_seconds);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOwnedMessageReadHandle.__wrap(ret[0]);
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {BrowserOwnedSendStep} step
     * @returns {string}
     */
    finish_owned_send(handle, generation, step) {
        let deferred4_0;
        let deferred4_1;
        try {
            const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len0 = WASM_VECTOR_LEN;
            _assertClass(step, BrowserOwnedSendStep);
            var ptr1 = step.__destroy_into_raw();
            const ret = wasm.browsercoreclient_finish_owned_send(this.__wbg_ptr, ptr0, len0, generation, ptr1);
            var ptr3 = ret[0];
            var len3 = ret[1];
            if (ret[3]) {
                ptr3 = 0; len3 = 0;
                throw takeFromExternrefTable0(ret[2]);
            }
            deferred4_0 = ptr3;
            deferred4_1 = len3;
            return getStringFromWasm0(ptr3, len3);
        } finally {
            wasm.__wbindgen_free(deferred4_0, deferred4_1, 1);
        }
    }
    /**
     * Called only after the original mutable WASM future released its borrow.
     * Consumes the exact Rust terminal before any session reuse/publication.
     * @param {string} handle
     * @param {number} generation
     * @param {BrowserSendTerminal} terminal
     * @returns {string}
     */
    finish_send(handle, generation, terminal) {
        let deferred4_0;
        let deferred4_1;
        try {
            const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len0 = WASM_VECTOR_LEN;
            _assertClass(terminal, BrowserSendTerminal);
            var ptr1 = terminal.__destroy_into_raw();
            const ret = wasm.browsercoreclient_finish_send(this.__wbg_ptr, ptr0, len0, generation, ptr1);
            var ptr3 = ret[0];
            var len3 = ret[1];
            if (ret[3]) {
                ptr3 = 0; len3 = 0;
                throw takeFromExternrefTable0(ret[2]);
            }
            deferred4_0 = ptr3;
            deferred4_1 = len3;
            return getStringFromWasm0(ptr3, len3);
        } finally {
            wasm.__wbindgen_free(deferred4_0, deferred4_1, 1);
        }
    }
    invalidate() {
        wasm.browsercoreclient_invalidate(this.__wbg_ptr);
    }
    /**
     * CI/inactive fresh-login seam. Password is owned and wiped in WASM;
     * no key/session getters or host persistence acknowledgement are exposed.
     * @param {string} api_url
     * @param {string} app_origin
     * @param {string} session_id
     * @param {string} email
     * @param {string} password
     * @param {string | null} [tfa]
     * @param {boolean | null} [stay_logged_in]
     * @returns {Promise<BrowserCoreClient>}
     */
    static login_password(api_url, app_origin, session_id, email, password, tfa, stay_logged_in) {
        const ptr0 = passStringToWasm0(api_url, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(app_origin, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(session_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(email, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ptr4 = passStringToWasm0(password, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len4 = WASM_VECTOR_LEN;
        var ptr5 = isLikeNone(tfa) ? 0 : passStringToWasm0(tfa, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        var len5 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_login_password(ptr0, len0, ptr1, len1, ptr2, len2, ptr3, len3, ptr4, len4, ptr5, len5, isLikeNone(stay_logged_in) ? 0xFFFFFF : stay_logged_in ? 1 : 0);
        return ret;
    }
    /**
     * One shared SDK latest viewing page, in the owning admitted Worker only.
     * Caller IDs select a resource; they do not grant owner/key/session authority.
     * @param {string} handle
     * @param {number} generation
     * @param {string} chat_id
     * @returns {Promise<any>}
     */
    open_chat(handle, generation, chat_id) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(chat_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_open_chat(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1);
        return ret;
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @returns {BrowserPreparedCacheMonitor}
     */
    prepare_cache_monitor(handle, generation, owner) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_prepare_cache_monitor(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserPreparedCacheMonitor.__wrap(ret[0]);
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} monitor_id
     * @param {string} id
     * @param {string} selector_json
     * @param {string} scope_json
     * @param {number} now_seconds
     * @param {Function} host_effect
     * @returns {Promise<BrowserIncomingPublication>}
     */
    prepare_cache_monitor_update(handle, generation, owner, monitor_id, id, selector_json, scope_json, now_seconds, host_effect) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(monitor_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ptr4 = passStringToWasm0(selector_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len4 = WASM_VECTOR_LEN;
        const ptr5 = passStringToWasm0(scope_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len5 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_prepare_cache_monitor_update(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, ptr4, len4, ptr5, len5, now_seconds, host_effect);
        return ret;
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} id
     * @param {string} selector_json
     * @param {string} scope_json
     * @param {number} now_seconds
     * @param {Function} host_effect
     * @returns {Promise<BrowserCachedReadPublication>}
     */
    prepare_cold_retained_saved_chat(handle, generation, owner, id, selector_json, scope_json, now_seconds, host_effect) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(selector_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ptr4 = passStringToWasm0(scope_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len4 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_prepare_cold_retained_saved_chat(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, ptr4, len4, now_seconds, host_effect);
        return ret;
    }
    /**
     * Browser-only encrypted host preparation, never native Session or ACK.
     * @param {string} handle
     * @param {number} generation
     * @returns {Promise<string>}
     */
    prepare_credentials(handle, generation) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_prepare_credentials(this.__wbg_ptr, ptr0, len0, generation);
        return ret;
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} chat_id
     * @param {string} markdown
     * @param {string} scope
     * @param {number} now
     * @param {Function} effect
     * @returns {Promise<BrowserDraftWriteHandle>}
     */
    prepare_local_draft(handle, generation, owner, chat_id, markdown, scope, now, effect) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(chat_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(markdown, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ptr4 = passStringToWasm0(scope, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len4 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_prepare_local_draft(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, ptr4, len4, now, effect);
        return ret;
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} id
     * @param {string} selector_json
     * @param {string} scope_json
     * @param {number} now_seconds
     * @param {Function} host_effect
     * @returns {Promise<BrowserCachedReadPublication>}
     */
    prepare_monitored_retained_saved_chat(handle, generation, owner, id, selector_json, scope_json, now_seconds, host_effect) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(selector_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ptr4 = passStringToWasm0(scope_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len4 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_prepare_monitored_retained_saved_chat(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, ptr4, len4, now_seconds, host_effect);
        return ret;
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @returns {BrowserOwnedPreparedSend}
     */
    prepare_new_owned_send(handle, generation) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_prepare_new_owned_send(this.__wbg_ptr, ptr0, len0, generation);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOwnedPreparedSend.__wrap(ret[0]);
    }
    /**
     * Inactive ordinary retention preparation after genuine password admission.
     * Existing restore stays nonmutating; no strong persistence ACK is exposed.
     * @param {string} handle
     * @param {number} generation
     * @param {boolean} stay_logged_in
     * @param {number} lifecycle_generation
     * @returns {Promise<BrowserOrdinaryLoginRetention>}
     */
    prepare_ordinary_login_retention(handle, generation, stay_logged_in, lifecycle_generation) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_prepare_ordinary_login_retention(this.__wbg_ptr, ptr0, len0, generation, stay_logged_in, lifecycle_generation);
        return ret;
    }
    /**
     * New opt-in ownership path; old methods remain the compatibility surface.
     * @param {string} handle
     * @param {number} generation
     * @param {string} chat_id
     * @returns {BrowserOwnedPreparedSend}
     */
    prepare_owned_send(handle, generation, chat_id) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(chat_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_prepare_owned_send(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOwnedPreparedSend.__wrap(ret[0]);
    }
    /**
     * Prepare a separately callable cancellation/event handle before entering
     * the mutable async Client lane. No network or turn admission occurs here.
     * @param {string} handle
     * @param {number} generation
     * @param {string} chat_id
     * @returns {BrowserPreparedSend}
     */
    prepare_send(handle, generation, chat_id) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(chat_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_prepare_send(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserPreparedSend.__wrap(ret[0]);
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} ids_json
     * @returns {Promise<string>}
     */
    read_cached_chat_items(handle, generation, owner, ids_json) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(ids_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_read_cached_chat_items(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2);
        return ret;
    }
    /**
     * Inactive explicit local-row bridge. No IDB IO or remote fallback occurs.
     * @param {string} handle
     * @param {number} generation
     * @param {string} expected_principal
     * @param {string} chat_id
     * @param {string} encrypted_rows_json
     * @param {boolean} saved
     * @returns {Promise<string>}
     */
    read_local_chat(handle, generation, expected_principal, chat_id, encrypted_rows_json, saved) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(expected_principal, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(chat_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(encrypted_rows_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_read_local_chat(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, saved);
        return ret;
    }
    /**
     * Exact retained checkpoint presentation; the callback executes only the
     * existing bounded metadata plan. No key export, PII lookup or remote read.
     * @param {string} handle
     * @param {number} generation
     * @param {string} expected_principal
     * @param {string} chat_id
     * @param {string} checkpoint_id
     * @param {Function} host_effect
     * @returns {Promise<string>}
     */
    read_local_checkpoint_summary(handle, generation, expected_principal, chat_id, checkpoint_id, host_effect) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(expected_principal, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(chat_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(checkpoint_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_read_local_checkpoint_summary(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, host_effect);
        return ret;
    }
    /**
     * Existing owned Worker resource, with Rust issuing bounded platform reads.
     * The callback receives selectors only; it cannot enroll/export a master key.
     * @param {string} handle
     * @param {number} generation
     * @param {string} expected_principal
     * @param {string} chat_id
     * @param {string} selector_json
     * @param {Function} host_effect
     * @returns {Promise<string>}
     */
    read_local_saved_chat_cursor(handle, generation, expected_principal, chat_id, selector_json, host_effect) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(expected_principal, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(chat_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(selector_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_read_local_saved_chat_cursor(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, host_effect);
        return ret;
    }
    /**
     * Distinct actual-retained-row view, never canonical saved-read/export.
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} id
     * @param {string} selector_json
     * @param {string} scope_json
     * @param {Function} host_effect
     * @returns {Promise<string>}
     */
    read_retained_saved_chat(handle, generation, owner, id, selector_json, scope_json, host_effect) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(selector_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ptr4 = passStringToWasm0(scope_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len4 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_read_retained_saved_chat(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, ptr4, len4, host_effect);
        return ret;
    }
    /**
     * One bounded rich saved-chat view. All metadata/decryption stays in the
     * shared SDK; JSON carries its closed public DTO, never native authority.
     * @param {string} handle
     * @param {number} generation
     * @param {string} chat_id
     * @returns {Promise<string>}
     */
    read_saved_chat(handle, generation, chat_id) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(chat_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_read_saved_chat(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1);
        return ret;
    }
    /**
     * Browser selectors only; the existing shared operation owns all paging,
     * canonical permission, denial, metadata, crypto and page-local PII policy.
     * @param {string} handle
     * @param {number} generation
     * @param {string} chat_id
     * @param {string} selector_json
     * @returns {Promise<string>}
     */
    read_saved_chat_page(handle, generation, chat_id, selector_json) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(chat_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(selector_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_read_saved_chat_page(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2);
        return ret;
    }
    /**
     * One read-only passive WebSocket reconnection followed by a fresh bounded
     * selected page. This is neither a complete sync nor durable publication.
     * No send, recovery claim, cache replacement or host persistence is invoked.
     * @param {string} handle
     * @param {number} generation
     * @param {string} chat_id
     * @returns {Promise<any>}
     */
    reconnect_chat(handle, generation, chat_id) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(chat_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_reconnect_chat(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1);
        return ret;
    }
    /**
     * @param {string} api_url
     * @param {string} app_origin
     * @param {string} session_id
     * @param {PreparedBrowserProfile} prepared
     * @returns {Promise<BrowserCoreClient>}
     */
    static restore(api_url, app_origin, session_id, prepared) {
        const ptr0 = passStringToWasm0(api_url, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(app_origin, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(session_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        _assertClass(prepared, PreparedBrowserProfile);
        var ptr3 = prepared.__destroy_into_raw();
        const ret = wasm.browsercoreclient_restore(ptr0, len0, ptr1, len1, ptr2, len2, ptr3);
        return ret;
    }
    /**
     * Actual admitted Client/key fences are enforced inside the shared core
     * across every IO await. JS supplies only owned existing-store effects.
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} ids_json
     * @param {string} scope_json
     * @param {Function} host_effect
     * @returns {Promise<string>}
     */
    restore_cached_metadata(handle, generation, owner, ids_json, scope_json, host_effect) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(ids_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(scope_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_restore_cached_metadata(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, host_effect);
        return ret;
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} chat_id
     * @param {string} scope
     * @param {Function} effect
     * @returns {Promise<BrowserDraftPublicationHandle>}
     */
    restore_local_draft(handle, generation, owner, chat_id, scope, effect) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(chat_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(scope, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_restore_local_draft(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2, ptr3, len3, effect);
        return ret;
    }
    /**
     * Dedicated inactive CAS lane. Worker owns one inherited platform lease;
     * this Rust driver owns all sequencing and secret/predecessor decisions.
     * @param {string} handle
     * @param {number} generation
     * @param {string} scope_json
     * @param {Function} host_effect
     * @returns {Promise<string>}
     */
    rotate_credentials(handle, generation, scope_json, host_effect) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(scope_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_rotate_credentials(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, host_effect);
        return ret;
    }
    /**
     * Existing saved-chat foreground send; shared Rust owns all encrypted
     * admission, stream, cancellation and canonical server persistence policy.
     * No browser credential/cache receipt is fabricated or acknowledged.
     * @param {string} handle
     * @param {number} generation
     * @param {BrowserPreparedSend} prepared
     * @param {string} text
     * @returns {Promise<BrowserSendTerminal>}
     */
    send_saved(handle, generation, prepared, text) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        _assertClass(prepared, BrowserPreparedSend);
        var ptr1 = prepared.__destroy_into_raw();
        const ptr2 = passStringToWasm0(text, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_send_saved(this.__wbg_ptr, ptr0, len0, generation, ptr1, ptr2, len2);
        return ret;
    }
    /**
     * Existing explicit foreground choice. Hints and ports never enable it.
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {boolean} enabled
     */
    set_foreground_recovery(handle, generation, owner, enabled) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_set_foreground_recovery(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, enabled);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @returns {Promise<BrowserCacheMonitor>}
     */
    start_cache_monitor(handle, generation, owner) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_start_cache_monitor(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1);
        return ret;
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {BrowserOwnedPreparedSend} prepared
     * @param {string} text
     * @returns {BrowserOwnedSendDriver}
     */
    start_owned_send(handle, generation, prepared, text) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        _assertClass(prepared, BrowserOwnedPreparedSend);
        var ptr1 = prepared.__destroy_into_raw();
        const ptr2 = passStringToWasm0(text, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_start_owned_send(this.__wbg_ptr, ptr0, len0, generation, ptr1, ptr2, len2);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOwnedSendDriver.__wrap(ret[0]);
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @returns {BrowserCoreStatus}
     */
    status(handle, generation) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_status(this.__wbg_ptr, ptr0, len0, generation);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserCoreStatus.__wrap(ret[0]);
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} owner
     * @param {string} monitor_id
     */
    stop_cache_monitor(handle, generation, owner, monitor_id) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(owner, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(monitor_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_stop_cache_monitor(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1, ptr2, len2);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @param {string} handle
     * @param {number} generation
     * @param {string} encoded
     * @returns {Promise<string>}
     */
    validate_credentials(handle, generation, encoded) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(encoded, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsercoreclient_validate_credentials(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1);
        return ret;
    }
}
if (Symbol.dispose) BrowserCoreClient.prototype[Symbol.dispose] = BrowserCoreClient.prototype.free;

/**
 * Deliberately carries only a handle and non-secret SDK-authoritative status.
 */
export class BrowserCoreStatus {
    static __wrap(ptr) {
        const obj = Object.create(BrowserCoreStatus.prototype);
        obj.__wbg_ptr = ptr;
        BrowserCoreStatusFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserCoreStatusFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browsercorestatus_free(ptr, 0);
    }
    /**
     * @returns {number}
     */
    get generation() {
        const ret = wasm.browsercorestatus_generation(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {string}
     */
    get handle() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browsercorestatus_handle(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {boolean}
     */
    get local_read_only() {
        const ret = wasm.browsercorestatus_local_read_only(this.__wbg_ptr);
        return ret !== 0;
    }
    /**
     * @returns {boolean}
     */
    get persisted() {
        const ret = wasm.browsercorestatus_persisted(this.__wbg_ptr);
        return ret !== 0;
    }
    /**
     * @returns {string}
     */
    get principal() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browsercorestatus_principal(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
}
if (Symbol.dispose) BrowserCoreStatus.prototype[Symbol.dispose] = BrowserCoreStatus.prototype.free;

export class BrowserDraftControlHandle {
    static __wrap(ptr) {
        const obj = Object.create(BrowserDraftControlHandle.prototype);
        obj.__wbg_ptr = ptr;
        BrowserDraftControlHandleFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserDraftControlHandleFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserdraftcontrolhandle_free(ptr, 0);
    }
    cancel() {
        wasm.browserdraftcontrolhandle_cancel(this.__wbg_ptr);
    }
}
if (Symbol.dispose) BrowserDraftControlHandle.prototype[Symbol.dispose] = BrowserDraftControlHandle.prototype.free;

export class BrowserDraftPublicationHandle {
    static __wrap(ptr) {
        const obj = Object.create(BrowserDraftPublicationHandle.prototype);
        obj.__wbg_ptr = ptr;
        BrowserDraftPublicationHandleFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserDraftPublicationHandleFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserdraftpublicationhandle_free(ptr, 0);
    }
    /**
     * @param {BrowserCoreClient} client
     * @returns {string}
     */
    take(client) {
        let deferred2_0;
        let deferred2_1;
        try {
            const ptr = this.__destroy_into_raw();
            _assertClass(client, BrowserCoreClient);
            const ret = wasm.browserdraftpublicationhandle_take(ptr, client.__wbg_ptr);
            var ptr1 = ret[0];
            var len1 = ret[1];
            if (ret[3]) {
                ptr1 = 0; len1 = 0;
                throw takeFromExternrefTable0(ret[2]);
            }
            deferred2_0 = ptr1;
            deferred2_1 = len1;
            return getStringFromWasm0(ptr1, len1);
        } finally {
            wasm.__wbindgen_free(deferred2_0, deferred2_1, 1);
        }
    }
}
if (Symbol.dispose) BrowserDraftPublicationHandle.prototype[Symbol.dispose] = BrowserDraftPublicationHandle.prototype.free;

export class BrowserDraftWriteHandle {
    static __wrap(ptr) {
        const obj = Object.create(BrowserDraftWriteHandle.prototype);
        obj.__wbg_ptr = ptr;
        BrowserDraftWriteHandleFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserDraftWriteHandleFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserdraftwritehandle_free(ptr, 0);
    }
    /**
     * @returns {BrowserDraftControlHandle}
     */
    control() {
        const ret = wasm.browserdraftwritehandle_control(this.__wbg_ptr);
        return BrowserDraftControlHandle.__wrap(ret);
    }
    /**
     * @param {BrowserCoreClient} client
     * @returns {string}
     */
    local_result(client) {
        let deferred2_0;
        let deferred2_1;
        try {
            _assertClass(client, BrowserCoreClient);
            const ret = wasm.browserdraftwritehandle_local_result(this.__wbg_ptr, client.__wbg_ptr);
            var ptr1 = ret[0];
            var len1 = ret[1];
            if (ret[3]) {
                ptr1 = 0; len1 = 0;
                throw takeFromExternrefTable0(ret[2]);
            }
            deferred2_0 = ptr1;
            deferred2_1 = len1;
            return getStringFromWasm0(ptr1, len1);
        } finally {
            wasm.__wbindgen_free(deferred2_0, deferred2_1, 1);
        }
    }
    /**
     * @param {BrowserCoreClient} client
     * @param {Function} effect
     * @returns {Promise<BrowserDraftPublicationHandle>}
     */
    synchronize(client, effect) {
        const ptr = this.__destroy_into_raw();
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserdraftwritehandle_synchronize(ptr, client.__wbg_ptr, effect);
        return ret;
    }
}
if (Symbol.dispose) BrowserDraftWriteHandle.prototype[Symbol.dispose] = BrowserDraftWriteHandle.prototype.free;

export class BrowserIncomingPublication {
    static __wrap(ptr) {
        const obj = Object.create(BrowserIncomingPublication.prototype);
        obj.__wbg_ptr = ptr;
        BrowserIncomingPublicationFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserIncomingPublicationFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserincomingpublication_free(ptr, 0);
    }
    /**
     * @returns {string}
     */
    get id() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browserincomingpublication_id(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @param {BrowserCoreClient} client
     * @returns {string}
     */
    take(client) {
        let deferred2_0;
        let deferred2_1;
        try {
            _assertClass(client, BrowserCoreClient);
            const ret = wasm.browserincomingpublication_take(this.__wbg_ptr, client.__wbg_ptr);
            var ptr1 = ret[0];
            var len1 = ret[1];
            if (ret[3]) {
                ptr1 = 0; len1 = 0;
                throw takeFromExternrefTable0(ret[2]);
            }
            deferred2_0 = ptr1;
            deferred2_1 = len1;
            return getStringFromWasm0(ptr1, len1);
        } finally {
            wasm.__wbindgen_free(deferred2_0, deferred2_1, 1);
        }
    }
}
if (Symbol.dispose) BrowserIncomingPublication.prototype[Symbol.dispose] = BrowserIncomingPublication.prototype.free;

export class BrowserInitialSyncControl {
    static __wrap(ptr) {
        const obj = Object.create(BrowserInitialSyncControl.prototype);
        obj.__wbg_ptr = ptr;
        BrowserInitialSyncControlFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserInitialSyncControlFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserinitialsynccontrol_free(ptr, 0);
    }
    cancel() {
        wasm.browserinitialsynccontrol_cancel(this.__wbg_ptr);
    }
    /**
     * @param {BrowserCoreClient} client
     */
    ensure_current(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserinitialsynccontrol_ensure_current(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
}
if (Symbol.dispose) BrowserInitialSyncControl.prototype[Symbol.dispose] = BrowserInitialSyncControl.prototype.free;

/**
 * Actual initial-sync IO handle. drive borrows no mutable Client/auth lane.
 */
export class BrowserInitialSyncHandle {
    static __wrap(ptr) {
        const obj = Object.create(BrowserInitialSyncHandle.prototype);
        obj.__wbg_ptr = ptr;
        BrowserInitialSyncHandleFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserInitialSyncHandleFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserinitialsynchandle_free(ptr, 0);
    }
    /**
     * @returns {BrowserInitialSyncControl}
     */
    control() {
        const ret = wasm.browserinitialsynchandle_control(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserInitialSyncControl.__wrap(ret[0]);
    }
    /**
     * @returns {Promise<void>}
     */
    drive() {
        const ret = wasm.browserinitialsynchandle_drive(this.__wbg_ptr);
        return ret;
    }
    /**
     * @param {BrowserCoreClient} client
     * @returns {BrowserInitialSyncMetadata}
     */
    retain(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserinitialsynchandle_retain(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserInitialSyncMetadata.__wrap(ret[0]);
    }
}
if (Symbol.dispose) BrowserInitialSyncHandle.prototype[Symbol.dispose] = BrowserInitialSyncHandle.prototype.free;

/**
 * Opaque original-source DATA only. No native-store, key or public-row getter.
 * Native per-row persistence and whole-hint completion remain separate work.
 */
export class BrowserInitialSyncMetadata {
    static __wrap(ptr) {
        const obj = Object.create(BrowserInitialSyncMetadata.prototype);
        obj.__wbg_ptr = ptr;
        BrowserInitialSyncMetadataFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserInitialSyncMetadataFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserinitialsyncmetadata_free(ptr, 0);
    }
    cancel() {
        wasm.browserinitialsyncmetadata_cancel(this.__wbg_ptr);
    }
    /**
     * @param {BrowserCoreClient} client
     */
    ensure_current(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserinitialsyncmetadata_ensure_current(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @param {BrowserCoreClient} client
     * @returns {number}
     */
    received_metadata_count(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserinitialsyncmetadata_received_metadata_count(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return ret[0] >>> 0;
    }
}
if (Symbol.dispose) BrowserInitialSyncMetadata.prototype[Symbol.dispose] = BrowserInitialSyncMetadata.prototype.free;

/**
 * One-use fresh-login resource. It cannot be built from host JSON or a key label.
 * The caller closes its fresh Worker after take(), performs ordinary page IO,
 * then admits a NEW saved-read Worker from the resulting genuine profile.
 */
export class BrowserOrdinaryLoginRetention {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOrdinaryLoginRetention.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOrdinaryLoginRetentionFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOrdinaryLoginRetentionFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserordinaryloginretention_free(ptr, 0);
    }
    /**
     * @param {BrowserCoreClient} client
     * @returns {any}
     */
    take(client) {
        const ptr = this.__destroy_into_raw();
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserordinaryloginretention_take(ptr, client.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return takeFromExternrefTable0(ret[0]);
    }
}
if (Symbol.dispose) BrowserOrdinaryLoginRetention.prototype[Symbol.dispose] = BrowserOrdinaryLoginRetention.prototype.free;

export class BrowserOriginalPhysicalDraftInventory {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOriginalPhysicalDraftInventory.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOriginalPhysicalDraftInventoryFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOriginalPhysicalDraftInventoryFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browseroriginalphysicaldraftinventory_free(ptr, 0);
    }
    /**
     * @param {BrowserCoreClient} client
     */
    apply(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browseroriginalphysicaldraftinventory_apply(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @returns {Promise<void>}
     */
    drive() {
        const ret = wasm.browseroriginalphysicaldraftinventory_drive(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {string}
     */
    get kind() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browseroriginalphysicaldraftinventory_kind(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
}
if (Symbol.dispose) BrowserOriginalPhysicalDraftInventory.prototype[Symbol.dispose] = BrowserOriginalPhysicalDraftInventory.prototype.free;

/**
 * Separate negative control remains callable while handle.drive owns a mutable
 * wasm-bindgen borrow across native IO. It can never release output or drain.
 */
export class BrowserOriginalRecoveryControl {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOriginalRecoveryControl.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOriginalRecoveryControlFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOriginalRecoveryControlFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browseroriginalrecoverycontrol_free(ptr, 0);
    }
    cancel() {
        wasm.browseroriginalrecoverycontrol_cancel(this.__wbg_ptr);
    }
    /**
     * @returns {Promise<void>}
     */
    wait_cancelled() {
        const ret = wasm.browseroriginalrecoverycontrol_wait_cancelled(this.__wbg_ptr);
        return ret;
    }
}
if (Symbol.dispose) BrowserOriginalRecoveryControl.prototype[Symbol.dispose] = BrowserOriginalRecoveryControl.prototype.free;

export class BrowserOriginalRecoveryHandle {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOriginalRecoveryHandle.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOriginalRecoveryHandleFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOriginalRecoveryHandleFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browseroriginalrecoveryhandle_free(ptr, 0);
    }
    /**
     * Every original Client/native start/final publication phase is short and
     * synchronous. Errors keep the exact persistence failure/resource in self.
     * @param {BrowserCoreClient} client
     */
    apply(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browseroriginalrecoveryhandle_apply(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @returns {BrowserOriginalRecoveryControl}
     */
    control() {
        const ret = wasm.browseroriginalrecoveryhandle_control(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOriginalRecoveryControl.__wrap(ret[0]);
    }
    /**
     * Await only native driver/IO/crypto resources; no Client/auth lock exists.
     * @returns {Promise<void>}
     */
    drive() {
        const ret = wasm.browseroriginalrecoveryhandle_drive(this.__wbg_ptr);
        return ret;
    }
    /**
     * @param {BrowserCoreClient} client
     */
    ensure_current(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browseroriginalrecoveryhandle_ensure_current(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @returns {string | undefined}
     */
    failure_kind() {
        const ret = wasm.browseroriginalrecoveryhandle_failure_kind(this.__wbg_ptr);
        let v1;
        if (ret[0] !== 0) {
            v1 = getStringFromWasm0(ret[0], ret[1]);
            wasm.__wbindgen_free(ret[0], ret[1] * 1, 1);
        }
        return v1;
    }
    /**
     * Selection DATA captured from the actual Core offer, never caller input.
     * The selected Core operation independently validates original Progress.
     * @returns {string}
     */
    get job_kind() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browseroriginalrecoveryhandle_job_kind(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    get kind() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browseroriginalrecoveryhandle_kind(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * Encrypted checkpoint identity DATA only; never a durability constructor.
     * @returns {string | undefined}
     */
    pending_checkpoint_digest() {
        const ret = wasm.browseroriginalrecoveryhandle_pending_checkpoint_digest(this.__wbg_ptr);
        if (ret[3]) {
            throw takeFromExternrefTable0(ret[2]);
        }
        let v1;
        if (ret[0] !== 0) {
            v1 = getStringFromWasm0(ret[0], ret[1]);
            wasm.__wbindgen_free(ret[0], ret[1] * 1, 1);
        }
        return v1;
    }
    /**
     * Negative own-resource retirement only after actual canonical/shared-commit
     * adoption or a genuine deferred terminal. Failure/unknown/start states
     * retain their exact resources; this never acknowledges the whole hint.
     */
    retire() {
        const ret = wasm.browseroriginalrecoveryhandle_retire(this.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
}
if (Symbol.dispose) BrowserOriginalRecoveryHandle.prototype[Symbol.dispose] = BrowserOriginalRecoveryHandle.prototype.free;

export class BrowserOriginalRecoveryPort {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOriginalRecoveryPort.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOriginalRecoveryPortFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOriginalRecoveryPortFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browseroriginalrecoveryport_free(ptr, 0);
    }
    /**
     * Caller owns the actual resource through this await, outside Rust/auth
     * leases; failure never attests storage/native driver quiescence.
     * @returns {Promise<void>}
     */
    close_and_drain() {
        const ret = wasm.browseroriginalrecoveryport_close_and_drain(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {Promise<void>}
     */
    ready() {
        const ret = wasm.browseroriginalrecoveryport_ready(this.__wbg_ptr);
        return ret;
    }
    revoke() {
        wasm.browseroriginalrecoveryport_revoke(this.__wbg_ptr);
    }
}
if (Symbol.dispose) BrowserOriginalRecoveryPort.prototype[Symbol.dispose] = BrowserOriginalRecoveryPort.prototype.free;

export class BrowserOwnedMessageReadControl {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOwnedMessageReadControl.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOwnedMessageReadControlFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOwnedMessageReadControlFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserownedmessagereadcontrol_free(ptr, 0);
    }
    cancel() {
        wasm.browserownedmessagereadcontrol_cancel(this.__wbg_ptr);
    }
    /**
     * @param {BrowserCoreClient} client
     */
    ensure_current(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserownedmessagereadcontrol_ensure_current(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
}
if (Symbol.dispose) BrowserOwnedMessageReadControl.prototype[Symbol.dispose] = BrowserOwnedMessageReadControl.prototype.free;

export class BrowserOwnedMessageReadHandle {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOwnedMessageReadHandle.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOwnedMessageReadHandleFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOwnedMessageReadHandleFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserownedmessagereadhandle_free(ptr, 0);
    }
    /**
     * @param {BrowserCoreClient} client
     * @param {BrowserOriginalRecoveryPort} port
     * @returns {BrowserOriginalPhysicalDraftInventory}
     */
    begin_physical_draft_inventory(client, port) {
        _assertClass(client, BrowserCoreClient);
        _assertClass(port, BrowserOriginalRecoveryPort);
        const ret = wasm.browserownedmessagereadhandle_begin_physical_draft_inventory(this.__wbg_ptr, client.__wbg_ptr, port.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOriginalPhysicalDraftInventory.__wrap(ret[0]);
    }
    /**
     * @returns {BrowserOwnedMessageReadControl}
     */
    control() {
        const ret = wasm.browserownedmessagereadhandle_control(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOwnedMessageReadControl.__wrap(ret[0]);
    }
    /**
     * Only this native driver is borrowed; no BrowserCoreClient/auth lock is
     * held while network, opaque key operations or native IO are pending.
     * @returns {Promise<BrowserOwnedMessageReadStepHandle>}
     */
    next() {
        const ret = wasm.browserownedmessagereadhandle_next(this.__wbg_ptr);
        return ret;
    }
    /**
     * Actual returned Core failure + sealed absence, never an error-label test.
     * @param {BrowserCoreClient} client
     * @returns {BrowserProfileCacheAbsenceHandle}
     */
    take_profile_cache_absence(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserownedmessagereadhandle_take_profile_cache_absence(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserProfileCacheAbsenceHandle.__wrap(ret[0]);
    }
    /**
     * Negative-only original driver fact. No Client recapture, auth/storage
     * grant or private output; transferred work and actual Host IO drain apart.
     * @returns {BrowserOwnedReadTerminalHandle | undefined}
     */
    terminal() {
        const ret = wasm.browserownedmessagereadhandle_terminal(this.__wbg_ptr);
        return ret === 0 ? undefined : BrowserOwnedReadTerminalHandle.__wrap(ret);
    }
}
if (Symbol.dispose) BrowserOwnedMessageReadHandle.prototype[Symbol.dispose] = BrowserOwnedMessageReadHandle.prototype.free;

export class BrowserOwnedMessageReadStepHandle {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOwnedMessageReadStepHandle.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOwnedMessageReadStepHandleFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOwnedMessageReadStepHandleFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserownedmessagereadstephandle_free(ptr, 0);
    }
    /**
     * @param {BrowserCoreClient} client
     */
    apply(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserownedmessagereadstephandle_apply(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @param {BrowserCoreClient} client
     * @returns {number | undefined}
     */
    authenticated_messages_version(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserownedmessagereadstephandle_authenticated_messages_version(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[3]) {
            throw takeFromExternrefTable0(ret[2]);
        }
        return ret[0] === 0 ? undefined : ret[1];
    }
    /**
     * @param {BrowserCoreClient} client
     * @returns {string}
     */
    authenticated_source_stamp(client) {
        let deferred2_0;
        let deferred2_1;
        try {
            _assertClass(client, BrowserCoreClient);
            const ret = wasm.browserownedmessagereadstephandle_authenticated_source_stamp(this.__wbg_ptr, client.__wbg_ptr);
            var ptr1 = ret[0];
            var len1 = ret[1];
            if (ret[3]) {
                ptr1 = 0; len1 = 0;
                throw takeFromExternrefTable0(ret[2]);
            }
            deferred2_0 = ptr1;
            deferred2_1 = len1;
            return getStringFromWasm0(ptr1, len1);
        } finally {
            wasm.__wbindgen_free(deferred2_0, deferred2_1, 1);
        }
    }
    /**
     * @param {Function} host_effect
     * @returns {Promise<BrowserOwnedMessageReadStepHandle>}
     */
    execute(host_effect) {
        const ptr = this.__destroy_into_raw();
        const ret = wasm.browserownedmessagereadstephandle_execute(ptr, host_effect);
        return ret;
    }
    /**
     * Sealed cold-only completion of the already-taken selected view. This
     * cannot discard an incoming hint or acknowledge remote metadata work.
     * @param {BrowserCoreClient} client
     */
    finish_cold(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserownedmessagereadstephandle_finish_cold(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @returns {string}
     */
    get id() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browserownedmessagereadstephandle_id(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    get kind() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browserownedmessagereadstephandle_kind(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * Explicit typed incomplete work. Retain this exact native resource; do not
     * immediately retry the same hint or label selected publication complete.
     * @param {BrowserCoreClient} client
     * @returns {BrowserOwnedMetadataContinuationHandle}
     */
    pending_metadata(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserownedmessagereadstephandle_pending_metadata(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOwnedMetadataContinuationHandle.__wrap(ret[0]);
    }
    /**
     * Actual per-B metadata persistence is not whole-hint completion.
     * @param {BrowserCoreClient} client
     * @returns {BrowserOwnedMetadataContinuationHandle}
     */
    pending_remainder(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserownedmessagereadstephandle_pending_remainder(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOwnedMetadataContinuationHandle.__wrap(ret[0]);
    }
    /**
     * Called only after the existing native Host's original prepared-id IO
     * drain acknowledgement. No caller drained/complete boolean is accepted.
     * @param {BrowserCoreClient} client
     * @returns {string}
     */
    take(client) {
        let deferred2_0;
        let deferred2_1;
        try {
            _assertClass(client, BrowserCoreClient);
            const ret = wasm.browserownedmessagereadstephandle_take(this.__wbg_ptr, client.__wbg_ptr);
            var ptr1 = ret[0];
            var len1 = ret[1];
            if (ret[3]) {
                ptr1 = 0; len1 = 0;
                throw takeFromExternrefTable0(ret[2]);
            }
            deferred2_0 = ptr1;
            deferred2_1 = len1;
            return getStringFromWasm0(ptr1, len1);
        } finally {
            wasm.__wbindgen_free(deferred2_0, deferred2_1, 1);
        }
    }
    /**
     * @returns {boolean}
     */
    uses_original_physical_draft_budget() {
        const ret = wasm.browserownedmessagereadstephandle_uses_original_physical_draft_budget(this.__wbg_ptr);
        return ret !== 0;
    }
}
if (Symbol.dispose) BrowserOwnedMessageReadStepHandle.prototype[Symbol.dispose] = BrowserOwnedMessageReadStepHandle.prototype.free;

export class BrowserOwnedMetadataContinuationHandle {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOwnedMetadataContinuationHandle.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOwnedMetadataContinuationHandleFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOwnedMetadataContinuationHandleFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserownedmetadatacontinuationhandle_free(ptr, 0);
    }
    /**
     * Start the next exact native metadata phase after the selected Host IO
     * drain/publication. No new Client, scope, hint or positive receipt exists.
     * @param {BrowserCoreClient} client
     * @returns {BrowserOwnedMessageReadHandle}
     */
    begin_metadata(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserownedmetadatacontinuationhandle_begin_metadata(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOwnedMessageReadHandle.__wrap(ret[0]);
    }
    /**
     * @param {BrowserCoreClient} client
     * @param {BrowserOriginalRecoveryPort} port
     * @returns {BrowserOriginalPhysicalDraftInventory | undefined}
     */
    begin_next_physical_draft_inventory(client, port) {
        _assertClass(client, BrowserCoreClient);
        _assertClass(port, BrowserOriginalRecoveryPort);
        const ret = wasm.browserownedmetadatacontinuationhandle_begin_next_physical_draft_inventory(this.__wbg_ptr, client.__wbg_ptr, port.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return ret[0] === 0 ? undefined : BrowserOriginalPhysicalDraftInventory.__wrap(ret[0]);
    }
    /**
     * Consumes only the original committed metadata remainder and actual full
     * notification offer. No caller job/stage/owner or recovered DTO is read.
     * @param {BrowserCoreClient} client
     * @param {BrowserOriginalRecoveryPort} port
     * @returns {BrowserOriginalRecoveryHandle | undefined}
     */
    begin_next_recovery(client, port) {
        _assertClass(client, BrowserCoreClient);
        _assertClass(port, BrowserOriginalRecoveryPort);
        const ret = wasm.browserownedmetadatacontinuationhandle_begin_next_recovery(this.__wbg_ptr, client.__wbg_ptr, port.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return ret[0] === 0 ? undefined : BrowserOriginalRecoveryHandle.__wrap(ret[0]);
    }
    cancel() {
        wasm.browserownedmetadatacontinuationhandle_cancel(this.__wbg_ptr);
    }
    close() {
        wasm.browserownedmetadatacontinuationhandle_close(this.__wbg_ptr);
    }
    /**
     * @param {BrowserCoreClient} client
     */
    ensure_current(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserownedmetadatacontinuationhandle_ensure_current(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @returns {string}
     */
    get id() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browserownedmetadatacontinuationhandle_id(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    get kind() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browserownedmetadatacontinuationhandle_kind(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {Promise<void>}
     */
    wait_cancelled() {
        const ret = wasm.browserownedmetadatacontinuationhandle_wait_cancelled(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {Promise<void>}
     */
    wait_recovery_work() {
        const ret = wasm.browserownedmetadatacontinuationhandle_wait_recovery_work(this.__wbg_ptr);
        return ret;
    }
}
if (Symbol.dispose) BrowserOwnedMetadataContinuationHandle.prototype[Symbol.dispose] = BrowserOwnedMetadataContinuationHandle.prototype.free;

export class BrowserOwnedPreparedSend {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOwnedPreparedSend.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOwnedPreparedSendFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOwnedPreparedSendFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserownedpreparedsend_free(ptr, 0);
    }
    /**
     * @returns {BrowserSendControl}
     */
    control() {
        const ret = wasm.browserownedpreparedsend_control(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserSendControl.__wrap(ret[0]);
    }
    /**
     * @returns {string}
     */
    get operation_id() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browserownedpreparedsend_operation_id(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {BrowserSendEvents}
     */
    take_events() {
        const ret = wasm.browserownedpreparedsend_take_events(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserSendEvents.__wrap(ret[0]);
    }
}
if (Symbol.dispose) BrowserOwnedPreparedSend.prototype[Symbol.dispose] = BrowserOwnedPreparedSend.prototype.free;

export class BrowserOwnedReadTerminalHandle {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOwnedReadTerminalHandle.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOwnedReadTerminalHandleFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOwnedReadTerminalHandleFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserownedreadterminalhandle_free(ptr, 0);
    }
    /**
     * @returns {boolean}
     */
    is_quiescent() {
        const ret = wasm.browserownedreadterminalhandle_is_quiescent(this.__wbg_ptr);
        return ret !== 0;
    }
}
if (Symbol.dispose) BrowserOwnedReadTerminalHandle.prototype[Symbol.dispose] = BrowserOwnedReadTerminalHandle.prototype.free;

export class BrowserOwnedSendDriver {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOwnedSendDriver.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOwnedSendDriverFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOwnedSendDriverFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserownedsenddriver_free(ptr, 0);
    }
    /**
     * This await owns only portable driver state; BrowserCoreClient is absent.
     * @param {string} handle
     * @param {number} generation
     * @param {string} operation
     * @returns {Promise<BrowserOwnedSendStep>}
     */
    next_phase(handle, generation, operation) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(operation, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browserownedsenddriver_next_phase(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1);
        return ret;
    }
    /**
     * @param {BrowserOwnedSendResume} resume
     */
    resume(resume) {
        _assertClass(resume, BrowserOwnedSendResume);
        var ptr0 = resume.__destroy_into_raw();
        const ret = wasm.browserownedsenddriver_resume(this.__wbg_ptr, ptr0);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
}
if (Symbol.dispose) BrowserOwnedSendDriver.prototype[Symbol.dispose] = BrowserOwnedSendDriver.prototype.free;

export class BrowserOwnedSendResume {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOwnedSendResume.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOwnedSendResumeFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOwnedSendResumeFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserownedsendresume_free(ptr, 0);
    }
}
if (Symbol.dispose) BrowserOwnedSendResume.prototype[Symbol.dispose] = BrowserOwnedSendResume.prototype.free;

export class BrowserOwnedSendStep {
    static __wrap(ptr) {
        const obj = Object.create(BrowserOwnedSendStep.prototype);
        obj.__wbg_ptr = ptr;
        BrowserOwnedSendStepFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserOwnedSendStepFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserownedsendstep_free(ptr, 0);
    }
    /**
     * @returns {string}
     */
    get kind() {
        let deferred2_0;
        let deferred2_1;
        try {
            const ret = wasm.browserownedsendstep_kind(this.__wbg_ptr);
            var ptr1 = ret[0];
            var len1 = ret[1];
            if (ret[3]) {
                ptr1 = 0; len1 = 0;
                throw takeFromExternrefTable0(ret[2]);
            }
            deferred2_0 = ptr1;
            deferred2_1 = len1;
            return getStringFromWasm0(ptr1, len1);
        } finally {
            wasm.__wbindgen_free(deferred2_0, deferred2_1, 1);
        }
    }
}
if (Symbol.dispose) BrowserOwnedSendStep.prototype[Symbol.dispose] = BrowserOwnedSendStep.prototype.free;

export class BrowserPreparedCacheMonitor {
    static __wrap(ptr) {
        const obj = Object.create(BrowserPreparedCacheMonitor.prototype);
        obj.__wbg_ptr = ptr;
        BrowserPreparedCacheMonitorFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserPreparedCacheMonitorFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserpreparedcachemonitor_free(ptr, 0);
    }
    /**
     * @returns {BrowserCacheMonitorStartControl}
     */
    control() {
        const ret = wasm.browserpreparedcachemonitor_control(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserCacheMonitorStartControl.__wrap(ret[0]);
    }
    /**
     * @returns {Promise<BrowserCacheMonitorStartStep>}
     */
    next() {
        const ret = wasm.browserpreparedcachemonitor_next(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {BrowserCacheMonitorStartTerminal | undefined}
     */
    terminal() {
        const ret = wasm.browserpreparedcachemonitor_terminal(this.__wbg_ptr);
        return ret === 0 ? undefined : BrowserCacheMonitorStartTerminal.__wrap(ret);
    }
}
if (Symbol.dispose) BrowserPreparedCacheMonitor.prototype[Symbol.dispose] = BrowserPreparedCacheMonitor.prototype.free;

export class BrowserPreparedSend {
    static __wrap(ptr) {
        const obj = Object.create(BrowserPreparedSend.prototype);
        obj.__wbg_ptr = ptr;
        BrowserPreparedSendFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserPreparedSendFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserpreparedsend_free(ptr, 0);
    }
    /**
     * @returns {BrowserSendControl}
     */
    control() {
        const ret = wasm.browserpreparedsend_control(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserSendControl.__wrap(ret[0]);
    }
    /**
     * @returns {string}
     */
    get operation_id() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.browserpreparedsend_operation_id(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {BrowserSendEvents}
     */
    take_events() {
        const ret = wasm.browserpreparedsend_take_events(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserSendEvents.__wrap(ret[0]);
    }
}
if (Symbol.dispose) BrowserPreparedSend.prototype[Symbol.dispose] = BrowserPreparedSend.prototype.free;

export class BrowserProfileCacheAbsenceHandle {
    static __wrap(ptr) {
        const obj = Object.create(BrowserProfileCacheAbsenceHandle.prototype);
        obj.__wbg_ptr = ptr;
        BrowserProfileCacheAbsenceHandleFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserProfileCacheAbsenceHandleFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserprofilecacheabsencehandle_free(ptr, 0);
    }
    /**
     * @param {BrowserCoreClient} client
     */
    consume(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserprofilecacheabsencehandle_consume(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @param {BrowserCoreClient} client
     */
    ensure_current(client) {
        _assertClass(client, BrowserCoreClient);
        const ret = wasm.browserprofilecacheabsencehandle_ensure_current(this.__wbg_ptr, client.__wbg_ptr);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
}
if (Symbol.dispose) BrowserProfileCacheAbsenceHandle.prototype[Symbol.dispose] = BrowserProfileCacheAbsenceHandle.prototype.free;

export class BrowserRecoveryBootstrap {
    static __wrap(ptr) {
        const obj = Object.create(BrowserRecoveryBootstrap.prototype);
        obj.__wbg_ptr = ptr;
        BrowserRecoveryBootstrapFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserRecoveryBootstrapFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserrecoverybootstrap_free(ptr, 0);
    }
    /**
     * Consumes the original first-bootstrap resource and actual prepared
     * profile. Root binding occurs INSIDE this Rust constructor before either
     * the restored Client or its status can escape to the Worker dispatcher.
     * @param {string} api_url
     * @param {string} app_origin
     * @param {string} session_id
     * @param {PreparedBrowserProfile} prepared
     * @returns {Promise<BrowserRecoveryRestoredClient>}
     */
    restore_original(api_url, app_origin, session_id, prepared) {
        const ptr = this.__destroy_into_raw();
        const ptr0 = passStringToWasm0(api_url, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(app_origin, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(session_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        _assertClass(prepared, PreparedBrowserProfile);
        var ptr3 = prepared.__destroy_into_raw();
        const ret = wasm.browserrecoverybootstrap_restore_original(ptr, ptr0, len0, ptr1, len1, ptr2, len2, ptr3);
        return ret;
    }
}
if (Symbol.dispose) BrowserRecoveryBootstrap.prototype[Symbol.dispose] = BrowserRecoveryBootstrap.prototype.free;

/**
 * One-use extraction from the already-root-bound Rust restore result. These
 * methods grant no new authority; Port/Client retain their original resources.
 */
export class BrowserRecoveryRestoredClient {
    static __wrap(ptr) {
        const obj = Object.create(BrowserRecoveryRestoredClient.prototype);
        obj.__wbg_ptr = ptr;
        BrowserRecoveryRestoredClientFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserRecoveryRestoredClientFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browserrecoveryrestoredclient_free(ptr, 0);
    }
    /**
     * @returns {BrowserCoreClient}
     */
    take_client() {
        const ret = wasm.browserrecoveryrestoredclient_take_client(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserCoreClient.__wrap(ret[0]);
    }
    /**
     * @returns {BrowserOriginalRecoveryPort}
     */
    take_port() {
        const ret = wasm.browserrecoveryrestoredclient_take_port(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return BrowserOriginalRecoveryPort.__wrap(ret[0]);
    }
}
if (Symbol.dispose) BrowserRecoveryRestoredClient.prototype[Symbol.dispose] = BrowserRecoveryRestoredClient.prototype.free;

export class BrowserSendControl {
    static __wrap(ptr) {
        const obj = Object.create(BrowserSendControl.prototype);
        obj.__wbg_ptr = ptr;
        BrowserSendControlFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserSendControlFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browsersendcontrol_free(ptr, 0);
    }
    /**
     * Request cooperative SDK cancellation. This is not a server stop ACK.
     * @param {string} handle
     * @param {number} generation
     * @param {string} operation
     */
    cancel(handle, generation, operation) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(operation, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsersendcontrol_cancel(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    close() {
        wasm.browsersendcontrol_close(this.__wbg_ptr);
    }
    /**
     * A pending encoded frame cannot outlive authoritative core revocation.
     * @param {string} handle
     * @param {number} generation
     * @param {string} operation
     * @returns {boolean}
     */
    publication_current(handle, generation, operation) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(operation, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsersendcontrol_publication_current(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return ret[0] !== 0;
    }
}
if (Symbol.dispose) BrowserSendControl.prototype[Symbol.dispose] = BrowserSendControl.prototype.free;

export class BrowserSendEvents {
    static __wrap(ptr) {
        const obj = Object.create(BrowserSendEvents.prototype);
        obj.__wbg_ptr = ptr;
        BrowserSendEventsFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserSendEventsFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browsersendevents_free(ptr, 0);
    }
    /**
     * Pull exactly one bounded SDK update or one final scoped outcome. The
     * independent control object remains callable while this borrow is pending.
     * @param {string} handle
     * @param {number} generation
     * @param {string} operation
     * @returns {Promise<string | undefined>}
     */
    next_event(handle, generation, operation) {
        const ptr0 = passStringToWasm0(handle, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(operation, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ret = wasm.browsersendevents_next_event(this.__wbg_ptr, ptr0, len0, generation, ptr1, len1);
        return ret;
    }
}
if (Symbol.dispose) BrowserSendEvents.prototype[Symbol.dispose] = BrowserSendEvents.prototype.free;

export class BrowserSendTerminal {
    static __wrap(ptr) {
        const obj = Object.create(BrowserSendTerminal.prototype);
        obj.__wbg_ptr = ptr;
        BrowserSendTerminalFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BrowserSendTerminalFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_browsersendterminal_free(ptr, 0);
    }
}
if (Symbol.dispose) BrowserSendTerminal.prototype[Symbol.dispose] = BrowserSendTerminal.prototype.free;

export class IntoUnderlyingByteSource {
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        IntoUnderlyingByteSourceFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_intounderlyingbytesource_free(ptr, 0);
    }
    /**
     * @returns {number}
     */
    get autoAllocateChunkSize() {
        const ret = wasm.intounderlyingbytesource_autoAllocateChunkSize(this.__wbg_ptr);
        return ret >>> 0;
    }
    cancel() {
        const ptr = this.__destroy_into_raw();
        wasm.intounderlyingbytesource_cancel(ptr);
    }
    /**
     * @param {ReadableByteStreamController} controller
     * @returns {Promise<any>}
     */
    pull(controller) {
        const ret = wasm.intounderlyingbytesource_pull(this.__wbg_ptr, controller);
        return ret;
    }
    /**
     * @param {ReadableByteStreamController} controller
     */
    start(controller) {
        wasm.intounderlyingbytesource_start(this.__wbg_ptr, controller);
    }
    /**
     * @returns {ReadableStreamType}
     */
    get type() {
        const ret = wasm.intounderlyingbytesource_type(this.__wbg_ptr);
        return __wbindgen_enum_ReadableStreamType[ret];
    }
}
if (Symbol.dispose) IntoUnderlyingByteSource.prototype[Symbol.dispose] = IntoUnderlyingByteSource.prototype.free;

export class IntoUnderlyingSink {
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        IntoUnderlyingSinkFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_intounderlyingsink_free(ptr, 0);
    }
    /**
     * @param {any} reason
     * @returns {Promise<any>}
     */
    abort(reason) {
        const ptr = this.__destroy_into_raw();
        const ret = wasm.intounderlyingsink_abort(ptr, reason);
        return ret;
    }
    /**
     * @returns {Promise<any>}
     */
    close() {
        const ptr = this.__destroy_into_raw();
        const ret = wasm.intounderlyingsink_close(ptr);
        return ret;
    }
    /**
     * @param {any} chunk
     * @returns {Promise<any>}
     */
    write(chunk) {
        const ret = wasm.intounderlyingsink_write(this.__wbg_ptr, chunk);
        return ret;
    }
}
if (Symbol.dispose) IntoUnderlyingSink.prototype[Symbol.dispose] = IntoUnderlyingSink.prototype.free;

export class IntoUnderlyingSource {
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        IntoUnderlyingSourceFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_intounderlyingsource_free(ptr, 0);
    }
    cancel() {
        const ptr = this.__destroy_into_raw();
        wasm.intounderlyingsource_cancel(ptr);
    }
    /**
     * @param {ReadableStreamDefaultController} controller
     * @returns {Promise<any>}
     */
    pull(controller) {
        const ret = wasm.intounderlyingsource_pull(this.__wbg_ptr, controller);
        return ret;
    }
}
if (Symbol.dispose) IntoUnderlyingSource.prototype[Symbol.dispose] = IntoUnderlyingSource.prototype.free;

/**
 * Worker-local, one-use profile. No field getters, Debug or serialization.
 */
export class PreparedBrowserProfile {
    static __wrap(ptr) {
        const obj = Object.create(PreparedBrowserProfile.prototype);
        obj.__wbg_ptr = ptr;
        PreparedBrowserProfileFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        PreparedBrowserProfileFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_preparedbrowserprofile_free(ptr, 0);
    }
    /**
     * Synchronous copy into Zeroizing memory. The caller must erase the JS
     * export buffer immediately on return, before any network await.
     * @param {string} principal
     * @param {Uint8Array} raw
     * @param {string} encrypted_email
     * @param {string} user_email_salt
     * @param {boolean} persisted
     * @returns {PreparedBrowserProfile}
     */
    static from_bytes(principal, raw, encrypted_email, user_email_salt, persisted) {
        const ptr0 = passStringToWasm0(principal, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passArray8ToWasm0(raw, wasm.__wbindgen_malloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(encrypted_email, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ptr3 = passStringToWasm0(user_email_salt, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len3 = WASM_VECTOR_LEN;
        const ret = wasm.preparedbrowserprofile_from_bytes(ptr0, len0, ptr1, len1, ptr2, len2, ptr3, len3, persisted);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return PreparedBrowserProfile.__wrap(ret[0]);
    }
    /**
     * The thin Worker passes the existing structured-cloned CryptoKey itself.
     * No export, persistence, wrapping or account authority is supplied by JS.
     * @param {string} principal
     * @param {CryptoKey} key
     * @param {string} encrypted_email
     * @param {string} user_email_salt
     * @param {boolean} persisted
     * @returns {Promise<PreparedBrowserProfile>}
     */
    static from_crypto_key(principal, key, encrypted_email, user_email_salt, persisted) {
        const ptr0 = passStringToWasm0(principal, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ptr1 = passStringToWasm0(encrypted_email, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len1 = WASM_VECTOR_LEN;
        const ptr2 = passStringToWasm0(user_email_salt, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len2 = WASM_VECTOR_LEN;
        const ret = wasm.preparedbrowserprofile_from_crypto_key(ptr0, len0, key, ptr1, len1, ptr2, len2, persisted);
        return ret;
    }
    /**
     * Explicit legacy-profile handoff. Unknown optional metadata never forces
     * email decryption, enrollment, or reauthentication. This is not owner proof.
     * @param {string} principal
     * @param {CryptoKey} key
     * @param {string | null | undefined} hashed_email
     * @param {string | null | undefined} user_email_salt
     * @param {boolean} persisted
     * @returns {PreparedBrowserProfile}
     */
    static from_existing_key(principal, key, hashed_email, user_email_salt, persisted) {
        const ptr0 = passStringToWasm0(principal, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        var ptr1 = isLikeNone(hashed_email) ? 0 : passStringToWasm0(hashed_email, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        var len1 = WASM_VECTOR_LEN;
        var ptr2 = isLikeNone(user_email_salt) ? 0 : passStringToWasm0(user_email_salt, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        var len2 = WASM_VECTOR_LEN;
        const ret = wasm.preparedbrowserprofile_from_existing_key(ptr0, len0, key, ptr1, len1, ptr2, len2, persisted);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return PreparedBrowserProfile.__wrap(ret[0]);
    }
}
if (Symbol.dispose) PreparedBrowserProfile.prototype[Symbol.dispose] = PreparedBrowserProfile.prototype.free;

/**
 * Called ONLY with held FIRST valid native bootstrap event before normal RPC
 * installation/Worker escape. Never return this private resource to the Page.
 * @param {any} event
 * @returns {BrowserRecoveryBootstrap | undefined}
 */
export function capture_original_recovery_bootstrap(event) {
    const ret = wasm.capture_original_recovery_bootstrap(event);
    if (ret[2]) {
        throw takeFromExternrefTable0(ret[1]);
    }
    return ret[0] === 0 ? undefined : BrowserRecoveryBootstrap.__wrap(ret[0]);
}
function __wbg_get_imports() {
    const import0 = {
        __proto__: null,
        __wbg___wbindgen_boolean_get_5b446f51afd21013: function(arg0) {
            const v = arg0;
            const ret = typeof(v) === 'boolean' ? v : undefined;
            return isLikeNone(ret) ? 0xFFFFFF : ret ? 1 : 0;
        },
        __wbg___wbindgen_is_function_1f9d30630b8b1d3d: function(arg0) {
            const ret = typeof(arg0) === 'function';
            return ret;
        },
        __wbg___wbindgen_is_null_e343b7d08827ba72: function(arg0) {
            const ret = arg0 === null;
            return ret;
        },
        __wbg___wbindgen_is_object_3c45d4f2dde4e749: function(arg0) {
            const val = arg0;
            const ret = typeof(val) === 'object' && val !== null;
            return ret;
        },
        __wbg___wbindgen_is_string_90b56bc79aad6f6c: function(arg0) {
            const ret = typeof(arg0) === 'string';
            return ret;
        },
        __wbg___wbindgen_is_undefined_8865fb403f8fe9d8: function(arg0) {
            const ret = arg0 === undefined;
            return ret;
        },
        __wbg___wbindgen_number_get_2e0e7dee9f701a71: function(arg0, arg1) {
            const obj = arg1;
            const ret = typeof(obj) === 'number' ? obj : undefined;
            getDataViewMemory0().setFloat64(arg0 + 8 * 1, isLikeNone(ret) ? 0 : ret, true);
            getDataViewMemory0().setInt32(arg0 + 4 * 0, !isLikeNone(ret), true);
        },
        __wbg___wbindgen_string_get_0380ccaa2f57f0d9: function(arg0, arg1) {
            const obj = arg1;
            const ret = typeof(obj) === 'string' ? obj : undefined;
            var ptr1 = isLikeNone(ret) ? 0 : passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            var len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32(arg0 + 4 * 1, len1, true);
            getDataViewMemory0().setInt32(arg0 + 4 * 0, ptr1, true);
        },
        __wbg___wbindgen_throw_41e9ee4f547fc59a: function(arg0, arg1) {
            throw new Error(getStringFromWasm0(arg0, arg1));
        },
        __wbg__wbg_cb_unref_dcc1a90847f04c41: function(arg0) {
            arg0._wbg_cb_unref();
        },
        __wbg_abort_f78b99d80248bacb: function(arg0) {
            arg0.abort();
        },
        __wbg_algorithm_876b2fc4b3022030: function() { return handleError(function (arg0) {
            const ret = arg0.algorithm;
            return ret;
        }, arguments); },
        __wbg_apply_a910804df6e1e433: function() { return handleError(function (arg0, arg1, arg2) {
            const ret = arg0.apply(arg1, arg2);
            return ret;
        }, arguments); },
        __wbg_body_4e088733babc630d: function(arg0) {
            const ret = arg0.body;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_browsercachedreadpublication_new: function(arg0) {
            const ret = BrowserCachedReadPublication.__wrap(arg0);
            return ret;
        },
        __wbg_browsercachemonitor_new: function(arg0) {
            const ret = BrowserCacheMonitor.__wrap(arg0);
            return ret;
        },
        __wbg_browsercachemonitorstartstep_new: function(arg0) {
            const ret = BrowserCacheMonitorStartStep.__wrap(arg0);
            return ret;
        },
        __wbg_browsercoreclient_new: function(arg0) {
            const ret = BrowserCoreClient.__wrap(arg0);
            return ret;
        },
        __wbg_browserdraftpublicationhandle_new: function(arg0) {
            const ret = BrowserDraftPublicationHandle.__wrap(arg0);
            return ret;
        },
        __wbg_browserdraftwritehandle_new: function(arg0) {
            const ret = BrowserDraftWriteHandle.__wrap(arg0);
            return ret;
        },
        __wbg_browserincomingpublication_new: function(arg0) {
            const ret = BrowserIncomingPublication.__wrap(arg0);
            return ret;
        },
        __wbg_browserordinaryloginretention_new: function(arg0) {
            const ret = BrowserOrdinaryLoginRetention.__wrap(arg0);
            return ret;
        },
        __wbg_browserownedmessagereadstephandle_new: function(arg0) {
            const ret = BrowserOwnedMessageReadStepHandle.__wrap(arg0);
            return ret;
        },
        __wbg_browserownedsendresume_new: function(arg0) {
            const ret = BrowserOwnedSendResume.__wrap(arg0);
            return ret;
        },
        __wbg_browserownedsendstep_new: function(arg0) {
            const ret = BrowserOwnedSendStep.__wrap(arg0);
            return ret;
        },
        __wbg_browserrecoveryrestoredclient_new: function(arg0) {
            const ret = BrowserRecoveryRestoredClient.__wrap(arg0);
            return ret;
        },
        __wbg_browsersendterminal_new: function(arg0) {
            const ret = BrowserSendTerminal.__wrap(arg0);
            return ret;
        },
        __wbg_buffer_56ec2905a66f58b9: function(arg0) {
            const ret = arg0.buffer;
            return ret;
        },
        __wbg_bufferedAmount_64b8a4229f549d4b: function(arg0) {
            const ret = arg0.bufferedAmount;
            return ret;
        },
        __wbg_byobRequest_54f7ce41d584549a: function(arg0) {
            const ret = arg0.byobRequest;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_byteLength_9f985b8373f1f3fe: function(arg0) {
            const ret = arg0.byteLength;
            return ret;
        },
        __wbg_byteOffset_0bd5a6a03553639c: function(arg0) {
            const ret = arg0.byteOffset;
            return ret;
        },
        __wbg_call_1875a20c43a36133: function() { return handleError(function (arg0, arg1, arg2, arg3) {
            const ret = arg0.call(arg1, arg2, arg3);
            return ret;
        }, arguments); },
        __wbg_call_187d372bd5fdd4aa: function() { return handleError(function (arg0, arg1, arg2) {
            const ret = arg0.call(arg1, arg2);
            return ret;
        }, arguments); },
        __wbg_call_6137034ef55c9d0f: function() { return handleError(function (arg0, arg1) {
            const ret = arg0.call(arg1);
            return ret;
        }, arguments); },
        __wbg_cancel_7c2a08c8db4c73f3: function(arg0) {
            const ret = arg0.cancel();
            return ret;
        },
        __wbg_catch_92594c2d17f55f12: function(arg0, arg1) {
            const ret = arg0.catch(arg1);
            return ret;
        },
        __wbg_clearTimeout_113b1cde814ec762: function(arg0) {
            const ret = clearTimeout(arg0);
            return ret;
        },
        __wbg_close_185286988f30f252: function() { return handleError(function (arg0) {
            arg0.close();
        }, arguments); },
        __wbg_close_748f26698dabe269: function() { return handleError(function (arg0) {
            arg0.close();
        }, arguments); },
        __wbg_close_d3ed56b5763be5ae: function() { return handleError(function (arg0) {
            arg0.close();
        }, arguments); },
        __wbg_crypto_38df2bab126b63dc: function(arg0) {
            const ret = arg0.crypto;
            return ret;
        },
        __wbg_data_522f7abc70721269: function(arg0) {
            const ret = arg0.data;
            return ret;
        },
        __wbg_decrypt_ed2c87e61e64b20e: function() { return handleError(function (arg0, arg1, arg2, arg3) {
            const ret = arg0.decrypt(arg1, arg2, arg3);
            return ret;
        }, arguments); },
        __wbg_done_b41a1d26cdb37fb6: function(arg0) {
            const ret = arg0.done;
            return ret;
        },
        __wbg_encrypt_e5011bfbe9cca035: function() { return handleError(function (arg0, arg1, arg2, arg3) {
            const ret = arg0.encrypt(arg1, arg2, arg3);
            return ret;
        }, arguments); },
        __wbg_enqueue_4a01c128f9a0de16: function() { return handleError(function (arg0, arg1) {
            arg0.enqueue(arg1);
        }, arguments); },
        __wbg_fill_775586ed37049ccf: function(arg0, arg1, arg2, arg3) {
            const ret = arg0.fill(arg1, arg2 >>> 0, arg3 >>> 0);
            return ret;
        },
        __wbg_from_296ca31f8d0f1c52: function(arg0) {
            const ret = Array.from(arg0);
            return ret;
        },
        __wbg_getRandomValues_869eb80731672410: function() { return handleError(function (arg0, arg1) {
            globalThis.crypto.getRandomValues(getArrayU8FromWasm0(arg0, arg1));
        }, arguments); },
        __wbg_getRandomValues_a608c4436c19407a: function() { return handleError(function (arg0, arg1) {
            globalThis.crypto.getRandomValues(getArrayU8FromWasm0(arg0, arg1));
        }, arguments); },
        __wbg_getRandomValues_c44a50d8cfdaebeb: function() { return handleError(function (arg0, arg1) {
            arg0.getRandomValues(arg1);
        }, arguments); },
        __wbg_getReader_b4b1868fbca77dbe: function() { return handleError(function (arg0) {
            const ret = arg0.getReader();
            return ret;
        }, arguments); },
        __wbg_get_31af05bd4842a84f: function() { return handleError(function (arg0, arg1) {
            const ret = Reflect.get(arg0, arg1);
            return ret;
        }, arguments); },
        __wbg_get_658f6698067d9515: function() { return handleError(function (arg0, arg1) {
            const ret = Reflect.get(arg0, arg1);
            return ret;
        }, arguments); },
        __wbg_get_6c896e0571ddae51: function(arg0, arg1) {
            const ret = arg0[arg1 >>> 0];
            return ret;
        },
        __wbg_get_done_7020b91c987365c7: function(arg0) {
            const ret = arg0.done;
            return isLikeNone(ret) ? 0xFFFFFF : ret ? 1 : 0;
        },
        __wbg_get_unchecked_288889d017702237: function(arg0, arg1) {
            const ret = arg0[arg1 >>> 0];
            return ret;
        },
        __wbg_get_value_87fbd6ad1283f2e7: function(arg0) {
            const ret = arg0.value;
            return ret;
        },
        __wbg_headers_eba93595f8944c2f: function(arg0) {
            const ret = arg0.headers;
            return ret;
        },
        __wbg_instanceof_ArrayBuffer_a99f175873e5d9b8: function(arg0) {
            let result;
            try {
                result = arg0 instanceof ArrayBuffer;
            } catch (_) {
                result = false;
            }
            const ret = result;
            return ret;
        },
        __wbg_instanceof_CryptoKey_744e9d2b2b74d8a0: function(arg0) {
            let result;
            try {
                result = arg0 instanceof CryptoKey;
            } catch (_) {
                result = false;
            }
            const ret = result;
            return ret;
        },
        __wbg_instanceof_Crypto_1620226aa7193bd2: function(arg0) {
            let result;
            try {
                result = arg0 instanceof Crypto;
            } catch (_) {
                result = false;
            }
            const ret = result;
            return ret;
        },
        __wbg_instanceof_DedicatedWorkerGlobalScope_15b0748d70779242: function(arg0) {
            let result;
            try {
                result = arg0 instanceof DedicatedWorkerGlobalScope;
            } catch (_) {
                result = false;
            }
            const ret = result;
            return ret;
        },
        __wbg_instanceof_Promise_e1dc6893aa1ece28: function(arg0) {
            let result;
            try {
                result = arg0 instanceof Promise;
            } catch (_) {
                result = false;
            }
            const ret = result;
            return ret;
        },
        __wbg_instanceof_Response_b8758567269c30b2: function(arg0) {
            let result;
            try {
                result = arg0 instanceof Response;
            } catch (_) {
                result = false;
            }
            const ret = result;
            return ret;
        },
        __wbg_instanceof_Uint8Array_828cef2aaacafc31: function(arg0) {
            let result;
            try {
                result = arg0 instanceof Uint8Array;
            } catch (_) {
                result = false;
            }
            const ret = result;
            return ret;
        },
        __wbg_isArray_e15a2ff68ffdbef2: function(arg0) {
            const ret = Array.isArray(arg0);
            return ret;
        },
        __wbg_iterator_e3c31c892080e444: function() {
            const ret = Symbol.iterator;
            return ret;
        },
        __wbg_length_78dac82682e59660: function(arg0) {
            const ret = arg0.length;
            return ret;
        },
        __wbg_length_7f3c00c40364105e: function(arg0) {
            const ret = arg0.length;
            return ret;
        },
        __wbg_length_d4bdea10311bd9cf: function(arg0) {
            const ret = arg0.length;
            return ret;
        },
        __wbg_location_42ee01eb1ef737eb: function(arg0) {
            const ret = arg0.location;
            return ret;
        },
        __wbg_msCrypto_bd5a034af96bcba6: function(arg0) {
            const ret = arg0.msCrypto;
            return ret;
        },
        __wbg_new_1dbf7428bba60a42: function(arg0) {
            const ret = new Uint8Array(arg0);
            return ret;
        },
        __wbg_new_2e41357094e99294: function() { return handleError(function () {
            const ret = new AbortController();
            return ret;
        }, arguments); },
        __wbg_new_343a093a3c2ffb4e: function(arg0, arg1) {
            const ret = new Error(getStringFromWasm0(arg0, arg1));
            return ret;
        },
        __wbg_new_4059fb0406225e04: function() { return handleError(function (arg0, arg1) {
            const ret = new WebSocket(getStringFromWasm0(arg0, arg1));
            return ret;
        }, arguments); },
        __wbg_new_617a8cdb8bb1130e: function() {
            const ret = new Object();
            return ret;
        },
        __wbg_new_83ca405eae412a62: function() { return handleError(function () {
            const ret = new Headers();
            return ret;
        }, arguments); },
        __wbg_new_ee2291f50781bf1d: function() {
            const ret = new Array();
            return ret;
        },
        __wbg_new_from_slice_9a868026ffa4208a: function(arg0, arg1) {
            const ret = new Uint8Array(getArrayU8FromWasm0(arg0, arg1));
            return ret;
        },
        __wbg_new_typed_b01cb72a8af741a3: function(arg0, arg1) {
            try {
                var state0 = {a: arg0, b: arg1};
                var cb0 = (arg0, arg1) => {
                    const a = state0.a;
                    state0.a = 0;
                    try {
                        return wasm_bindgen_1d20785795349f07___convert__closures_____invoke___js_sys_77b40d978049f4c4___Function_fn_wasm_bindgen_1d20785795349f07___JsValue_____wasm_bindgen_1d20785795349f07___sys__Undefined___js_sys_77b40d978049f4c4___Function_fn_wasm_bindgen_1d20785795349f07___JsValue_____wasm_bindgen_1d20785795349f07___sys__Undefined_______true_(a, state0.b, arg0, arg1);
                    } finally {
                        state0.a = a;
                    }
                };
                const ret = new Promise(cb0);
                return ret;
            } finally {
                state0.a = 0;
            }
        },
        __wbg_new_with_byte_offset_and_length_2f5d7fc2a828b74d: function(arg0, arg1, arg2) {
            const ret = new Uint8Array(arg0, arg1 >>> 0, arg2 >>> 0);
            return ret;
        },
        __wbg_new_with_length_3da0ad195f6f63ba: function(arg0) {
            const ret = new Uint8Array(arg0 >>> 0);
            return ret;
        },
        __wbg_new_with_str_and_init_4618dee4e950224f: function() { return handleError(function (arg0, arg1, arg2) {
            const ret = new Request(getStringFromWasm0(arg0, arg1), arg2);
            return ret;
        }, arguments); },
        __wbg_next_33784799010f1bbe: function(arg0) {
            const ret = arg0.next;
            return ret;
        },
        __wbg_next_f4aac29c42af995c: function() { return handleError(function (arg0) {
            const ret = arg0.next();
            return ret;
        }, arguments); },
        __wbg_node_84ea875411254db1: function(arg0) {
            const ret = arg0.node;
            return ret;
        },
        __wbg_now_aa4ccb83129e9e55: function() {
            const ret = Date.now();
            return ret;
        },
        __wbg_now_e7c6795a7f81e10f: function(arg0) {
            const ret = arg0.now();
            return ret;
        },
        __wbg_origin_829038aa827cdc38: function(arg0, arg1) {
            const ret = arg1.origin;
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32(arg0 + 4 * 1, len1, true);
            getDataViewMemory0().setInt32(arg0 + 4 * 0, ptr1, true);
        },
        __wbg_performance_3fcf6e32a7e1ed0a: function(arg0) {
            const ret = arg0.performance;
            return ret;
        },
        __wbg_preparedbrowserprofile_new: function(arg0) {
            const ret = PreparedBrowserProfile.__wrap(arg0);
            return ret;
        },
        __wbg_process_44c7a14e11e9f69e: function(arg0) {
            const ret = arg0.process;
            return ret;
        },
        __wbg_prototypesetcall_bc27214492979395: function(arg0, arg1, arg2) {
            Uint8Array.prototype.set.call(getArrayU8FromWasm0(arg0, arg1), arg2);
        },
        __wbg_push_2baf45db356cf468: function(arg0, arg1) {
            const ret = arg0.push(arg1);
            return ret;
        },
        __wbg_queueMicrotask_9833f9a49df95a49: function(arg0) {
            const ret = arg0.queueMicrotask;
            return ret;
        },
        __wbg_queueMicrotask_a72f977e97f23c5f: function(arg0) {
            queueMicrotask(arg0);
        },
        __wbg_randomFillSync_6c25eac9869eb53c: function() { return handleError(function (arg0, arg1) {
            arg0.randomFillSync(arg1);
        }, arguments); },
        __wbg_read_2a943774344c9728: function(arg0) {
            const ret = arg0.read();
            return ret;
        },
        __wbg_readyState_d8514376867e415b: function(arg0) {
            const ret = arg0.readyState;
            return ret;
        },
        __wbg_recoveryCancel_8eb0437c1d103a08: function() { return handleError(function (arg0, arg1, arg2, arg3, arg4, arg5) {
            recoveryCancel(arg0, getStringFromWasm0(arg1, arg2), arg3, getStringFromWasm0(arg4, arg5));
        }, arguments); },
        __wbg_recoveryCapture_4b27ea166180a8e4: function() { return handleError(function (arg0) {
            const ret = recoveryCapture(arg0);
            return ret;
        }, arguments); },
        __wbg_recoveryInventoryRequest_13fb844ecff9383d: function() { return handleError(function (arg0, arg1, arg2, arg3, arg4, arg5, arg6, arg7) {
            recoveryInventoryRequest(arg0, getStringFromWasm0(arg1, arg2), arg3, getStringFromWasm0(arg4, arg5), getStringFromWasm0(arg6, arg7));
        }, arguments); },
        __wbg_recoveryListen_7920aa62455d8953: function() { return handleError(function (arg0, arg1) {
            recoveryListen(arg0, arg1);
        }, arguments); },
        __wbg_recoveryRead_6fb63b78d31ac179: function() { return handleError(function (arg0, arg1) {
            const ret = recoveryRead(arg0, arg1);
            return ret;
        }, arguments); },
        __wbg_recoveryRequest_dc171dd8bbe5b83b: function() { return handleError(function (arg0, arg1, arg2, arg3, arg4, arg5, arg6, arg7) {
            recoveryRequest(arg0, getStringFromWasm0(arg1, arg2), arg3, getStringFromWasm0(arg4, arg5), getStringFromWasm0(arg6, arg7));
        }, arguments); },
        __wbg_recoveryStop_7a7b5ee96c3730d8: function() { return handleError(function (arg0, arg1, arg2) {
            recoveryStop(arg0, getStringFromWasm0(arg1, arg2));
        }, arguments); },
        __wbg_releaseLock_eb64cd83aa9fcfe4: function(arg0) {
            arg0.releaseLock();
        },
        __wbg_require_b4edbdcf3e2a1ef0: function() { return handleError(function () {
            const ret = module.require;
            return ret;
        }, arguments); },
        __wbg_resolve_0076e10020304ede: function(arg0) {
            const ret = Promise.resolve(arg0);
            return ret;
        },
        __wbg_respond_c102fabcc79e5ef0: function() { return handleError(function (arg0, arg1) {
            arg0.respond(arg1 >>> 0);
        }, arguments); },
        __wbg_send_b5bdd806efe4baf6: function() { return handleError(function (arg0, arg1, arg2) {
            arg0.send(getStringFromWasm0(arg1, arg2));
        }, arguments); },
        __wbg_setTimeout_ef24d2fc3ad97385: function() { return handleError(function (arg0, arg1) {
            const ret = setTimeout(arg0, arg1);
            return ret;
        }, arguments); },
        __wbg_set_145a351398b48c65: function() { return handleError(function (arg0, arg1, arg2) {
            const ret = Reflect.set(arg0, arg1, arg2);
            return ret;
        }, arguments); },
        __wbg_set_575d3ddb70fe831d: function(arg0, arg1, arg2) {
            arg0.set(getArrayU8FromWasm0(arg1, arg2));
        },
        __wbg_set_af5932e3f78b5648: function() { return handleError(function (arg0, arg1, arg2, arg3, arg4) {
            arg0.set(getStringFromWasm0(arg1, arg2), getStringFromWasm0(arg3, arg4));
        }, arguments); },
        __wbg_set_body_1fb0f1008bfc7df6: function(arg0, arg1) {
            arg0.body = arg1;
        },
        __wbg_set_cache_7507c4cc5938ccc7: function(arg0, arg1) {
            arg0.cache = __wbindgen_enum_RequestCache[arg1];
        },
        __wbg_set_credentials_e0dcce31ca532b7d: function(arg0, arg1) {
            arg0.credentials = __wbindgen_enum_RequestCredentials[arg1];
        },
        __wbg_set_headers_40ad33dcf016613f: function(arg0, arg1) {
            arg0.headers = arg1;
        },
        __wbg_set_method_dcb32343247ec427: function(arg0, arg1, arg2) {
            arg0.method = getStringFromWasm0(arg1, arg2);
        },
        __wbg_set_onclose_a84370531f3d2948: function(arg0, arg1) {
            arg0.onclose = arg1;
        },
        __wbg_set_onerror_94ee307653399172: function(arg0, arg1) {
            arg0.onerror = arg1;
        },
        __wbg_set_onmessage_cb6f77d2d8e0402a: function(arg0, arg1) {
            arg0.onmessage = arg1;
        },
        __wbg_set_onopen_c914147e8a2db4b0: function(arg0, arg1) {
            arg0.onopen = arg1;
        },
        __wbg_set_redirect_cc128ab2411da334: function(arg0, arg1) {
            arg0.redirect = __wbindgen_enum_RequestRedirect[arg1];
        },
        __wbg_set_signal_2dbd377604627f26: function(arg0, arg1) {
            arg0.signal = arg1;
        },
        __wbg_signal_e5a49a2d9c65b7f6: function(arg0) {
            const ret = arg0.signal;
            return ret;
        },
        __wbg_static_accessor_GLOBAL_266715b9d96ba635: function() {
            const ret = typeof global === 'undefined' ? null : global;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_static_accessor_GLOBAL_THIS_10fb7dc1ae063179: function() {
            const ret = typeof globalThis === 'undefined' ? null : globalThis;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_static_accessor_SELF_0b583911f537483a: function() {
            const ret = typeof self === 'undefined' ? null : self;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_static_accessor_WINDOW_d7f903d1508cbdc4: function() {
            const ret = typeof window === 'undefined' ? null : window;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_status_ce0a98d3c57125f3: function(arg0) {
            const ret = arg0.status;
            return ret;
        },
        __wbg_subarray_002b94d5e13d1411: function(arg0, arg1, arg2) {
            const ret = arg0.subarray(arg1 >>> 0, arg2 >>> 0);
            return ret;
        },
        __wbg_subtle_fd9b8e4f931c4961: function(arg0) {
            const ret = arg0.subtle;
            return ret;
        },
        __wbg_then_c949d5a25a4e78f8: function(arg0, arg1, arg2) {
            const ret = arg0.then(arg1, arg2);
            return ret;
        },
        __wbg_then_e71170d78fcf8954: function(arg0, arg1) {
            const ret = arg0.then(arg1);
            return ret;
        },
        __wbg_type_1fa7db973af8bb3b: function(arg0, arg1) {
            const ret = arg1.type;
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32(arg0 + 4 * 1, len1, true);
            getDataViewMemory0().setInt32(arg0 + 4 * 0, ptr1, true);
        },
        __wbg_usages_b2f85c6b5ba0c204: function(arg0) {
            const ret = arg0.usages;
            return ret;
        },
        __wbg_value_f3c585ee8f5ba40c: function(arg0) {
            const ret = arg0.value;
            return ret;
        },
        __wbg_versions_276b2795b1c6a219: function(arg0) {
            const ret = arg0.versions;
            return ret;
        },
        __wbg_view_9c570f33e8d6ab96: function(arg0) {
            const ret = arg0.view;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbindgen_generic_0000000000000001: function(arg0, arg1) {
            // Cast intrinsic for `Closure(Closure { owned: true, function: Function { arguments: [Boolean, Externref], shim_idx: 381, ret: Unit, inner_ret: Some(Unit) }, mutable: true }) -> Externref`.
            const ret = makeMutClosure(arg0, arg1, wasm_bindgen_1d20785795349f07___convert__closures_____invoke___bool__wasm_bindgen_1d20785795349f07___JsValue______true_);
            return ret;
        },
        __wbindgen_generic_0000000000000002: function(arg0, arg1) {
            // Cast intrinsic for `Closure(Closure { owned: true, function: Function { arguments: [Externref, Boolean], shim_idx: 379, ret: Unit, inner_ret: Some(Unit) }, mutable: true }) -> Externref`.
            const ret = makeMutClosure(arg0, arg1, wasm_bindgen_1d20785795349f07___convert__closures_____invoke___wasm_bindgen_1d20785795349f07___JsValue__bool______true_);
            return ret;
        },
        __wbindgen_generic_0000000000000003: function(arg0, arg1) {
            // Cast intrinsic for `Closure(Closure { owned: true, function: Function { arguments: [Externref], shim_idx: 1430, ret: Unit, inner_ret: Some(Unit) }, mutable: true }) -> Externref`.
            const ret = makeMutClosure(arg0, arg1, wasm_bindgen_1d20785795349f07___convert__closures_____invoke___wasm_bindgen_1d20785795349f07___JsValue______true_);
            return ret;
        },
        __wbindgen_generic_0000000000000004: function(arg0, arg1) {
            // Cast intrinsic for `Closure(Closure { owned: true, function: Function { arguments: [Externref], shim_idx: 1567, ret: Result(Unit), inner_ret: Some(Result(Unit)) }, mutable: true }) -> Externref`.
            const ret = makeMutClosure(arg0, arg1, wasm_bindgen_1d20785795349f07___convert__closures_____invoke___wasm_bindgen_1d20785795349f07___JsValue__core_ed718c3d60ebd546___result__Result_____wasm_bindgen_1d20785795349f07___JsError___true_);
            return ret;
        },
        __wbindgen_generic_0000000000000005: function(arg0, arg1) {
            // Cast intrinsic for `Closure(Closure { owned: true, function: Function { arguments: [NamedExternref("CloseEvent")], shim_idx: 556, ret: Unit, inner_ret: Some(Unit) }, mutable: true }) -> Externref`.
            const ret = makeMutClosure(arg0, arg1, wasm_bindgen_1d20785795349f07___convert__closures_____invoke___web_sys_4e9453912a95622___features__gen_CloseEvent__CloseEvent______true_);
            return ret;
        },
        __wbindgen_generic_0000000000000006: function(arg0, arg1) {
            // Cast intrinsic for `Closure(Closure { owned: true, function: Function { arguments: [NamedExternref("Event")], shim_idx: 556, ret: Unit, inner_ret: Some(Unit) }, mutable: true }) -> Externref`.
            const ret = makeMutClosure(arg0, arg1, wasm_bindgen_1d20785795349f07___convert__closures_____invoke___web_sys_4e9453912a95622___features__gen_CloseEvent__CloseEvent______true__161);
            return ret;
        },
        __wbindgen_generic_0000000000000007: function(arg0, arg1) {
            // Cast intrinsic for `Closure(Closure { owned: true, function: Function { arguments: [NamedExternref("MessageEvent")], shim_idx: 556, ret: Unit, inner_ret: Some(Unit) }, mutable: true }) -> Externref`.
            const ret = makeMutClosure(arg0, arg1, wasm_bindgen_1d20785795349f07___convert__closures_____invoke___web_sys_4e9453912a95622___features__gen_CloseEvent__CloseEvent______true__162);
            return ret;
        },
        __wbindgen_generic_0000000000000008: function(arg0, arg1) {
            // Cast intrinsic for `Closure(Closure { owned: true, function: Function { arguments: [], shim_idx: 1394, ret: Unit, inner_ret: Some(Unit) }, mutable: true }) -> Externref`.
            const ret = makeMutClosure(arg0, arg1, wasm_bindgen_1d20785795349f07___convert__closures_____invoke_______true__1_);
            return ret;
        },
        __wbindgen_generic_0000000000000009: function(arg0, arg1) {
            // Cast intrinsic for `Closure(Closure { owned: true, function: Function { arguments: [], shim_idx: 683, ret: Unit, inner_ret: Some(Unit) }, mutable: true }) -> Externref`.
            const ret = makeMutClosure(arg0, arg1, wasm_bindgen_1d20785795349f07___convert__closures_____invoke_______true_);
            return ret;
        },
        __wbindgen_generic_000000000000000a: function(arg0) {
            // Cast intrinsic for `F64 -> Externref`.
            const ret = arg0;
            return ret;
        },
        __wbindgen_generic_000000000000000b: function(arg0, arg1) {
            // Cast intrinsic for `Ref(Slice(U8)) -> NamedExternref("Uint8Array")`.
            const ret = getArrayU8FromWasm0(arg0, arg1);
            return ret;
        },
        __wbindgen_generic_000000000000000c: function(arg0, arg1) {
            // Cast intrinsic for `Ref(String) -> Externref`.
            const ret = getStringFromWasm0(arg0, arg1);
            return ret;
        },
        __wbindgen_init_externref_table: function() {
            const table = wasm.__wbindgen_externrefs;
            const offset = table.grow(4);
            table.set(0, undefined);
            table.set(offset + 0, undefined);
            table.set(offset + 1, null);
            table.set(offset + 2, true);
            table.set(offset + 3, false);
        },
    };
    return {
        __proto__: null,
        "./openmates_browser_bg.js": import0,
        "./snippets/openmates-browser-bindings-63fbca14d615347d/inline0.js": import1,
        "./snippets/openmates-sdk-c8cc119936fa2be8/inline0.js": import2,
        "./snippets/openmates-sdk-c8cc119936fa2be8/inline0.js": import3,
        "./snippets/openmates-sdk-c8cc119936fa2be8/inline0.js": import4,
    };
}

function wasm_bindgen_1d20785795349f07___convert__closures_____invoke_______true__1_(arg0, arg1) {
    wasm.wasm_bindgen_1d20785795349f07___convert__closures_____invoke_______true__1_(arg0, arg1);
}

function wasm_bindgen_1d20785795349f07___convert__closures_____invoke_______true_(arg0, arg1) {
    wasm.wasm_bindgen_1d20785795349f07___convert__closures_____invoke_______true_(arg0, arg1);
}

function wasm_bindgen_1d20785795349f07___convert__closures_____invoke___wasm_bindgen_1d20785795349f07___JsValue______true_(arg0, arg1, arg2) {
    wasm.wasm_bindgen_1d20785795349f07___convert__closures_____invoke___wasm_bindgen_1d20785795349f07___JsValue______true_(arg0, arg1, arg2);
}

function wasm_bindgen_1d20785795349f07___convert__closures_____invoke___web_sys_4e9453912a95622___features__gen_CloseEvent__CloseEvent______true_(arg0, arg1, arg2) {
    wasm.wasm_bindgen_1d20785795349f07___convert__closures_____invoke___web_sys_4e9453912a95622___features__gen_CloseEvent__CloseEvent______true_(arg0, arg1, arg2);
}

function wasm_bindgen_1d20785795349f07___convert__closures_____invoke___web_sys_4e9453912a95622___features__gen_CloseEvent__CloseEvent______true__161(arg0, arg1, arg2) {
    wasm.wasm_bindgen_1d20785795349f07___convert__closures_____invoke___web_sys_4e9453912a95622___features__gen_CloseEvent__CloseEvent______true__161(arg0, arg1, arg2);
}

function wasm_bindgen_1d20785795349f07___convert__closures_____invoke___web_sys_4e9453912a95622___features__gen_CloseEvent__CloseEvent______true__162(arg0, arg1, arg2) {
    wasm.wasm_bindgen_1d20785795349f07___convert__closures_____invoke___web_sys_4e9453912a95622___features__gen_CloseEvent__CloseEvent______true__162(arg0, arg1, arg2);
}

function wasm_bindgen_1d20785795349f07___convert__closures_____invoke___wasm_bindgen_1d20785795349f07___JsValue__core_ed718c3d60ebd546___result__Result_____wasm_bindgen_1d20785795349f07___JsError___true_(arg0, arg1, arg2) {
    const ret = wasm.wasm_bindgen_1d20785795349f07___convert__closures_____invoke___wasm_bindgen_1d20785795349f07___JsValue__core_ed718c3d60ebd546___result__Result_____wasm_bindgen_1d20785795349f07___JsError___true_(arg0, arg1, arg2);
    if (ret[1]) {
        throw takeFromExternrefTable0(ret[0]);
    }
}

function wasm_bindgen_1d20785795349f07___convert__closures_____invoke___js_sys_77b40d978049f4c4___Function_fn_wasm_bindgen_1d20785795349f07___JsValue_____wasm_bindgen_1d20785795349f07___sys__Undefined___js_sys_77b40d978049f4c4___Function_fn_wasm_bindgen_1d20785795349f07___JsValue_____wasm_bindgen_1d20785795349f07___sys__Undefined_______true_(arg0, arg1, arg2, arg3) {
    wasm.wasm_bindgen_1d20785795349f07___convert__closures_____invoke___js_sys_77b40d978049f4c4___Function_fn_wasm_bindgen_1d20785795349f07___JsValue_____wasm_bindgen_1d20785795349f07___sys__Undefined___js_sys_77b40d978049f4c4___Function_fn_wasm_bindgen_1d20785795349f07___JsValue_____wasm_bindgen_1d20785795349f07___sys__Undefined_______true_(arg0, arg1, arg2, arg3);
}

function wasm_bindgen_1d20785795349f07___convert__closures_____invoke___wasm_bindgen_1d20785795349f07___JsValue__bool______true_(arg0, arg1, arg2, arg3) {
    wasm.wasm_bindgen_1d20785795349f07___convert__closures_____invoke___wasm_bindgen_1d20785795349f07___JsValue__bool______true_(arg0, arg1, arg2, arg3);
}

function wasm_bindgen_1d20785795349f07___convert__closures_____invoke___bool__wasm_bindgen_1d20785795349f07___JsValue______true_(arg0, arg1, arg2, arg3) {
    wasm.wasm_bindgen_1d20785795349f07___convert__closures_____invoke___bool__wasm_bindgen_1d20785795349f07___JsValue______true_(arg0, arg1, arg2, arg3);
}


const __wbindgen_enum_ReadableStreamType = ["bytes"];


const __wbindgen_enum_RequestCache = ["default", "no-store", "reload", "no-cache", "force-cache", "only-if-cached"];


const __wbindgen_enum_RequestCredentials = ["omit", "same-origin", "include"];


const __wbindgen_enum_RequestRedirect = ["follow", "error", "manual"];
const BrowserCacheMonitorFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browsercachemonitor_free(ptr, 1));
const BrowserCacheMonitorStartControlFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browsercachemonitorstartcontrol_free(ptr, 1));
const BrowserCacheMonitorStartStepFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browsercachemonitorstartstep_free(ptr, 1));
const BrowserCacheMonitorStartTerminalFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browsercachemonitorstartterminal_free(ptr, 1));
const BrowserCachedReadPublicationFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browsercachedreadpublication_free(ptr, 1));
const BrowserCoreClientFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browsercoreclient_free(ptr, 1));
const BrowserCoreStatusFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browsercorestatus_free(ptr, 1));
const BrowserDraftControlHandleFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserdraftcontrolhandle_free(ptr, 1));
const BrowserDraftPublicationHandleFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserdraftpublicationhandle_free(ptr, 1));
const BrowserDraftWriteHandleFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserdraftwritehandle_free(ptr, 1));
const BrowserIncomingPublicationFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserincomingpublication_free(ptr, 1));
const BrowserInitialSyncControlFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserinitialsynccontrol_free(ptr, 1));
const BrowserInitialSyncHandleFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserinitialsynchandle_free(ptr, 1));
const BrowserInitialSyncMetadataFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserinitialsyncmetadata_free(ptr, 1));
const BrowserOrdinaryLoginRetentionFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserordinaryloginretention_free(ptr, 1));
const BrowserOriginalPhysicalDraftInventoryFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browseroriginalphysicaldraftinventory_free(ptr, 1));
const BrowserOriginalRecoveryControlFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browseroriginalrecoverycontrol_free(ptr, 1));
const BrowserOriginalRecoveryHandleFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browseroriginalrecoveryhandle_free(ptr, 1));
const BrowserOriginalRecoveryPortFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browseroriginalrecoveryport_free(ptr, 1));
const BrowserOwnedMessageReadControlFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserownedmessagereadcontrol_free(ptr, 1));
const BrowserOwnedMessageReadHandleFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserownedmessagereadhandle_free(ptr, 1));
const BrowserOwnedMessageReadStepHandleFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserownedmessagereadstephandle_free(ptr, 1));
const BrowserOwnedMetadataContinuationHandleFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserownedmetadatacontinuationhandle_free(ptr, 1));
const BrowserOwnedPreparedSendFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserownedpreparedsend_free(ptr, 1));
const BrowserOwnedReadTerminalHandleFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserownedreadterminalhandle_free(ptr, 1));
const BrowserOwnedSendDriverFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserownedsenddriver_free(ptr, 1));
const BrowserOwnedSendResumeFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserownedsendresume_free(ptr, 1));
const BrowserOwnedSendStepFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserownedsendstep_free(ptr, 1));
const BrowserPreparedCacheMonitorFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserpreparedcachemonitor_free(ptr, 1));
const BrowserPreparedSendFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserpreparedsend_free(ptr, 1));
const BrowserProfileCacheAbsenceHandleFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserprofilecacheabsencehandle_free(ptr, 1));
const BrowserRecoveryBootstrapFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserrecoverybootstrap_free(ptr, 1));
const BrowserRecoveryRestoredClientFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browserrecoveryrestoredclient_free(ptr, 1));
const BrowserSendControlFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browsersendcontrol_free(ptr, 1));
const BrowserSendEventsFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browsersendevents_free(ptr, 1));
const BrowserSendTerminalFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_browsersendterminal_free(ptr, 1));
const IntoUnderlyingByteSourceFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_intounderlyingbytesource_free(ptr, 1));
const IntoUnderlyingSinkFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_intounderlyingsink_free(ptr, 1));
const IntoUnderlyingSourceFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_intounderlyingsource_free(ptr, 1));
const PreparedBrowserProfileFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_preparedbrowserprofile_free(ptr, 1));

function addToExternrefTable0(obj) {
    const idx = wasm.__externref_table_alloc();
    wasm.__wbindgen_externrefs.set(idx, obj);
    return idx;
}

function _assertClass(instance, klass) {
    if (!(instance instanceof klass)) {
        throw new Error(`expected instance of ${klass.name}`);
    }
}

const CLOSURE_DTORS = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(state => wasm.__wbindgen_destroy_closure(state.a, state.b));

function getArrayU8FromWasm0(ptr, len) {
    ptr = ptr >>> 0;
    return getUint8ArrayMemory0().subarray(ptr / 1, ptr / 1 + len);
}

let cachedDataViewMemory0 = null;
function getDataViewMemory0() {
    if (cachedDataViewMemory0 === null || cachedDataViewMemory0.buffer.detached === true || (cachedDataViewMemory0.buffer.detached === undefined && cachedDataViewMemory0.buffer !== wasm.memory.buffer)) {
        cachedDataViewMemory0 = new DataView(wasm.memory.buffer);
    }
    return cachedDataViewMemory0;
}

function getStringFromWasm0(ptr, len) {
    return decodeText(ptr >>> 0, len);
}

let cachedUint8ArrayMemory0 = null;
function getUint8ArrayMemory0() {
    if (cachedUint8ArrayMemory0 === null || cachedUint8ArrayMemory0.byteLength === 0) {
        cachedUint8ArrayMemory0 = new Uint8Array(wasm.memory.buffer);
    }
    return cachedUint8ArrayMemory0;
}

function handleError(f, args) {
    try {
        return f.apply(this, args);
    } catch (e) {
        const idx = addToExternrefTable0(e);
        wasm.__wbindgen_exn_store(idx);
    }
}

function isLikeNone(x) {
    return x === undefined || x === null;
}

function makeMutClosure(arg0, arg1, f) {
    const state = { a: arg0, b: arg1, cnt: 1 };
    const real = (...args) => {

        // First up with a closure we increment the internal reference
        // count. This ensures that the Rust closure environment won't
        // be deallocated while we're invoking it.
        state.cnt++;
        const a = state.a;
        state.a = 0;
        try {
            return f(a, state.b, ...args);
        } finally {
            state.a = a;
            real._wbg_cb_unref();
        }
    };
    real._wbg_cb_unref = () => {
        if (--state.cnt === 0) {
            wasm.__wbindgen_destroy_closure(state.a, state.b);
            state.a = 0;
            CLOSURE_DTORS.unregister(state);
        }
    };
    CLOSURE_DTORS.register(real, state, state);
    return real;
}

function passArray8ToWasm0(arg, malloc) {
    const ptr = malloc(arg.length * 1, 1) >>> 0;
    getUint8ArrayMemory0().set(arg, ptr / 1);
    WASM_VECTOR_LEN = arg.length;
    return ptr;
}

function passStringToWasm0(arg, malloc, realloc) {
    if (realloc === undefined) {
        const buf = cachedTextEncoder.encode(arg);
        const ptr = malloc(buf.length, 1) >>> 0;
        getUint8ArrayMemory0().subarray(ptr, ptr + buf.length).set(buf);
        WASM_VECTOR_LEN = buf.length;
        return ptr;
    }

    let len = arg.length;
    let ptr = malloc(len, 1) >>> 0;

    const mem = getUint8ArrayMemory0();

    let offset = 0;

    for (; offset < len; offset++) {
        const code = arg.charCodeAt(offset);
        if (code > 0x7F) break;
        mem[ptr + offset] = code;
    }
    if (offset !== len) {
        if (offset !== 0) {
            arg = arg.slice(offset);
        }
        ptr = realloc(ptr, len, len = offset + arg.length * 3, 1) >>> 0;
        const view = getUint8ArrayMemory0().subarray(ptr + offset, ptr + len);
        const ret = cachedTextEncoder.encodeInto(arg, view);

        offset += ret.written;
        ptr = realloc(ptr, len, offset, 1) >>> 0;
    }

    WASM_VECTOR_LEN = offset;
    return ptr;
}

function takeFromExternrefTable0(idx) {
    const value = wasm.__wbindgen_externrefs.get(idx);
    wasm.__externref_table_dealloc(idx);
    return value;
}

let cachedTextDecoder = new TextDecoder('utf-8', { ignoreBOM: true, fatal: true });
cachedTextDecoder.decode();
const MAX_SAFARI_DECODE_BYTES = 2146435072;
let numBytesDecoded = 0;
function decodeText(ptr, len) {
    numBytesDecoded += len;
    if (numBytesDecoded >= MAX_SAFARI_DECODE_BYTES) {
        cachedTextDecoder = new TextDecoder('utf-8', { ignoreBOM: true, fatal: true });
        cachedTextDecoder.decode();
        numBytesDecoded = len;
    }
    return cachedTextDecoder.decode(getUint8ArrayMemory0().subarray(ptr, ptr + len));
}

const cachedTextEncoder = new TextEncoder();

if (!('encodeInto' in cachedTextEncoder)) {
    cachedTextEncoder.encodeInto = function (arg, view) {
        const buf = cachedTextEncoder.encode(arg);
        view.set(buf);
        return {
            read: arg.length,
            written: buf.length
        };
    };
}

let WASM_VECTOR_LEN = 0;

let wasmModule, wasmInstance, wasm;
function __wbg_finalize_init(instance, module) {
    wasmInstance = instance;
    wasm = instance.exports;
    wasmModule = module;
    cachedDataViewMemory0 = null;
    cachedUint8ArrayMemory0 = null;
    wasm.__wbindgen_start();
    return wasm;
}

async function __wbg_load(module, imports) {
    if (typeof Response === 'function' && module instanceof Response) {
        if (!module.ok) {
            throw new Error(`failed to fetch Wasm: ${module.status} ${module.statusText} fetching '${module.url}'`);
        }

        if (typeof WebAssembly.instantiateStreaming === 'function') {
            try {
                return await WebAssembly.instantiateStreaming(module, imports);
            } catch (e) {
                const validResponse = expectedResponseType(module.type);

                if (validResponse && module.headers.get('Content-Type') !== 'application/wasm') {
                    console.warn("`WebAssembly.instantiateStreaming` failed because your server does not serve Wasm with `application/wasm` MIME type. Falling back to `WebAssembly.instantiate` which is slower. Original error:\n", e);

                } else { throw e; }
            }
        }

        const bytes = await module.arrayBuffer();
        return await WebAssembly.instantiate(bytes, imports);
    } else {
        const instance = await WebAssembly.instantiate(module, imports);

        if (instance instanceof WebAssembly.Instance) {
            return { instance, module };
        } else {
            return instance;
        }
    }

    function expectedResponseType(type) {
        switch (type) {
            case 'basic': case 'cors': case 'default': return true;
        }
        return false;
    }
}

function initSync(module) {
    if (wasm !== undefined) return wasm;


    if (module !== undefined) {
        if (Object.getPrototypeOf(module) === Object.prototype) {
            ({module} = module)
        } else {
            console.warn('using deprecated parameters for `initSync()`; pass a single object instead')
        }
    }

    const imports = __wbg_get_imports();
    if (!(module instanceof WebAssembly.Module)) {
        module = new WebAssembly.Module(module);
    }
    const instance = new WebAssembly.Instance(module, imports);
    return __wbg_finalize_init(instance, module);
}

async function __wbg_init(module_or_path) {
    if (wasm !== undefined) return wasm;


    if (module_or_path !== undefined) {
        if (Object.getPrototypeOf(module_or_path) === Object.prototype) {
            ({module_or_path} = module_or_path)
        } else {
            console.warn('using deprecated parameters for the initialization function; pass a single object instead')
        }
    }

    if (module_or_path === undefined) {
        module_or_path = new URL('openmates_browser_bg.wasm', import.meta.url);
    }
    const imports = __wbg_get_imports();

    if (typeof module_or_path === 'string' || (typeof Request === 'function' && module_or_path instanceof Request) || (typeof URL === 'function' && module_or_path instanceof URL)) {
        module_or_path = fetch(module_or_path);
    }

    const { instance, module } = await __wbg_load(await module_or_path, imports);

    return __wbg_finalize_init(instance, module);
}

export { initSync, __wbg_init as default };

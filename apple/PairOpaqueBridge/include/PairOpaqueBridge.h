#ifndef OPENMATES_PAIR_OPAQUE_BRIDGE_H
#define OPENMATES_PAIR_OPAQUE_BRIDGE_H

#ifdef __cplusplus
extern "C" {
#endif

// The returned JSON C string is owned by the bridge and must be released with
// pair_opaque_free. Inputs and outputs contain ephemeral secrets; callers must
// keep them in memory only and never log or persist them.
char *pair_opaque_call(const char *request_json);
void pair_opaque_free(char *response_json);

#ifdef __cplusplus
}
#endif

#endif

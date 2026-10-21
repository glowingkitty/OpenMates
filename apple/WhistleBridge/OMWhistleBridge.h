#ifndef OM_WHISTLE_BRIDGE_H
#define OM_WHISTLE_BRIDGE_H
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
// Only the pinned speech model is accepted. Negative returns are sanitized categories.
// Every call must go through WhistleNativeBridge.shared's single serial queue.
int om_whistle_load(const uint8_t *bytes, size_t count);
int om_whistle_transcribe(const float *pcm, int count, char *output, int capacity);
void om_whistle_end_session(void);
int om_whistle_model_resident(void);
// No unload/destroy exists in the pinned engine. Session end never reclaims the model.
#ifdef __cplusplus
}
#endif
#endif

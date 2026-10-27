// Whistle-only C facade. Do not link Python, its telemetry, or Needle LLM weights.
// Pinned upstream API: needle3 3391a1007e7db31d2fe5c69c734bbe93a9c1ce79.
#if OM_WHISTLE_NATIVE
#include "OMWhistleBridge.h"
#include "needle.h"
#include <cstring>
#include <cmath>

static bool modelResident = false;

int om_whistle_load(const uint8_t *bytes, size_t count) {
    if (modelResident) return 0;
    if (!bytes || count != 16919407) return -1;
    // The Swift asset boundary verifies SHA256 before exposing this pointer.
    try {
        if (needle_load(bytes, static_cast<unsigned long long>(count)) < 0) return -2;
        if (needle_models() != NEEDLE_SPEECH) return -2;
    } catch (...) { return -2; }
    modelResident = true;
    return 0;
}

int om_whistle_transcribe(const float *pcm, int count, char *output, int capacity) {
    if (!modelResident || !pcm || !output || count <= 0 || count > 16000 * 30 || capacity < 2) return -1;
    std::memset(output, 0, static_cast<size_t>(capacity));
    for (int i = 0; i < count; ++i) {
        if (!std::isfinite(pcm[i]) || pcm[i] < -1.0f || pcm[i] > 1.0f) return -1;
    }
    // Detection only; no tools, keywords, timestamps, text completion or networking.
    int result;
    try { result = needle_transcribe(pcm, count, nullptr, nullptr, 0, output, capacity); }
    catch (...) { std::memset(output, 0, static_cast<size_t>(capacity)); return -2; }
    // Upstream errors may include content. Never expose needle_last_error to logs/UI.
    if (result < 0) { std::memset(output, 0, static_cast<size_t>(capacity)); return -2; }
    if (!std::memchr(output, 0, static_cast<size_t>(capacity))) {
        std::memset(output, 0, static_cast<size_t>(capacity)); return -3;
    }
    return result;
}

void om_whistle_end_session(void) {
    // Official reset rewinds conversation; it is NOT a model unload or a promise
    // that native acoustic scratch is erased. App-owned PCM/output are short lived.
    if (modelResident) { try { needle_reset(); } catch (...) { /* Never cross the C ABI. */ } }
}
int om_whistle_model_resident(void) { return modelResident ? 1 : 0; }
#endif

#ifndef OPENMATES_POCKET_TTS_H
#define OPENMATES_POCKET_TTS_H
#include <stddef.h>
#include <stdint.h>
typedef struct OMPocketEngine OMPocketEngine;
typedef struct OMPocketAudio OMPocketAudio;
OMPocketEngine *om_pocket_create(const char *path);
OMPocketAudio *om_pocket_synthesize(OMPocketEngine *engine, const char *text);
const uint8_t *om_pocket_audio_bytes(const OMPocketAudio *audio);
size_t om_pocket_audio_count(const OMPocketAudio *audio);
void om_pocket_audio_free(OMPocketAudio *audio);
void om_pocket_destroy(OMPocketEngine *engine);
#endif

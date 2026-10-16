// OpenMates offline classifier adapter. Framed stdin/stdout; no text in logs.
#include "pf.h"
#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <linux/filter.h>
#include <linux/seccomp.h>

static bool deny_network() {
    sock_filter rules[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_socket, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_socketpair, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_connect, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    sock_fprog program{static_cast<unsigned short>(sizeof(rules) / sizeof(rules[0])), rules};
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) ||
        syscall(__NR_seccomp, SECCOMP_SET_MODE_FILTER, SECCOMP_FILTER_FLAG_TSYNC, &program)) return false;
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd >= 0) { close(fd); return false; }
    return errno == EPERM;
}

static bool read_frame(std::string &text) {
    unsigned char header[4];
    if (!std::cin.read(reinterpret_cast<char *>(header), 4)) return false;
    uint32_t length = (uint32_t(header[0]) << 24) | (uint32_t(header[1]) << 16) |
                      (uint32_t(header[2]) << 8) | header[3];
    if (length > 1024 * 1024) return false;
    text.resize(length);
    return length == 0 || bool(std::cin.read(text.data(), length));
}

static void write_frame(const std::string &json) {
    const uint32_t n = static_cast<uint32_t>(json.size());
    unsigned char header[] = {static_cast<unsigned char>(n >> 24), static_cast<unsigned char>(n >> 16),
                              static_cast<unsigned char>(n >> 8), static_cast<unsigned char>(n)};
    std::cout.write(reinterpret_cast<const char *>(header), 4);
    std::cout.write(json.data(), json.size());
    std::cout.flush();
}

int main(int argc, char **argv) {
    if (!deny_network()) return 70;
    if (argc == 2 && std::string(argv[1]) == "--self-test") {
        std::cout << "{\"network\":\"denied\",\"protocol\":1}\n";
        return 0;
    }
    if (argc != 3 || pf_abi_version() != 1) return 64;
    int threads = std::max(1, std::min(4, std::atoi(argv[2])));
    pf_ctx *ctx = pf_load(argv[1], "cpu", threads);
    if (!ctx || pf_last_error(ctx)) { pf_free(ctx); return 71; }
    pf_set_window(ctx, 4096); // Native overlap/halo covers the complete input.
    write_frame("{\"ready\":true}");
    std::string text;
    while (read_frame(text)) {
        pf_entity *entities = nullptr;
        size_t count = 0;
        if (pf_classify(ctx, text.data(), text.size(), 0.0f, &entities, &count)) {
            write_frame("{\"error\":\"privacy_model_failed\"}");
            pf_entities_free(entities, count);
            std::fill(text.begin(), text.end(), 0);
            continue;
        }
        std::string json = "{\"spans\":[";
        for (size_t i = 0; i < count; ++i) {
            if (i) json += ',';
            // Labels are the pinned runtime's fixed ASCII taxonomy, not user text.
            json += "{\"start\":" + std::to_string(entities[i].start) +
                    ",\"end\":" + std::to_string(entities[i].end) +
                    ",\"label\":\"" + std::string(entities[i].label) + "\"}";
        }
        json += "]}";
        pf_entities_free(entities, count);
        write_frame(json);
        std::fill(text.begin(), text.end(), '\0');
    }
    pf_free(ctx);
    return 0;
}

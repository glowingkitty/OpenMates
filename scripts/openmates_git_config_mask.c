#define _GNU_SOURCE

/* Managed by OpenMates remote-command AppArmor installer. */
/*
 * Compatibility shim for Git's repository-local configuration reads.
 *
 * AppArmor remains the security boundary and always denies the real Project
 * .git/config path.  This library only gives dynamically linked tools an
 * empty read view.  Bypassing or removing it therefore fails closed at the
 * kernel policy.  The target is compile-time fixed: environment variables,
 * argv, and Project files cannot broaden it.
 */

#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef OPENMATES_GIT_CONFIG_PATH
#define OPENMATES_GIT_CONFIG_PATH "/project/.git/config"
#endif

#define EMPTY_CONFIG_PATH "/dev/null"

static bool normalize_absolute_path(const char *input, char output[PATH_MAX + 1])
{
    size_t input_length;
    size_t output_length = 1;
    size_t index = 0;

    if (input == NULL || input[0] != '/')
        return false;
    input_length = strnlen(input, PATH_MAX + 1);
    if (input_length == 0 || input_length > PATH_MAX)
        return false;

    output[0] = '/';
    output[1] = '\0';
    while (index < input_length) {
        size_t start;
        size_t length;

        while (index < input_length && input[index] == '/')
            index++;
        start = index;
        while (index < input_length && input[index] != '/')
            index++;
        length = index - start;
        if (length == 0 || (length == 1 && input[start] == '.'))
            continue;
        if (length == 2 && input[start] == '.' && input[start + 1] == '.') {
            if (output_length > 1) {
                output_length--;
                while (output_length > 1 && output[output_length - 1] != '/')
                    output_length--;
                if (output_length > 1)
                    output_length--;
                output[output_length] = '\0';
            }
            continue;
        }
        if (output_length > 1) {
            if (output_length >= PATH_MAX)
                return false;
            output[output_length++] = '/';
        }
        if (length > PATH_MAX - output_length)
            return false;
        memcpy(output + output_length, input + start, length);
        output_length += length;
        output[output_length] = '\0';
    }
    return true;
}

static bool directory_path(int dirfd, char output[PATH_MAX + 1])
{
    if (dirfd == AT_FDCWD)
        return getcwd(output, PATH_MAX + 1) != NULL;

    char descriptor_path[64];
    int length = snprintf(descriptor_path, sizeof(descriptor_path), "/proc/self/fd/%d", dirfd);
    ssize_t resolved_length;

    if (length < 0 || (size_t)length >= sizeof(descriptor_path))
        return false;
    resolved_length = readlink(descriptor_path, output, PATH_MAX);
    if (resolved_length <= 0 || resolved_length > PATH_MAX)
        return false;
    output[resolved_length] = '\0';
    if (output[0] != '/' || strstr(output, " (deleted)") != NULL)
        return false;
    return true;
}

static bool is_masked_path_at(int dirfd, const char *path)
{
    char absolute[PATH_MAX + 1];
    char normalized[PATH_MAX + 1];

    if (path == NULL || path[0] == '\0')
        return false;
    if (path[0] == '/') {
        if (!normalize_absolute_path(path, normalized))
            return false;
    } else {
        char base[PATH_MAX + 1];
        int length;

        if (!directory_path(dirfd, base))
            return false;
        length = snprintf(absolute, sizeof(absolute), "%s/%s", base, path);
        if (length < 0 || (size_t)length >= sizeof(absolute))
            return false;
        if (!normalize_absolute_path(absolute, normalized))
            return false;
    }
    return strcmp(normalized, OPENMATES_GIT_CONFIG_PATH) == 0;
}

static bool read_only_open_flags(int flags)
{
    int mutation_flags = O_CREAT | O_TRUNC | O_APPEND;

#ifdef O_TMPFILE
    mutation_flags |= O_TMPFILE;
#endif
    return (flags & O_ACCMODE) == O_RDONLY && (flags & mutation_flags) == 0;
}

static bool read_only_fopen_mode(const char *mode)
{
    return mode != NULL && mode[0] == 'r' && strchr(mode, '+') == NULL;
}

static bool load_symbol(const char *name, void *destination, size_t destination_size)
{
    void *symbol;

    dlerror();
    symbol = dlsym(RTLD_NEXT, name);
    if (dlerror() != NULL || symbol == NULL || destination_size != sizeof(symbol)) {
        errno = ENOSYS;
        return false;
    }
    memcpy(destination, &symbol, sizeof(symbol));
    return true;
}

int access(const char *path, int mode)
{
    int (*next_access)(const char *, int);
    const char *effective = path;

    if ((mode & W_OK) == 0 && is_masked_path_at(AT_FDCWD, path))
        effective = EMPTY_CONFIG_PATH;
    if (!load_symbol("access", &next_access, sizeof(next_access)))
        return -1;
    return next_access(effective, mode);
}

int faccessat(int dirfd, const char *path, int mode, int flags)
{
    int (*next_faccessat)(int, const char *, int, int);
    const char *effective = path;
    int effective_dirfd = dirfd;

    if ((mode & W_OK) == 0 && is_masked_path_at(dirfd, path)) {
        effective = EMPTY_CONFIG_PATH;
        effective_dirfd = AT_FDCWD;
    }
    if (!load_symbol("faccessat", &next_faccessat, sizeof(next_faccessat)))
        return -1;
    return next_faccessat(effective_dirfd, effective, mode, flags);
}

int faccessat2(int dirfd, const char *path, int mode, int flags)
{
    int (*next_faccessat2)(int, const char *, int, int);
    const char *effective = path;
    int effective_dirfd = dirfd;

    if ((mode & W_OK) == 0 && is_masked_path_at(dirfd, path)) {
        effective = EMPTY_CONFIG_PATH;
        effective_dirfd = AT_FDCWD;
    }
    if (!load_symbol("faccessat2", &next_faccessat2, sizeof(next_faccessat2))) {
#ifdef SYS_faccessat2
        return (int)syscall(SYS_faccessat2, effective_dirfd, effective, mode, flags);
#else
        return -1;
#endif
    }
    return next_faccessat2(effective_dirfd, effective, mode, flags);
}

FILE *fopen(const char *path, const char *mode)
{
    FILE *(*next_fopen)(const char *, const char *);
    const char *effective = path;

    if (read_only_fopen_mode(mode) && is_masked_path_at(AT_FDCWD, path))
        effective = EMPTY_CONFIG_PATH;
    if (!load_symbol("fopen", &next_fopen, sizeof(next_fopen)))
        return NULL;
    return next_fopen(effective, mode);
}

FILE *fopen64(const char *path, const char *mode)
{
    FILE *(*next_fopen64)(const char *, const char *);
    const char *effective = path;

    if (read_only_fopen_mode(mode) && is_masked_path_at(AT_FDCWD, path))
        effective = EMPTY_CONFIG_PATH;
    if (!load_symbol("fopen64", &next_fopen64, sizeof(next_fopen64)))
        return NULL;
    return next_fopen64(effective, mode);
}

static int call_open_symbol(const char *symbol, const char *path, int flags, va_list arguments)
{
    int (*next_open)(const char *, int, ...);
    bool needs_mode = (flags & O_CREAT) != 0;
    mode_t mode = 0;

#ifdef O_TMPFILE
    needs_mode = needs_mode || (flags & O_TMPFILE) == O_TMPFILE;
#endif
    if (needs_mode)
        mode = (mode_t)va_arg(arguments, int);
    if (!load_symbol(symbol, &next_open, sizeof(next_open)))
        return -1;
    if (needs_mode)
        return next_open(path, flags, mode);
    return next_open(path, flags);
}

int open(const char *path, int flags, ...)
{
    const char *effective = path;
    va_list arguments;
    int result;

    if (read_only_open_flags(flags) && is_masked_path_at(AT_FDCWD, path))
        effective = EMPTY_CONFIG_PATH;
    va_start(arguments, flags);
    result = call_open_symbol("open", effective, flags, arguments);
    va_end(arguments);
    return result;
}

int open64(const char *path, int flags, ...)
{
    const char *effective = path;
    va_list arguments;
    int result;

    if (read_only_open_flags(flags) && is_masked_path_at(AT_FDCWD, path))
        effective = EMPTY_CONFIG_PATH;
    va_start(arguments, flags);
    result = call_open_symbol("open64", effective, flags, arguments);
    va_end(arguments);
    return result;
}

static int call_openat_symbol(
    const char *symbol, int dirfd, const char *path, int flags, va_list arguments
)
{
    int (*next_openat)(int, const char *, int, ...);
    bool needs_mode = (flags & O_CREAT) != 0;
    mode_t mode = 0;

#ifdef O_TMPFILE
    needs_mode = needs_mode || (flags & O_TMPFILE) == O_TMPFILE;
#endif
    if (needs_mode)
        mode = (mode_t)va_arg(arguments, int);
    if (!load_symbol(symbol, &next_openat, sizeof(next_openat)))
        return -1;
    if (needs_mode)
        return next_openat(dirfd, path, flags, mode);
    return next_openat(dirfd, path, flags);
}

int openat(int dirfd, const char *path, int flags, ...)
{
    const char *effective = path;
    int effective_dirfd = dirfd;
    va_list arguments;
    int result;

    if (read_only_open_flags(flags) && is_masked_path_at(dirfd, path)) {
        effective = EMPTY_CONFIG_PATH;
        effective_dirfd = AT_FDCWD;
    }
    va_start(arguments, flags);
    result = call_openat_symbol("openat", effective_dirfd, effective, flags, arguments);
    va_end(arguments);
    return result;
}

int openat64(int dirfd, const char *path, int flags, ...)
{
    const char *effective = path;
    int effective_dirfd = dirfd;
    va_list arguments;
    int result;

    if (read_only_open_flags(flags) && is_masked_path_at(dirfd, path)) {
        effective = EMPTY_CONFIG_PATH;
        effective_dirfd = AT_FDCWD;
    }
    va_start(arguments, flags);
    result = call_openat_symbol("openat64", effective_dirfd, effective, flags, arguments);
    va_end(arguments);
    return result;
}

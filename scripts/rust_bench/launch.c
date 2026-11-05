/*
 * rust_bench launcher: run one command tree and report wall/CPU/max-RSS as JSON.
 *
 * Why C: a child forked from the Python harness inherits Python's resident
 * pages, and Linux folds that high-water mark into ru_maxrss across exec. This
 * launcher is tiny, forks the target from itself, becomes a child subreaper so
 * orphaned/daemonized descendants re-parent to it, reaps every process with
 * wait4() and sums their CPU. Max RSS is the largest single-process ru_maxrss.
 *
 * usage: launch <result-fd> <cgroup.procs|-> <stdout> <stderr> <cwd|-> <timeout-ms> -- argv...
 * The target inherits this process's environment (set by the harness).
 * Wall time = fork of the target -> reap of the target (not of later orphans).
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t alarmed = 0;
static void on_alarm(int sig) { (void)sig; alarmed = 1; }

static long long now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static void arm_timer(long ms) {
    struct itimerval it = {{0, 0}, {ms / 1000, (ms % 1000) * 1000}};
    setitimer(ITIMER_REAL, &it, NULL);
}

/* SIGKILL every direct child (as subreaper, all orphans are direct children). */
static int kill_children(void) {
    int killed = 0;
    pid_t self = getpid();
    DIR *proc = opendir("/proc");
    if (!proc) return 0;
    struct dirent *entry;
    while ((entry = readdir(proc))) {
        char path[64], buf[512];
        if (entry->d_name[0] < '0' || entry->d_name[0] > '9') continue;
        snprintf(path, sizeof path, "/proc/%s/stat", entry->d_name);
        int fd = open(path, O_RDONLY);
        if (fd < 0) continue;
        ssize_t n = read(fd, buf, sizeof buf - 1);
        close(fd);
        if (n <= 0) continue;
        buf[n] = 0;
        char *end = strrchr(buf, ')');
        int ppid = 0;
        if (end && sscanf(end + 2, "%*c %d", &ppid) == 1 && ppid == self) {
            if (kill(atoi(entry->d_name), SIGKILL) == 0) killed++;
        }
    }
    closedir(proc);
    return killed;
}

int main(int argc, char **argv) {
    if (argc < 9 || strcmp(argv[7], "--") != 0) {
        fprintf(stderr, "usage: launch <result-fd> <procs|-> <stdout> <stderr> <cwd|-> <timeout-ms> -- argv...\n");
        return 125;
    }
    int result_fd = atoi(argv[1]);
    const char *procs = argv[2], *out = argv[3], *err = argv[4], *cwd = argv[5];
    long timeout_ms = atol(argv[6]);
    char **target = &argv[8];

    if (prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0) { perror("prctl"); return 125; }
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_alarm; /* no SA_RESTART: wait4 returns EINTR */
    sigaction(SIGALRM, &sa, NULL);

    long long start = now_ns();
    pid_t main_pid = fork();
    if (main_pid < 0) { perror("fork"); return 125; }
    if (main_pid == 0) {
        if (strcmp(procs, "-") != 0) {
            int fd = open(procs, O_WRONLY);
            if (fd < 0 || write(fd, "0", 1) != 1) { perror("cgroup join"); _exit(126); }
            close(fd);
        }
        setpgid(0, 0);
        int in = open("/dev/null", O_RDONLY);
        int o = open(out, O_WRONLY | O_CREAT | O_TRUNC, 0600);
        int e = open(err, O_WRONLY | O_CREAT | O_TRUNC, 0600);
        if (in < 0 || o < 0 || e < 0) { perror("open"); _exit(126); }
        dup2(in, 0); dup2(o, 1); dup2(e, 2);
        close(in); close(o); close(e); close(result_fd);
        if (strcmp(cwd, "-") != 0 && chdir(cwd) != 0) { perror("chdir"); _exit(126); }
        execvp(target[0], target);
        perror("exec");
        _exit(127);
    }

    long long wall_ns = -1, cpu_user_us = 0, cpu_sys_us = 0;
    long max_rss = 0;
    int exit_code = -1, timed_out = 0, reaped = 0, killed = 0, alarms = 0;
    arm_timer(timeout_ms);
    for (;;) {
        int status;
        struct rusage ru;
        pid_t pid = wait4(-1, &status, 0, &ru);
        if (pid < 0 && errno == ECHILD) break;
        if (pid < 0 && errno == EINTR) {
            if (!alarmed) continue;
            alarmed = 0;
            if (wall_ns < 0) timed_out = 1;
            if (++alarms > 20) break;
            killed += kill_children();
            arm_timer(500);
            continue;
        }
        if (pid < 0) { perror("wait4"); break; }
        reaped++;
        cpu_user_us += (long long)ru.ru_utime.tv_sec * 1000000 + ru.ru_utime.tv_usec;
        cpu_sys_us += (long long)ru.ru_stime.tv_sec * 1000000 + ru.ru_stime.tv_usec;
        if (ru.ru_maxrss > max_rss) max_rss = ru.ru_maxrss;
        if (pid == main_pid) {
            wall_ns = now_ns() - start;
            exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
            arm_timer(5000); /* grace for leftover descendants, then SIGKILL */
        }
    }
    arm_timer(0);
    dprintf(result_fd,
            "{\"exitCode\":%d,\"timedOut\":%s,\"wallNs\":%lld,\"cpuUserUs\":%lld,\"cpuSystemUs\":%lld,"
            "\"maxRssKiB\":%ld,\"processesReaped\":%d,\"leftoversKilled\":%d,\"complete\":%s}\n",
            exit_code, timed_out ? "true" : "false", wall_ns, cpu_user_us, cpu_sys_us, max_rss, reaped,
            killed, alarms > 20 ? "false" : "true");
    return 0;
}

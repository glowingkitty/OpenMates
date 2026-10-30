/* Benchmark-only Linux process meter. An exec before this fork isolates the
 * measured child's RSS floor from the Python harness's heap/high-water RSS.
 * The measurement fd is private to the harness; the application never sees it.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

static int legacy(int argc, char **argv) {
    if (argc < 3) return 125;
    char *end = NULL;
    long number = strtol(argv[1], &end, 10);
    if (!end || *end || number < 3 || number > 1048576) return 125;
    int fd = (int)number;
    int ready[2];
    if (pipe(ready) != 0) return 125;
    pid_t child = fork();
    if (child < 0) return 125;
    if (child == 0) {
        close(ready[1]);
        char byte;
        ssize_t received;
        do { received = read(ready[0], &byte, 1); } while (received < 0 && errno == EINTR);
        close(ready[0]);
        if (received != 1) _exit(125);
        close(fd);
        execvp(argv[2], &argv[2]);
        perror("benchmark application exec");
        _exit(127);
    }
    close(ready[0]);
    if (dprintf(fd, "{\"pid\":%ld}\n", (long)child) < 0) return 125;
    if (write(ready[1], "1", 1) != 1) return 125;
    close(ready[1]);
    int status;
    struct rusage usage;
    pid_t waited;
    do {
        waited = wait4(child, &status, 0, &usage);
    } while (waited < 0 && errno == EINTR);
    if (waited != child) return 125;
    int code = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
    if (dprintf(fd,
        "{\"exitCode\":%d,\"cpuUserMs\":%.3f,\"cpuSystemMs\":%.3f,\"peakRssKiB\":%ld}\n",
        code, usage.ru_utime.tv_sec * 1000.0 + usage.ru_utime.tv_usec / 1000.0,
        usage.ru_stime.tv_sec * 1000.0 + usage.ru_stime.tv_usec / 1000.0,
        usage.ru_maxrss) < 0) return 125;
    close(fd);
    return code;
}

#if defined(__linux__)
/* Owned mode is Linux-only and deliberately bounded. A fresh subreaper owns no
 * unrelated children. Kernel wait4 accounting partitions reaped roots; sampled
 * proc counters are used only for live idle snapshots, never lifetime totals. */
#include <dirent.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#define LIMIT 4096
struct identity { pid_t pid, parent; unsigned long long birth, own, waited, rss; int handle; };
static struct identity owned[LIMIT];
static int count;
#ifdef OWNED_METER_TEST
static int (*test_identity_read)(pid_t, struct identity *);
static int (*test_handle_open)(pid_t);
static int (*test_handle_live)(int);
static void (*test_handle_signal)(int);
#endif
static int handle_open(pid_t pid) {
#ifdef OWNED_METER_TEST
    if(test_handle_open)return test_handle_open(pid);
#endif
    return (int)syscall(SYS_pidfd_open,pid,0);
}
static int handle_live(int handle) {
#ifdef OWNED_METER_TEST
    if(test_handle_live)return test_handle_live(handle);
#endif
    struct pollfd descriptor={handle,POLLIN,0};
    return poll(&descriptor,1,0)==0;
}
static void handle_kill(int handle) {
#ifdef OWNED_METER_TEST
    if(test_handle_signal){test_handle_signal(handle);return;}
#endif
    syscall(SYS_pidfd_send_signal,handle,SIGKILL,NULL,0);
}
static volatile sig_atomic_t cancelled;
static void cancel_handler(int sig) { (void)sig; cancelled = 1; }
static long long now_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return (long long)t.tv_sec*1000000000LL+t.tv_nsec; }
static int read_identity(pid_t pid, struct identity *out) {
#ifdef OWNED_METER_TEST
    if(test_identity_read)return test_identity_read(pid,out);
#endif
    char path[64], data[4096];
    snprintf(path,sizeof(path),"/proc/%ld/stat",(long)pid);
    int fd=open(path,O_RDONLY|O_CLOEXEC); if(fd<0) return 0;
    ssize_t n=read(fd,data,sizeof(data)-1); int saved=errno; close(fd); if(n==0||(n<0&&(saved==ESRCH||saved==ENOENT)))return 0; if(n<0||n==(ssize_t)sizeof(data)-1)return -1;
    data[n]=0; char *p=strrchr(data,')'); if(!p||p[1]!=' ')return -1;
    char *save=NULL, *v=strtok_r(p+2," ",&save); unsigned long long vals[22]={0}; int field=3;
    while(v&&field<=24) {if(field!=3) {char *e; vals[field-3]=strtoull(v,&e,10); if(*e&&*e!='\n')return -1;} v=strtok_r(NULL," ",&save);field++;}
    if(field!=25)return -1;
    snprintf(path,sizeof(path),"/proc/%ld/status",(long)pid);
    FILE *status=fopen(path,"r");if(!status)return errno==ENOENT?0:-1;
    unsigned uid=~0U;char line[256];while(fgets(line,sizeof(line),status))if(sscanf(line,"Uid: %u",&uid)==1)break;
    fclose(status);if(uid!=(unsigned)getuid())return -1;
    *out=(struct identity){.pid=pid,.parent=(pid_t)vals[1],.birth=vals[19],.own=vals[11]+vals[12],.waited=vals[13]+vals[14],.rss=vals[21],.handle=-1}; return 1;
}
static int index_of(pid_t pid) {for(int i=0;i<count;i++)if(owned[i].handle>=0&&owned[i].pid==pid)return i;return -1;}
/* Only a currently live captured parent can prove indirect ancestry. Historical
 * numeric PIDs are never authority, including the original application PID. */
static int parent_owned(pid_t parent) {
    if(parent==getpid())return 1;
    int i=index_of(parent);if(i<0)return 0;
    struct identity current;
    return handle_live(owned[i].handle)&&read_identity(parent,&current)==1&&current.birth==owned[i].birth;
}
static int register_candidate(const struct identity *candidate) {
    int i=index_of(candidate->pid);
    if(i>=0)return owned[i].birth==candidate->birth?0:-1;
    if(!parent_owned(candidate->parent))return 0;
    if(count==LIMIT)return -1;
    /* Recheck ancestry before acquiring any child handle. Then pin the child's
     * identity and recheck parent/birth after open to close registration races. */
    struct identity before;
    if(read_identity(candidate->pid,&before)!=1||before.birth!=candidate->birth||before.parent!=candidate->parent||!parent_owned(before.parent))return -1;
    int h=handle_open(candidate->pid);if(h<0)return errno==ESRCH?0:-1;
    struct identity check;
    if(read_identity(candidate->pid,&check)!=1||check.birth!=before.birth||check.parent!=before.parent||!parent_owned(check.parent)){close(h);return -1;}
    owned[count]=check;owned[count++].handle=h;return 1;
}
static int census(void) {
    struct identity all[LIMIT]; int n=0; DIR *dir=opendir("/proc"); if(!dir)return -1;
    struct dirent *entry; int visited=0;
    while((entry=readdir(dir))) { if(++visited>65536){closedir(dir);return -1;} char *end; long p=strtol(entry->d_name,&end,10); if(*end||p<=0)continue;
        if(n==LIMIT){closedir(dir);return -1;} int r=read_identity((pid_t)p,&all[n]); if(r<0&&index_of((pid_t)p)>=0){closedir(dir);return -1;} if(r==1)n++;
    } closedir(dir);
    int changed=1;
    while(changed) {changed=0;for(int j=0;j<n;j++) {
        int registered=register_candidate(&all[j]);if(registered<0)return -1;
        if(registered)changed=1;
    }} return 0;
}
static void terminate_owned(void) {for(int i=0;i<count;i++)if(owned[i].handle>=0)handle_kill(owned[i].handle);}
static int snapshot(int fd,unsigned seq,double reaped) {
    int prior=count;
    if(census()||count!=prior)return -1;
    struct identity first[LIMIT],second[LIMIT]; int live=0; unsigned long long ticks=0,rss=0;
    for(int i=0;i<count;i++) {if(owned[i].handle<0)continue;int r=read_identity(owned[i].pid,&first[live]);if(r<0)return -1;if(!r)continue;
        if(first[live].birth!=owned[i].birth)return -1;
        if(!parent_owned(first[live].parent))return -1;
        live++;}
    for(int i=0;i<live;i++) {if(read_identity(first[i].pid,&second[i])!=1||first[i].birth!=second[i].birth||first[i].parent!=second[i].parent||first[i].waited!=second[i].waited)return -1;
        ticks+=second[i].own+second[i].waited;if(second[i].rss>rss)rss=second[i].rss;}
    if(census()||count!=prior)return -1;
    return dprintf(fd,"{\"snapshot\":%u,\"cpuMs\":%.3f,\"rssKiB\":%llu,\"ownedCount\":%d,\"status\":\"complete\"}\n",seq,reaped+ticks*1000.0/sysconf(_SC_CLK_TCK),rss*(unsigned long long)sysconf(_SC_PAGESIZE)/1024,live)<0?-1:0;
}
int main(int argc,char **argv) {
    if(argc<3||strcmp(argv[2],"--owned-tree-v2"))return legacy(argc,argv);
    if(argc<7||strcmp(argv[5],"--")||(strcmp(argv[3],"rust-leaf")&&strcmp(argv[3],"pinned-typescript-owned-tree")))return 125;
    char *end; long f=strtol(argv[1],&end,10);if(*end||f<3||f>1048576)return 125;int fd=(int)f;
    long c=strtol(argv[4],&end,10);if(*end||c<3||c>1048576||c==f)return 125;int control=(int)c;
    if(prctl(PR_SET_CHILD_SUBREAPER,1))return 125;
    struct sigaction action={0};action.sa_handler=cancel_handler;sigaction(SIGINT,&action,NULL);sigaction(SIGTERM,&action,NULL);
    fcntl(control,F_SETFL,O_NONBLOCK);
    long long launched=now_ns(), deadline=launched+1000000000LL; int supplied=0;char buffer[256];size_t used=0;
    pid_t root=-1;int root_code=125,root_done=0,adopted=0,empty=0;double user=0,system=0;long peak=0;const char *failure=NULL;
    while(!supplied&&now_ns()<deadline&&!cancelled) {
        struct pollfd p={control,POLLIN,0};poll(&p,1,1);char ch;ssize_t n=read(control,&ch,1);
        if(n==1){if(used>=sizeof(buffer)-1){failure="control";break;}buffer[used++]=ch;if(ch=='\n'){buffer[used]=0;long long d;char extra;if(sscanf(buffer,"D %lld %c",&d,&extra)!=1||d<=now_ns()){failure="deadline";break;}deadline=d;supplied=1;}}
        else if(n==0){failure="control";break;}
    }
    if(!supplied||cancelled) return 125;
    int ready[2];if(pipe(ready))return 125;root=fork();if(root<0)return 125;
    if(!root){close(ready[1]);close(control);close(fd);char b;if(read(ready[0],&b,1)!=1)_exit(125);close(ready[0]);signal(SIGINT,SIG_DFL);signal(SIGTERM,SIG_DFL);execvp(argv[6],argv+6);_exit(127);}
    close(ready[0]);if(census())failure="ownership";
    int root_index=index_of(root);
    if(root_index<0||dprintf(fd,"{\"pid\":%ld,\"birth\":%llu}\n",(long)root,root_index<0?0:owned[root_index].birth)<0)failure="ownership";
    /* The private birth anchor is captured while root is still blocked. Never
     * release an application whose initial ownership proof could not be made. */
    if(!failure&&write(ready[1],"1",1)!=1)failure="ownership";
    close(ready[1]);fcntl(control,F_SETFL,O_NONBLOCK);used=0;
    while(now_ns()<deadline) {
        if(census())failure="ownership";
        if(!strcmp(argv[3],"rust-leaf")) {
            struct identity current;
            if(count>1||(read_identity(root,&current)==1&&current.waited))failure="native-descendant";
        }
        if(cancelled)failure="cancelled";
        if(now_ns()>=deadline-200000000LL&&!failure)failure="deadline";
        if(failure)terminate_owned();
        int status;struct rusage usage;pid_t pid;
        while((pid=wait4(-1,&status,WNOHANG,&usage))>0) {
            int i=index_of(pid);if(i<0)failure="ownership";else {close(owned[i].handle);owned[i].handle=-1;}
            if(pid==root){root_done=1;root_code=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);}else adopted++;
            user+=usage.ru_utime.tv_sec*1000.0+usage.ru_utime.tv_usec/1000.0;system+=usage.ru_stime.tv_sec*1000.0+usage.ru_stime.tv_usec/1000.0;if(usage.ru_maxrss>peak)peak=usage.ru_maxrss;
        }
        if(pid<0&&errno==ECHILD){empty=1;break;}if(pid<0&&errno!=EINTR)failure="wait";
        char ch;ssize_t n;
        while((n=read(control,&ch,1))==1){if(used>=sizeof(buffer)-1){failure="control";used=0;break;}buffer[used++]=ch;if(ch=='\n'){buffer[used]=0;long long d;unsigned seq;char extra;
            if(sscanf(buffer,"D %lld %c",&d,&extra)==1&&d>now_ns())deadline=d;
            else if(sscanf(buffer,"S %u %c",&seq,&extra)==1){if(census()||snapshot(fd,seq,user+system))failure="snapshot";}
            else failure="control";
            used=0;}}
        struct pollfd p={control,POLLIN,0};poll(&p,1,1);
    }
    if(!empty||!root_done){failure="cleanup";terminate_owned();}
    int clean=empty&&root_done;
    dprintf(fd,"{\"exitCode\":%d,\"cpuUserMs\":%.3f,\"cpuSystemMs\":%.3f,\"peakRssKiB\":%ld,\"method\":\"owned-tree-v2\",\"processAccounting\":\"%s\",\"cpuScope\":\"kernel-waited-forest\",\"rssScope\":\"largest-waited-process-hwm-kib\",\"ownedShutdownConfirmed\":%s,\"adoptedReapCount\":%d,\"accountingStatus\":\"%s\"}\n",root_code,user,system,peak,argv[3],clean?"true":"false",adopted,failure?failure:"complete");
    close(fd);close(control);return failure?125:root_code;
}

#else
#include <string.h>
int main(int argc, char **argv) {
    if (argc >= 3 && strcmp(argv[2], "--owned-tree-v2") == 0) return 125;
    return legacy(argc, argv);
}
#endif

/* Private finite successor. Original V2 entry and source remain byte-preserved.
 * No commands, argv contents, stdin, credentials, memory contents or paths enter
 * receipts. Ptrace reads syscall numbers/clone flags only, never syscall strings.
 */
#define main owned_v2_main
#include "ci_client_process_meter_original.c"
#undef main
#if defined(__linux__)
#include <sys/ptrace.h>
#include <linux/ptrace.h>
#include <linux/sched.h>
#include <linux/audit.h>
#include <stddef.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/vfs.h>
#include <sys/ioctl.h>
#include <linux/magic.h>
#include <linux/nsfs.h>
#define M_MAX_TASKS 4096
#define M_MAX_EVENTS 2000000ULL
#define M_MAX_MARKERS 64
struct m_task {
    pid_t tid, tgid;
    unsigned long long birth;
    int live, initial, creator, creating, creation_event, handle;
};
static struct m_task m_tasks[M_MAX_TASKS];
static int m_n, m_processes, m_threads, m_execs, m_root_done;
/* Set only after the separate inherited-kernel-FD admission below. Never env. */
static int m_contained_verified, m_contained_nsfd=-1;
static unsigned long long m_contained_nsdev,m_contained_nsino;
static unsigned m_contained_clone3_entries,m_contained_clone3_events;
static int m_gate_forest_fds(int measurement,int control,int ns);
static unsigned long long m_events;
static const char *m_unknown, *m_failure;
static pid_t m_root;
static int m_initial_handle=-1;
static pid_t m_pending[M_MAX_TASKS];
static int m_pending_count;
static unsigned m_fork_events,m_vfork_events,m_clone_events,m_untraced_refusals,m_clone3_refusals,m_x32_refusals,m_signal_stops,m_group_stops,m_cancel_observed,m_deadline_observed;
static int m_resume(pid_t tid,int sig);
static long m_peak;
static struct rusage m_usage;
static int m_root_code=125;
static void m_unavailable(const char *code) { if(!m_unknown)m_unknown=code; }
static void m_fail(const char *code) { if(!m_failure)m_failure=code; m_unavailable(code); }
static int m_index(pid_t tid) { for(int i=0;i<m_n;i++)if(m_tasks[i].tid==tid&&m_tasks[i].live)return i;return -1; }
static int m_tgid(pid_t tid, pid_t *tgid) {
    char path[64],line[256];snprintf(path,sizeof(path),"/proc/%ld/status",(long)tid);
    FILE *f=fopen(path,"r");if(!f)return -1;
    unsigned long value=0;int found=0;
    while(fgets(line,sizeof(line),f))if(sscanf(line,"Tgid: %lu",&value)==1){found=1;break;}
    fclose(f);if(!found||!value||value>2147483647UL)return -1;*tgid=(pid_t)value;return 0;
}
static int m_add(pid_t tid, int creator, int kind) {
    if(tid<=0||m_n==M_MAX_TASKS||m_index(tid)>=0)return -1;
    struct identity id;pid_t tgid;
    if(read_identity(tid,&id)!=1||m_tgid(tid,&tgid))return -1;
    if(kind==1&&tgid!=m_root)return -1;
    /* Contained clone3 never trusts mutable input flags. Kernel birth/Tgid and
     * matching ptrace event/initial stop are the only child identity source. */
    if(kind==3&&(!m_contained_verified||creator<0||creator>=m_n||
       (tid!=tgid&&tgid!=m_tasks[creator].tgid)))return -1;
    int handle=-1;
    if(tid==tgid){handle=handle_open(tid);if(handle<0)return -1;m_processes++;}
    else m_threads++;
    m_tasks[m_n]=(struct m_task){.tid=tid,.tgid=tgid,.birth=id.birth,.live=1,.initial=1,.creator=creator,.handle=handle};
    int added=m_n++;
    for(int j=0;j<m_pending_count;j++)if(m_pending[j]==tid){
        m_pending[j]=m_pending[--m_pending_count];m_tasks[added].initial=0;
        if(m_resume(tid,0)<0)return -1;
        break;
    }
    return added;
}
static int m_held(int i) {
    if(i<0||i>=m_n||!m_tasks[i].live)return 0;
    struct identity id;
    return read_identity(m_tasks[i].tid,&id)==1&&id.birth==m_tasks[i].birth;
}
static void m_kill_all(void) {
    if(!m_root_done){if(m_initial_handle>=0)handle_kill(m_initial_handle);else kill(m_root,SIGKILL);}
    /* Pending TIDs are unreaped kernel wait-stop children of this fresh tracer,
     * never arbitrary process-table PIDs. Creation proof is still unavailable. */
    for(int j=0;j<m_pending_count;j++)ptrace(PTRACE_CONT,m_pending[j],0,(void *)(long)SIGKILL);
    for(int i=0;i<m_n;i++)if(m_tasks[i].live&&m_tasks[i].handle>=0)handle_kill(m_tasks[i].handle);
}
static int m_resume(pid_t tid,int sig) {
    return ptrace(PTRACE_SYSCALL,tid,0,(void *)(long)sig)<0?-1:0;
}
static int m_native_arch(unsigned int arch) {
#if defined(__aarch64__)
    return arch==AUDIT_ARCH_AARCH64;
#elif defined(__x86_64__)
    return arch==AUDIT_ARCH_X86_64;
#else
    (void)arch;return 0;
#endif
}
/* x32 shares AUDIT_ARCH_X86_64 but tags syscall numbers with bit30.
 * Reject at ENTRY before dispatch/resume: native SYS_clone matching alone
 * would miss an x32 creation call, including CLONE_UNTRACED. */
static int m_native_syscall_nr(unsigned long long nr) {
#if defined(__x86_64__)
    return (nr & 0x40000000ULL)==0;
#else
    (void)nr;return 1;
#endif
}
static int m_creation(unsigned long long nr, unsigned long long *flags,
                      const struct ptrace_syscall_info *info) {
    *flags=0;(void)info;
#ifdef SYS_clone
    if(nr==SYS_clone){*flags=info->entry.args[0];return 1;}
#endif
#ifdef SYS_clone3
    if(nr==SYS_clone3){
        /* clone3 reads pointed-to memory after this stop. Another thread may
         * mutate flags before the kernel consumes them; a one-time PEEKDATA
         * read would not prove absence of CLONE_UNTRACED. No execution/repair
         * of this syscall is authorized by this finite observer. */
        if(m_contained_verified){m_contained_clone3_entries++;return 3;}
        return -2;
    }
#endif
#ifdef SYS_fork
    if(nr==SYS_fork)return 1;
#endif
#ifdef SYS_vfork
    if(nr==SYS_vfork)return 1;
#endif
    return 0;
}
static int m_syscall(int i) {
    struct ptrace_syscall_info info;memset(&info,0,sizeof(info));
    long size=ptrace(PTRACE_GET_SYSCALL_INFO,m_tasks[i].tid,(void *)sizeof(info),&info);
    if(size<0||!m_native_arch(info.arch)){m_fail("syscall-observation-unavailable");return -1;}
    if(info.op==PTRACE_SYSCALL_INFO_ENTRY){
        if(size<(long)(offsetof(struct ptrace_syscall_info,entry.args)+sizeof(info.entry.args))){m_fail("truncated-syscall-entry");return -1;}
        if(!m_native_syscall_nr(info.entry.nr)){m_x32_refusals++;m_fail("x32-syscall-abi-unsupported");return -1;}
        unsigned long long flags=0;int creation=m_creation(info.entry.nr,&flags,&info);
        if(creation<0){if(creation==-2)m_clone3_refusals++;m_fail(creation==-2?"clone3-mutable-flags-unsupported":"clone-flags-unavailable");return -1;}
        if(creation){
            /* TRACECLONE alone does not cover CLONE_UNTRACED. Observe and refuse
             * that request at syscall ENTRY, before an untraced child can exist. */
            if(flags&CLONE_UNTRACED){m_untraced_refusals++;m_fail("untraced-clone-refused");return -1;}
            if(flags&CLONE_NEWPID){m_fail("pid-namespace-clone-unsupported");return -1;}
            m_tasks[i].creating=creation==3?3:(flags&CLONE_THREAD)&&(flags&CLONE_VM)?1:2;
            m_tasks[i].creation_event=0;
        }
    }else if(info.op==PTRACE_SYSCALL_INFO_EXIT){
        if(size<(long)(offsetof(struct ptrace_syscall_info,exit.is_error)+sizeof(info.exit.is_error))){m_fail("truncated-syscall-exit");return -1;}
        if(m_tasks[i].creating&&info.exit.rval>=0&&!m_tasks[i].creation_event){m_fail("missing-creation-event");return -1;}
        m_tasks[i].creating=0;m_tasks[i].creation_event=0;
    }else {m_fail("unknown-syscall-stop");return -1;}
    return 0;
}
static int m_exec(int i) {
    unsigned long former=0;
    if(ptrace(PTRACE_GETEVENTMSG,m_tasks[i].tid,0,&former)<0){m_fail("exec-event-unavailable");return -1;}
    m_execs++;
    if(former&&(pid_t)former!=m_tasks[i].tid){m_fail("thread-exec-transition-unsupported");return -1;}
    if(m_execs>1)m_unavailable("multiple-exec-images");
    return 0;
}
static int m_event(int i,unsigned event,const char *profile) {
    if(event==PTRACE_EVENT_FORK||event==PTRACE_EVENT_VFORK||event==PTRACE_EVENT_CLONE){
        unsigned long tid=0;int kind=m_tasks[i].creating;
        if(!kind||ptrace(PTRACE_GETEVENTMSG,m_tasks[i].tid,0,&tid)<0||!tid||tid>2147483647UL){m_fail("creation-event-unavailable");return -1;}
        int added=m_add((pid_t)tid,i,kind);
        if(added<0){m_fail("creation-identity-unavailable");return -1;}
        if(kind==3){m_contained_clone3_events++;kind=m_tasks[added].tid==m_tasks[added].tgid?2:1;}
        m_tasks[i].creation_event=1;
        if(event==PTRACE_EVENT_FORK)m_fork_events++;
        else if(event==PTRACE_EVENT_VFORK)m_vfork_events++;
        else m_clone_events++;
        if(kind==2){m_unavailable("multiple-application-processes");if(!strcmp(profile,"rust-leaf"))m_fail("native-descendant");}
        return 0;
    }
    if(event==PTRACE_EVENT_EXEC)return m_exec(i);
    if(event==PTRACE_EVENT_EXIT)return 0;
    m_fail("unknown-ptrace-event");return -1;
}
/* Trusted harness control fd only. Snapshot labels are finite; application has
 * neither fd nor authority to attest settled/retained lifecycle checkpoints. */
static int m_resident_bytes(pid_t pid,unsigned long long *bytes) {
    char path[64],line[256];snprintf(path,sizeof(path),"/proc/%ld/smaps_rollup",(long)pid);
    FILE *f=fopen(path,"r");if(!f)return -1;
    unsigned long long value=0;char unit[8],extra;int found=0,lines=0;
    while(fgets(line,sizeof(line),f)){
        if(++lines>128){fclose(f);return -1;}
        if(sscanf(line,"Rss: %llu %7s %c",&value,unit,&extra)==2){if(strcmp(unit,"kB")){fclose(f);return -1;}found++;}
    }
    int failed=ferror(f);fclose(f);
    /* Linux proc smaps kB is1024-byte KiB, not decimal kB. */
    if(failed||found!=1||!value||value>9007199254740991ULL/1024)return -1;
    *bytes=value*1024;return 0;
}
static int m_marker(int fd,unsigned seq,const char *phase,int long_lived) {
    if(!seq)return -1;
    unsigned long long bytes=0;int i=m_index(m_root);struct identity a,b;
    int available=long_lived&&!m_unknown&&m_processes==1&&m_execs==1&&!m_root_done&&
        m_held(i)&&read_identity(m_root,&a)==1&&m_resident_bytes(m_root,&bytes)==0&&
        read_identity(m_root,&b)==1&&a.birth==b.birth&&m_held(i);
    if(!available)return dprintf(fd,"{\"marker\":%u,\"phase\":\"%s\",\"rssBytes\":null,\"memoryStatus\":\"unavailable\",\"topologyFinal\":false}\n",seq,phase)<0?-1:0;
    return dprintf(fd,"{\"marker\":%u,\"phase\":\"%s\",\"rssBytes\":%llu,\"method\":\"original-process-smaps-rollup-rss\",\"memoryStatus\":\"provisional-single-process\",\"topologyFinal\":false}\n",seq,phase,bytes)<0?-1:0;
}
static int m_control(int control,char *buffer,size_t *used,int fd,long long *deadline,int long_lived,int *markers) {
    char ch;ssize_t n;
    while((n=read(control,&ch,1))==1){
        if(*used>=255)return -1;
        buffer[(*used)++]=ch;
        if(ch=='\n'){
            buffer[*used]=0;char extra;long long d;unsigned seq;char label[16];
            if(sscanf(buffer,"D %lld %c",&d,&extra)==1&&d>now_ns()&&d<=*deadline)*deadline=d;
            else if(sscanf(buffer,"M %15s %u %c",label,&seq,&extra)==2&&(!strcmp(label,"steady")||!strcmp(label,"retained"))){
                if(++*markers>M_MAX_MARKERS||m_marker(fd,seq,label,long_lived))return -1;
            }else return -1;
            *used=0;
        }
    }
    return n<0&&(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINTR)?0:-1;
}
static int memory_v3(int argc,char **argv) {
    if(argc<8||argv[7][0]!='/'||strcmp(argv[6],"--")||(strcmp(argv[3],"rust-leaf")&&strcmp(argv[3],"pinned-typescript-owned-tree"))||
       (strcmp(argv[5],"ephemeral-command")&&strcmp(argv[5],"long-lived")))return 125;
    char *end=NULL;long f=strtol(argv[1],&end,10);if(!end||*end||f<3||f>1048576)return 125;int fd=(int)f;
    long c=strtol(argv[4],&end,10);if(!end||*end||c<3||c>1048576||c==f)return 125;int control=(int)c;
    int long_lived=!strcmp(argv[5],"long-lived");
    if(prctl(PR_SET_CHILD_SUBREAPER,1))return 125;
    struct sigaction action={0};action.sa_handler=cancel_handler;
    sigaction(SIGINT,&action,NULL);sigaction(SIGTERM,&action,NULL);sigaction(SIGHUP,&action,NULL);signal(SIGPIPE,SIG_IGN);
    if(fcntl(control,F_SETFL,O_NONBLOCK)<0||fcntl(fd,F_SETFL,O_NONBLOCK)<0)return 125;
    long long launched=now_ns(),deadline=launched+1000000000LL;int supplied=0;char buffer[256];size_t used=0;
    while(!supplied&&now_ns()<deadline&&!cancelled){
        char ch;ssize_t n=read(control,&ch,1);
        if(n==1){if(used>=sizeof(buffer)-1)return 125;buffer[used++]=ch;if(ch=='\n'){buffer[used]=0;long long d;char extra;if(sscanf(buffer,"D %lld %c",&d,&extra)!=1||d<=now_ns())return 125;deadline=d;supplied=1;}}
        else if(n==0)return 125;else if(errno!=EINTR&&errno!=EAGAIN&&errno!=EWOULDBLOCK)return 125;
        if(!supplied){struct pollfd p={control,POLLIN,0};poll(&p,1,1);}
    }
    if(!supplied||cancelled)return 125;
    pid_t owner=getpid();
    m_root=fork();if(m_root<0)return 125;
    if(!m_root){
        /* Covers tracer death before SETOPTIONS/EXITKILL. Parent identity is
         * checked after prctl to close the fork-to-PDEATHSIG installation race. */
        if(prctl(PR_SET_PDEATHSIG,SIGKILL)||getppid()!=owner)_exit(125);
        close(control);close(fd);
        if(m_contained_nsfd>=0){close(m_contained_nsfd);if(setsid()<0||m_gate_forest_fds(-1,-1,-1))_exit(125);}
        signal(SIGINT,SIG_DFL);signal(SIGTERM,SIG_DFL);signal(SIGHUP,SIG_DFL);signal(SIGPIPE,SIG_DFL);
        if(ptrace(PTRACE_TRACEME,0,0,0)<0)_exit(126);
        raise(SIGSTOP);execv(argv[7],argv+7);_exit(127);
    }
    m_initial_handle=handle_open(m_root);if(m_initial_handle<0)m_fail("initial-pidfd-unavailable");
    int attached=0,empty=0,markers=0;used=0;
    /* All stops are consumed by this one wait owner. No other waitpid consumer. */
    while(now_ns()<deadline){
        if(cancelled){m_cancel_observed=1;m_fail("cancelled");}
        if(now_ns()>=deadline-200000000LL){m_deadline_observed=1;m_fail("deadline");}
        if(m_failure)m_kill_all();
        int status;struct rusage usage;pid_t tid=wait4(-1,&status,__WALL|WNOHANG,&usage);
        if(tid>0){
            if(++m_events>M_MAX_EVENTS)m_fail("event-bound");
            int i=m_index(tid);
            if(WIFSTOPPED(status)){
                int sig=WSTOPSIG(status);unsigned event=(unsigned)status>>16;
                if(!attached&&tid==m_root&&sig==SIGSTOP){
                    i=m_add(m_root,-1,0);
                    unsigned long options=PTRACE_O_TRACEFORK|PTRACE_O_TRACEVFORK|PTRACE_O_TRACECLONE|PTRACE_O_TRACEEXEC|PTRACE_O_TRACEEXIT|PTRACE_O_TRACESYSGOOD|PTRACE_O_EXITKILL;
                    if(i<0||ptrace(PTRACE_SETOPTIONS,m_root,0,(void *)options)<0)m_fail("ptrace-options-unavailable");
                    else {attached=1;m_tasks[i].initial=0;if(dprintf(fd,"{\"pid\":%ld,\"birth\":%llu,\"method\":\"owned-memory-v3\"}\n",(long)m_root,m_tasks[i].birth)<0)m_fail("measurement-pipe");}
                }else if(i<0){
                    /* A kernel wait stop establishes ptrace ownership, but an
                     * absent matching creation event cannot establish topology. */
                    if(!m_failure&&sig==SIGSTOP&&!event&&m_pending_count<M_MAX_TASKS){
                        int duplicate=0;for(int j=0;j<m_pending_count;j++)if(m_pending[j]==tid)duplicate=1;
                        if(!duplicate){m_pending[m_pending_count++]=tid;continue;}
                    }
                    m_fail("unmatched-kernel-task-stop");
                }else if(!m_held(i))m_fail("task-identity-changed");
                else if(event)m_event(i,event,argv[3]);
                else if(sig==(SIGTRAP|0x80))m_syscall(i);
                else if(m_tasks[i].initial&&sig==SIGSTOP)m_tasks[i].initial=0;
                else {
                    siginfo_t delivered;
                    if(sig<=0||sig>=NSIG||ptrace(PTRACE_GETSIGINFO,tid,0,&delivered)<0){m_group_stops++;m_fail("group-or-unknown-signal-stop");}
                    else {m_signal_stops++;if(!m_failure&&m_resume(tid,sig)<0)m_fail("signal-resume");}
                    if(!m_failure)continue;
                }
                if(m_failure){
                    /* This exact TID is held in a kernel-delivered ptrace stop;
                     * no PID lookup or process-group inference authorizes it. */
                    if(ptrace(PTRACE_CONT,tid,0,(void *)(long)SIGKILL)<0&&errno!=ESRCH)m_fail("trace-cleanup");
                }else if(m_resume(tid,0)<0)m_fail("syscall-resume");
            }else if(WIFEXITED(status)||WIFSIGNALED(status)){
                if(tid==m_root){
                    m_root_done=1;if(m_initial_handle>=0){close(m_initial_handle);m_initial_handle=-1;}m_root_code=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);m_usage=usage;m_peak=usage.ru_maxrss;
                    if(!attached)m_fail("ptrace-denied-or-initial-stop-missing");
                }
                if(i>=0){m_tasks[i].live=0;if(m_tasks[i].handle>=0){close(m_tasks[i].handle);m_tasks[i].handle=-1;}}
                else if(attached)m_unavailable("unmatched-final-wait");
            }else m_fail("unknown-wait-status");
            continue;
        }
        if(tid<0&&errno==ECHILD){empty=1;break;}
        if(tid<0&&errno!=EINTR)m_fail("kernel-wait-unavailable");
        if(attached&&!m_failure&&m_control(control,buffer,&used,fd,&deadline,long_lived,&markers))m_fail("control-or-marker-unavailable");
        struct pollfd p={control,POLLIN,0};poll(&p,1,1);
    }
    if(!empty||!m_root_done){m_fail("cleanup-unverified");m_kill_all();}
    if(m_pending_count)m_fail("unmatched-pending-kernel-task");
    int clean=empty&&m_root_done;
    int available=attached&&clean&&!m_failure&&!m_unknown&&m_processes==1&&m_execs==1&&m_peak>0;
    /* Thread exits are NOT added to leader rusage: that would double-count CPU.
     * Multi-process ptrace wait/reap accounting is not silently equated with V2. */
    if(m_processes!=1)m_unavailable("multiprocess-cpu-accounting-unverified");
    const char *cpu=attached&&clean&&m_processes==1?"kernel-waited-single-thread-group":"unavailable";
    dprintf(fd,"{\"exitCode\":%d,\"wallMs\":%.3f,\"rawRootCpuUserMs\":%.3f,\"rawRootCpuSystemMs\":%.3f,\"rawRootPeakRssKiB\":%ld,\"method\":\"owned-memory-v3\",\"cpuScope\":\"%s\",\"ownedShutdownConfirmed\":%s,\"topologyObserver\":\"ptrace-syscall-entry-exit-and-fork-vfork-clone-exec\",\"kernelEvents\":%llu,\"processesEver\":%d,\"threadCreates\":%d,\"execEvents\":%d,\"markerCount\":%d,\"memoryAvailable\":%s,\"memoryStatus\":\"%s\",\"wholeApplicationPeakRssKiB\":",m_root_code,(now_ns()-launched)/1000000.0,m_usage.ru_utime.tv_sec*1000.0+m_usage.ru_utime.tv_usec/1000.0,m_usage.ru_stime.tv_sec*1000.0+m_usage.ru_stime.tv_usec/1000.0,m_peak,cpu,clean?"true":"false",m_events,m_processes,m_threads,m_execs,markers,available?"true":"false",available?"single-process-kernel-hwm":m_failure?m_failure:m_unknown?m_unknown:"unavailable");
    if(available)dprintf(fd,"%ld",m_peak);else dprintf(fd,"null");
    dprintf(fd,",\"cpuUserMs\":");
    if(attached&&clean&&m_processes==1)dprintf(fd,"%.3f",m_usage.ru_utime.tv_sec*1000.0+m_usage.ru_utime.tv_usec/1000.0);else dprintf(fd,"null");
    dprintf(fd,",\"cpuSystemMs\":");
    if(attached&&clean&&m_processes==1)dprintf(fd,"%.3f",m_usage.ru_stime.tv_sec*1000.0+m_usage.ru_stime.tv_usec/1000.0);else dprintf(fd,"null");
    if(m_contained_verified)dprintf(fd,",\"containedClone3Entries\":%u,\"containedClone3Events\":%u",m_contained_clone3_entries,m_contained_clone3_events);
    dprintf(fd,",\"forkEvents\":%u,\"vforkEvents\":%u,\"cloneEvents\":%u,\"untracedCloneRefusals\":%u,\"clone3Refusals\":%u,\"x32Refusals\":%u,\"signalDeliveryStops\":%u,\"groupOrUnknownStops\":%u,\"cancelObserved\":%u,\"deadlineObserved\":%u,\"units\":\"KiB\",\"instrumentation\":\"ptrace-syscall-traced-do-not-compare-untraced-history\"}\n",m_fork_events,m_vfork_events,m_clone_events,m_untraced_refusals,m_clone3_refusals,m_x32_refusals,m_signal_stops,m_group_stops,m_cancel_observed,m_deadline_observed);
    for(int i=0;i<m_n;i++)if(m_tasks[i].handle>=0)close(m_tasks[i].handle);
    close(fd);close(control);return m_failure?125:m_root_code;
}

/* Ordinary callers cannot provide this gate with a boolean, env or writable
 * control file. Only an actual nonroot PID1-created anonymous socketpair peer
 * and a live matching nsfs PID namespace descriptor admit the contained entry.
 * The outside managed Launch independently pins this exact namespace/source.
 */
static int m_gate_socket(int fd) {
    int type=0,domain=0; socklen_t n=sizeof(type);struct ucred peer;
    if(fd<3||getsockopt(fd,SOL_SOCKET,SO_TYPE,&type,&n)||n!=sizeof(type)||type!=SOCK_STREAM)return -1;
    n=sizeof(domain);if(getsockopt(fd,SOL_SOCKET,SO_DOMAIN,&domain,&n)||domain!=AF_UNIX)return -1;
    n=sizeof(peer);if(getsockopt(fd,SOL_SOCKET,SO_PEERCRED,&peer,&n)||n!=sizeof(peer)||
       peer.pid!=1||peer.uid!=geteuid()||peer.gid!=getegid())return -1;
    struct sockaddr_un address;struct stat inode;
    n=sizeof(address);if(getsockname(fd,(struct sockaddr *)&address,&n)||n!=offsetof(struct sockaddr_un,sun_path)||address.sun_family!=AF_UNIX)return -1;
    n=sizeof(address);if(getpeername(fd,(struct sockaddr *)&address,&n)||n!=offsetof(struct sockaddr_un,sun_path)||address.sun_family!=AF_UNIX)return -1;
    if(fstat(fd,&inode)||!S_ISSOCK(inode.st_mode)||inode.st_uid!=geteuid())return -1;
    return 0;
}
static int m_gate_privileges(void) {
    FILE *f=fopen("/proc/self/status","r");if(!f)return -1;
    char line[256];unsigned seen=0;unsigned long long value;
    const char *fields[]={"CapInh:","CapPrm:","CapEff:","CapBnd:","CapAmb:"};
    int nnp=0;
    while(fgets(line,sizeof(line),f)){
        for(unsigned i=0;i<5;i++)if(!strncmp(line,fields[i],strlen(fields[i]))){
            if((seen&(1U<<i))||sscanf(line+strlen(fields[i]),"%llx",&value)!=1||value){fclose(f);return -1;}
            seen|=1U<<i;
        }
        if(!strncmp(line,"NoNewPrivs:",11)){
            if(nnp||sscanf(line+11,"%llu",&value)!=1||value!=1){fclose(f);return -1;}nnp=1;
        }
    }
    int bad=ferror(f);fclose(f);return !bad&&seen==31&&nnp?0:-1;
}
static int m_gate_forest_fds(int measurement,int control,int ns) {
    DIR *d=opendir("/proc/self/fd");if(!d)return -1;
    int own=dirfd(d),bad=0;struct dirent *entry;
    errno=0;
    while((entry=readdir(d))){
        char *end=NULL;long fd=strtol(entry->d_name,&end,10);
        if(!*entry->d_name||!end||*end)continue;
        if(fd>2&&fd!=own&&fd!=measurement&&fd!=control&&fd!=ns){bad=1;break;}
    }
    if(errno)bad=1;
    if(closedir(d))bad=1;
    return bad?-1:0;
}
static int m_contained_entry(int argc,char **argv) {
    if(argc<9||strcmp(argv[7],"--")||getpid()<=1||getppid()!=1||!geteuid()||!getegid())return 125;
    uid_t real,effective,saved;gid_t gr,ge,gs;
    if(getresuid(&real,&effective,&saved)||getresgid(&gr,&ge,&gs)||real!=effective||saved!=effective||gr!=ge||gs!=ge)return 125;
    char *end=NULL;long f=strtol(argv[1],&end,10);if(!end||*end||f<3||f>1048576)return 125;
    long c=strtol(argv[4],&end,10);if(!end||*end||c<3||c>1048576||c==f)return 125;
    long ns=strtol(argv[6],&end,10);if(!end||*end||ns<3||ns>1048576||ns==f||ns==c)return 125;
    if(m_gate_socket((int)f)||m_gate_socket((int)c)||m_gate_privileges()||m_gate_forest_fds((int)f,(int)c,(int)ns))return 125;
    struct stat first,second;
    if(fstat((int)f,&first)||fstat((int)c,&second)||(first.st_dev==second.st_dev&&first.st_ino==second.st_ino))return 125;
    struct stat a,b;struct statfs fs;
    int self=open("/proc/self/ns/pid",O_RDONLY|O_CLOEXEC);if(self<0)return 125;
    int bad=fstat((int)ns,&a)||fstat(self,&b)||fstatfs((int)ns,&fs)||
        (unsigned long)fs.f_type!=(unsigned long)NSFS_MAGIC||ioctl((int)ns,NS_GET_NSTYPE)!=CLONE_NEWPID||
        a.st_dev!=b.st_dev||a.st_ino!=b.st_ino;
    close(self);if(bad||prctl(PR_SET_DUMPABLE,0)||prctl(PR_GET_DUMPABLE)!=0)return 125;
    m_contained_nsfd=(int)ns;m_contained_nsdev=(unsigned long long)a.st_dev;m_contained_nsino=(unsigned long long)a.st_ino;
    m_contained_verified=1;
    if(dprintf((int)f,"{\"containedKernelGate\":true,\"namespaceDev\":%llu,\"namespaceInode\":%llu,\"peerPid\":1,\"privateFdsChecked\":true}\n",m_contained_nsdev,m_contained_nsino)<0)return 125;
    char **adapted=calloc((size_t)argc,sizeof(char *));if(!adapted)return 125;
    for(int i=0;i<6;i++)adapted[i]=argv[i];
    for(int i=7;i<argc;i++)adapted[i-1]=argv[i];
    int code=memory_v3(argc-1,adapted);free(adapted);return code;
}
#endif
int main(int argc,char **argv) {
    if(argc>=3&&!strcmp(argv[2],"--owned-memory-v3-contained")){
#if defined(__linux__)
        return m_contained_entry(argc,argv);
#else
        return 125;
#endif
    }
    if(argc>=3&&!strcmp(argv[2],"--owned-memory-v3")){
#if defined(__linux__)
        return memory_v3(argc,argv);
#else
        return 125;
#endif
    }
    return owned_v2_main(argc,argv);
}

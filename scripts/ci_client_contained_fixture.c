/* Finite harmless synthetic topology fixture; no credentials, network or product. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <time.h>
#include <linux/sched.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
static int private_fds(void) {
    DIR *d=opendir("/proc/self/fd");if(!d)return -1;
    int own=dirfd(d),extra=0;struct dirent *entry;
    while((entry=readdir(d))){char *end;long fd=strtol(entry->d_name,&end,10);if(*entry->d_name&&!*end&&fd>2&&fd!=own)extra++;}
    if(closedir(d))return -1;
    return extra;
}
static int entry_private_fds;
static int report(const char *mode,int late,int error) {
    struct rusage usage;if(getrusage(RUSAGE_SELF,&usage))return 3;
    printf("{\"fixture\":\"%s\",\"privateFds\":%d,\"selfRssKiB\":%ld,\"lateWorker\":%s,\"syscallErrno\":%d,\"acceptanceEligible\":false}\n",mode,entry_private_fds,usage.ru_maxrss,late?"true":"false",error);
    return fflush(stdout)?3:0;
}
static void *pages(void *unused) {
    (void)unused;size_t n=8*1024*1024;volatile unsigned char *p=malloc(n);if(!p)return (void *)1;
    for(size_t i=0;i<n;i+=4096)p[i]=1;
    usleep(30000);free((void *)p);return NULL;
}
static void *late(void *unused) {
    (void)unused;char path[80],line[1024];snprintf(path,sizeof(path),"/proc/%ld/stat",(long)getpid());
    int exited=0;
    for(int i=0;i<1000&&!exited;i++){
        FILE *f=fopen(path,"r");if(!f)return (void *)1;
        if(fgets(line,sizeof(line),f)){char *end=strrchr(line,')');if(end&&end[1]==' '&&end[2]=='Z')exited=1;}
        fclose(f);if(!exited)usleep(1000);
    }
    if(!exited)_exit(9);
    size_t n=32*1024*1024;volatile unsigned char *p=malloc(n);if(!p)_exit(3);
    for(size_t i=0;i<n;i+=4096)p[i]=1;
    if(report("late-worker",1,0))_exit(3);
    free((void *)p);return NULL;
}
/* Optional ordinary-stderr observations; never private meter frames/authority.
 * Five records, each <768bytes: total<3840 fits one Linux pipe page before the
 * existing driver drains stderr. Reads themselves can perturb timing/RSS. */
struct diagnostic_counter { const char *name; char value[24]; };
static void diagnostic_fields(const char *path,struct diagnostic_counter *fields,size_t count) {
    for(size_t i=0;i<count;i++)strcpy(fields[i].value,"null");
    char buffer[4097];int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return;
    ssize_t size=read(fd,buffer,sizeof(buffer));close(fd);
    if(size<=0||(size_t)size>=sizeof(buffer))return;
    buffer[size]='\0';char *save=NULL;
    for(char *line=strtok_r(buffer,"\n",&save);line;line=strtok_r(NULL,"\n",&save)){
        for(size_t i=0;i<count;i++){
            size_t length=strlen(fields[i].name);
            if(strncmp(line,fields[i].name,length)||line[length]!=':')continue;
            const char *start=line+length+1;while(*start==' '||*start=='\t')start++;
            if(*start<'0'||*start>'9')continue;
            errno=0;char *end=NULL;unsigned long long value=strtoull(start,&end,10);
            while(end&&(*end==' '||*end=='\t'))end++;
            if(errno||!end||strcmp(end,"kB"))continue;
            snprintf(fields[i].value,sizeof(fields[i].value),"%llu",value);
        }
    }
}
static unsigned long long diagnostic_start_ticks(void) {
    char buffer[4097];int fd=open("/proc/self/stat",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return 0;
    ssize_t size=read(fd,buffer,sizeof(buffer));close(fd);
    if(size<=0||(size_t)size>=sizeof(buffer))return 0;
    buffer[size]='\0';char *end=strrchr(buffer,')');if(!end||end[1]!=' ')return 0;
    char *save=NULL,*token=strtok_r(end+2," ", &save);
    for(int field=3;token;field++,token=strtok_r(NULL," ",&save))if(field==22){
        errno=0;char *tail=NULL;unsigned long long value=strtoull(token,&tail,10);
        return !errno&&tail&&!*tail?value:0;
    }
    return 0;
}
static unsigned long long diagnostic_monotonic_ns(void) {
    struct timespec now;if(clock_gettime(CLOCK_MONOTONIC,&now)||now.tv_sec<0)return 0;
    if((unsigned long long)now.tv_sec>(ULLONG_MAX-(unsigned long long)now.tv_nsec)/1000000000ULL)return 0;
    return (unsigned long long)now.tv_sec*1000000000ULL+(unsigned long long)now.tv_nsec;
}
static void diagnostic_snapshot(const char *phase) {
    unsigned long long begin=diagnostic_monotonic_ns(),ticks=diagnostic_start_ticks();
    struct rusage usage;char hwm[24]="null";
    if(!getrusage(RUSAGE_SELF,&usage)&&usage.ru_maxrss>=0)snprintf(hwm,sizeof(hwm),"%ld",usage.ru_maxrss);
    struct diagnostic_counter status[]={{"VmHWM",""},{"VmRSS",""},{"RssAnon",""},{"RssFile",""},{"RssShmem",""}};
    struct diagnostic_counter rollup[]={{"Rss",""},{"Pss",""},{"Anonymous",""},{"Shared_Clean",""},{"Shared_Dirty",""},{"Private_Clean",""},{"Private_Dirty",""},{"Swap",""}};
    diagnostic_fields("/proc/self/status",status,sizeof(status)/sizeof(status[0]));
    diagnostic_fields("/proc/self/smaps_rollup",rollup,sizeof(rollup)/sizeof(rollup[0]));
    unsigned long long end=diagnostic_monotonic_ns();char output[768];
    int length=snprintf(output,sizeof(output),
        "{\"kind\":\"contained-rss-v1\",\"phase\":\"%s\",\"pid\":%ld,\"startTicks\":\"%llu\",\"beginNs\":\"%llu\",\"endNs\":\"%llu\",\"ruMaxKiB\":%s,"
        "\"statusKiB\":{\"VmHWM\":%s,\"VmRSS\":%s,\"RssAnon\":%s,\"RssFile\":%s,\"RssShmem\":%s},"
        "\"rollupKiB\":{\"Rss\":%s,\"Pss\":%s,\"Anonymous\":%s,\"Shared_Clean\":%s,\"Shared_Dirty\":%s,\"Private_Clean\":%s,\"Private_Dirty\":%s,\"Swap\":%s}}\n",
        phase,(long)getpid(),ticks,begin,end,hwm,status[0].value,status[1].value,status[2].value,status[3].value,status[4].value,
        rollup[0].value,rollup[1].value,rollup[2].value,rollup[3].value,rollup[4].value,rollup[5].value,rollup[6].value,rollup[7].value);
    if(length>0&&(size_t)length<sizeof(output)){ssize_t written=write(STDERR_FILENO,output,(size_t)length);(void)written;}
}

int main(int argc,char **argv) {
    entry_private_fds=private_fds();
    if(argc!=2||entry_private_fds!=0)return 2;
    const char *mode=argv[1];
    if(!strcmp(mode,"leaf")){if(pages(NULL))return 3;return report(mode,0,0);}
    if(!strcmp(mode,"threads")){
        pthread_t threads[4];for(int i=0;i<4;i++)if(pthread_create(&threads[i],NULL,pages,NULL))return 3;
        for(int i=0;i<4;i++){void *result;if(pthread_join(threads[i],&result)||result)return 3;}
        return report(mode,0,0);
    }
    if(!strcmp(mode,"late-worker")){pthread_t worker;if(pthread_create(&worker,NULL,late,NULL))return 3;pthread_exit(NULL);}
    if(!strcmp(mode,"child")){pid_t child=fork();if(child<0)return 3;if(!child)_exit(pages(NULL)!=NULL);int s;if(waitpid(child,&s,0)!=child||!WIFEXITED(s)||WEXITSTATUS(s))return 3;return report(mode,0,0);}
    if(!strcmp(mode,"clone3")||!strcmp(mode,"clone3-error")||!strcmp(mode,"clone3-untraced")){
#ifdef SYS_clone3
        struct clone_args args={0};args.exit_signal=SIGCHLD;if(!strcmp(mode,"clone3-untraced"))args.flags=CLONE_UNTRACED;
        errno=0;long child=syscall(SYS_clone3,&args,!strcmp(mode,"clone3-error")?0:sizeof(args));int error=child<0?errno:0;
        if(!child){if(!strcmp(mode,"clone3-untraced"))sleep(20);_exit(0);}
        if(child>0){int s;if(waitpid((pid_t)child,&s,0)!=child)return 3;}
        return report(mode,0,error);
#else
        return report(mode,0,ENOSYS);
#endif
    }
    if(!strcmp(mode,"untraced")){
#ifdef SYS_clone
        long child=syscall(SYS_clone,CLONE_UNTRACED|SIGCHLD,0,0,0,0);if(!child)_exit(0);if(child>0)waitpid((pid_t)child,NULL,0);
#endif
        return 8;
    }
    if(!strcmp(mode,"crash")){raise(SIGSEGV);return 8;}
    if(!strcmp(mode,"cancel")){if(kill(getppid(),SIGTERM))return 3;sleep(20);return 8;}
    if(!strcmp(mode,"deadline")){sleep(20);return 8;}
    if(!strcmp(mode,"long-lived")){
        diagnostic_snapshot("before_alloc");
        char command;volatile unsigned char *p=malloc(16*1024*1024);if(!p)return 3;
        for(size_t i=0;i<16*1024*1024;i+=4096)p[i]=1;
        diagnostic_snapshot("after_touch");
        if(write(1,"steady\n",7)!=7||read(0,&command,1)!=1)return 3;
        diagnostic_snapshot("before_free");
        free((void *)p);
        diagnostic_snapshot("after_free");
        if(write(1,"retained\n",9)!=9||read(0,&command,1)!=1)return 3;
        diagnostic_snapshot("before_exit");
        return report(mode,0,0);
    }
    return 2;
}

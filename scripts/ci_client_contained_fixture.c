/* Finite harmless synthetic topology fixture; no credentials, network or product. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
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
        char command;volatile unsigned char *p=malloc(16*1024*1024);if(!p)return 3;
        for(size_t i=0;i<16*1024*1024;i+=4096)p[i]=1;
        if(write(1,"steady\n",7)!=7||read(0,&command,1)!=1)return 3;
        free((void *)p);
        if(write(1,"retained\n",9)!=9||read(0,&command,1)!=1)return 3;
        return report(mode,0,0);
    }
    return 2;
}

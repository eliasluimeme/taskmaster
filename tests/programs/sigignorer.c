#include <stdio.h>
#include <signal.h>
#include <unistd.h>

void handler(int sig) {
    printf("sigignorer received signal %d, but ignoring it!\n", sig);
    fflush(stdout);
}

int main(void) {
    signal(SIGTERM, handler);
    signal(SIGINT, handler);
    signal(SIGQUIT, handler);
    printf("sigignorer started (PID: %d). Will ignore TERM/INT/QUIT!\n", getpid());
    fflush(stdout);

    while (1) {
        sleep(1);
    }
    return 0;
}

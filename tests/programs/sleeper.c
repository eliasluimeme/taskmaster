#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv) {
    int duration = 60;
    if (argc > 1) {
        duration = atoi(argv[1]);
    }
    printf("Sleeper sleeping for %d seconds (PID: %d)...\n", duration, getpid());
    fflush(stdout);
    sleep(duration);
    printf("Sleeper finished.\n");
    return 0;
}

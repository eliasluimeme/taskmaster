#include <stdio.h>
#include <unistd.h>

int main(void) {
    int count = 0;
    while (count < 200) {
        printf("[STDOUT] Flooding log lines from process: line %d\n", count);
        fprintf(stderr, "[STDERR] Flooding error lines from process: line %d\n", count);
        count++;
        usleep(500); // 0.5ms
    }
    fflush(stdout);
    fflush(stderr);
    printf("Flooder completed 200 lines.\n");
    fflush(stdout);
    return 0;
}

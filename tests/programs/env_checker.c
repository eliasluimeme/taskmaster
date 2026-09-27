#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    const char *key = (argc > 1) ? argv[1] : "TASKMASTER_TEST";
    char *val = getenv(key);
    if (val) {
        printf("%s=%s\n", key, val);
    } else {
        printf("%s=(null)\n", key);
    }
    fflush(stdout);
    return 0;
}

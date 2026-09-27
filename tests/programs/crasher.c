#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    int code = 1;
    if (argc > 1) {
        code = atoi(argv[1]);
    }
    printf("Crasher exiting with code %d\n", code);
    return code;
}

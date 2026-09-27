#include <stdio.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char **argv) {
    const char *filepath = (argc > 1) ? argv[1] : "umask_test.txt";
    int fd = open(filepath, O_CREAT | O_WRONLY | O_TRUNC, 0666);
    if (fd < 0) {
        perror("open");
        return 1;
    }
    close(fd);

    struct stat st;
    if (stat(filepath, &st) == 0) {
        printf("Created %s with mode: %o\n", filepath, st.st_mode & 0777);
    }
    return 0;
}

CC = cc
CFLAGS = -Wall -Wextra -Werror

TARGETS = crasher sleeper sigignorer flooder umask_checker env_checker

all: $(TARGETS)

crasher: crasher.c
	$(CC) $(CFLAGS) -o crasher crasher.c

sleeper: sleeper.c
	$(CC) $(CFLAGS) -o sleeper sleeper.c

sigignorer: sigignorer.c
	$(CC) $(CFLAGS) -o sigignorer sigignorer.c

flooder: flooder.c
	$(CC) $(CFLAGS) -o flooder flooder.c

umask_checker: umask_checker.c
	$(CC) $(CFLAGS) -o umask_checker umask_checker.c

env_checker: env_checker.c
	$(CC) $(CFLAGS) -o env_checker env_checker.c

clean:
	rm -f $(TARGETS) *.txt

.PHONY: all clean

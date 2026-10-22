#define _GNU_SOURCE 1
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include <arpa/inet.h>
#include "../native/eve-sendto-filter.h"

static struct sock_filter filter[] = {
    BPF_STMT(BPF_LD + BPF_W + BPF_ABS, offsetof(struct seccomp_data, nr)),
    EVE_SENDTO_FILTER(__NR_sendto, 1),
    BPF_STMT(BPF_RET + BPF_K, SECCOMP_RET_ALLOW)
};

/* Interpret the same instruction macro that the production builder emits. */
static uint32_t evaluate(int syscall, uint64_t address, uint64_t length)
{
    struct seccomp_data data = { .nr = syscall, .args = {0, 0, 0, 0, address, length} };
    uint32_t accumulator = 0;
    size_t pc;
    for (pc = 0; pc < sizeof(filter) / sizeof(filter[0]); pc++) {
        const struct sock_filter *instruction = &filter[pc];
        switch (instruction->code) {
        case BPF_LD + BPF_W + BPF_ABS:
            assert(instruction->k + sizeof(accumulator) <= sizeof(data));
            memcpy(&accumulator, (unsigned char *)&data + instruction->k, sizeof(accumulator));
            break;
        case BPF_JMP + BPF_JEQ + BPF_K:
            pc += accumulator == instruction->k ? instruction->jt : instruction->jf;
            break;
        case BPF_RET + BPF_K: return instruction->k;
        default: assert(0);
        }
    }
    assert(0);
    return 0;
}

static void kernel_filter(void)
{
    struct sock_fprog program = { .len = sizeof(filter) / sizeof(filter[0]), .filter = filter };
    struct sockaddr_in destination = { .sin_family = AF_INET, .sin_port = htons(9),
                                      .sin_addr = { .s_addr = htonl(INADDR_LOOPBACK) } };
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    assert(fd >= 0 && connect(fd, (struct sockaddr *)&destination, sizeof(destination)) == 0);
    assert(prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0);
    assert(prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program) == 0);
    assert(syscall(__NR_sendto, fd, "x", 1, 0, NULL, 0) == 1);
    errno = 0;
    assert(syscall(__NR_sendto, fd, "x", 1, 0, &destination, sizeof(destination)) == -1 && errno == ENOSYS);
    errno = 0;
    assert(syscall(__NR_sendto, fd, "x", 1, 0, NULL, 1) == -1 && errno == ENOSYS);
    assert(getpid() > 0); /* A nonmatching syscall retains the accumulator. */
    close(fd);
}

int main(void)
{
    int status;
    pid_t child;
    assert(sizeof(filter) / sizeof(filter[0]) == EVE_SENDTO_FILTER_LENGTH + 2);
    assert(evaluate(__NR_sendto, 0, 0) == SECCOMP_RET_ALLOW);
    assert(evaluate(__NR_sendto, 1, 0) == (SECCOMP_RET_TRACE | 1));
    assert(evaluate(__NR_sendto, UINT64_C(1) << 32, 0) == (SECCOMP_RET_TRACE | 1));
    assert(evaluate(__NR_sendto, 0, 1) == (SECCOMP_RET_TRACE | 1));
    assert(evaluate(__NR_sendto, 0, UINT64_C(1) << 32) == (SECCOMP_RET_TRACE | 1));
    assert(evaluate(__NR_sendmsg, 0, 0) == SECCOMP_RET_ALLOW); /* Goes to next production rule. */
    assert(evaluate(__NR_connect, 0, 0) == SECCOMP_RET_ALLOW);
    child = fork(); assert(child >= 0);
    if (child == 0) { kernel_filter(); _exit(0); }
    assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    puts("Production connected-sendto BPF: pointer and length halves, syscall matching, kernel execution passed");
    return 0;
}

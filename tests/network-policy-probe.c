/* Native PRoot EVE network-policy integration probe. SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/io_uring.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static void fail(const char *what) {
    fprintf(stderr, "policy probe failed: %s (errno=%d: %s)\n", what, errno, strerror(errno));
    exit(2);
}
#define REQUIRE(x, what) do { if (!(x)) fail(what); } while (0)
static void rejected(int value, int expected, const char *what) {
    REQUIRE(value == -1 && errno == expected, what);
}
static struct sockaddr_in ipv4(const char *ip, int port) {
    struct sockaddr_in address = { .sin_family = AF_INET, .sin_port = htons(port) };
    REQUIRE(inet_pton(AF_INET, ip, &address.sin_addr) == 1, "parse IPv4");
    return address;
}
static struct sockaddr_in6 ipv6(const char *ip, int port) {
    struct sockaddr_in6 address = { .sin6_family = AF_INET6, .sin6_port = htons(port) };
    REQUIRE(inet_pton(AF_INET6, ip, &address.sin6_addr) == 1, "parse IPv6");
    return address;
}
static int sock(int family, int kind) {
    int fd = socket(family, kind | SOCK_CLOEXEC, 0);
    REQUIRE(fd >= 0, "create allowed socket");
    struct timeval timeout = { .tv_sec = 2 };
    REQUIRE(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0, "set receive timeout");
    REQUIRE(setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) == 0, "set send timeout");
    return fd;
}
static void external_rejections(void) {
    struct sockaddr_in remote = ipv4("192.0.2.1", 443);
    int fd = sock(AF_INET, SOCK_STREAM);
    errno = 0; rejected(connect(fd, (void *)&remote, sizeof(remote)), EACCES, "reject public TCP");
    errno = 0; rejected(bind(fd, (void *)&remote, sizeof(remote)), EACCES, "reject public bind");
    close(fd);
    fd = sock(AF_INET, SOCK_DGRAM);
    errno = 0; rejected(connect(fd, (void *)&remote, sizeof(remote)), EACCES, "reject public UDP connect");
    errno = 0; rejected(sendto(fd, "blocked-udp", 11, 0, (void *)&remote, sizeof(remote)), EACCES, "reject public UDP sendto");
    remote = ipv4("198.51.100.53", 53);
    const unsigned char query[12] = {0x12,0x34,1,0,0,1,0,0,0,0,0,0};
    errno = 0; rejected(sendto(fd, query, sizeof(query), 0, (void *)&remote, sizeof(remote)), EACCES, "reject external DNS UDP");
    struct iovec vector = { .iov_base = (void *)"blocked-sendmsg", .iov_len = 15 };
    struct msghdr message = { .msg_name = &remote, .msg_namelen = sizeof(remote), .msg_iov = &vector, .msg_iovlen = 1 };
    errno = 0; rejected(sendmsg(fd, &message, 0), EACCES, "reject public UDP sendmsg");
    struct mmsghdr batch = { .msg_hdr = message };
    errno = 0; rejected(sendmmsg(fd, &batch, 1, 0), EACCES, "reject public UDP sendmmsg");
    REQUIRE(batch.msg_len == 0, "blocked sendmmsg leaves output alone");
    close(fd);
    struct sockaddr_in6 remote6 = ipv6("2001:db8::1", 443);
    fd = sock(AF_INET6, SOCK_STREAM);
    errno = 0; rejected(connect(fd, (void *)&remote6, sizeof(remote6)), EACCES, "reject public IPv6");
    close(fd);
    remote6 = ipv6("::ffff:192.0.2.1", 443);
    fd = sock(AF_INET6, SOCK_DGRAM);
    errno = 0; rejected(sendto(fd, "blocked-mapped", 14, 0, (void *)&remote6, sizeof(remote6)), EACCES, "reject public mapped IPv6");
    close(fd);
    errno = 0; rejected(socket(AF_INET, SOCK_RAW, 0), EACCES, "reject raw IP socket");
    errno = 0; rejected(socket(AF_PACKET, SOCK_DGRAM, 0), EAFNOSUPPORT, "reject packet socket");
    int pair[2];
    errno = 0; rejected(socketpair(AF_INET, SOCK_STREAM, 0, pair), EAFNOSUPPORT, "reject IP socketpair");
#ifdef SYS_io_uring_setup
    struct io_uring_params params = {0};
    errno = 0; rejected(syscall(SYS_io_uring_setup, 2, &params), EACCES, "reject io_uring bypass");
#endif
}
static void redirects(void) {
    for (int mode = 0; mode < 3; mode++) {
        int family = mode ? AF_INET6 : AF_INET;
        int fd = sock(family, SOCK_STREAM);
        if (family == AF_INET) {
            struct sockaddr_in address = ipv4("127.0.0.1", 443);
            REQUIRE(connect(fd, (void *)&address, sizeof(address)) == 0, "IPv4 localhost443 redirect");
            REQUIRE(ntohs(address.sin_port) == 443, "IPv4 caller address remains immutable");
            socklen_t length = sizeof(address);
            REQUIRE(getpeername(fd, (void *)&address, &length) == 0 && ntohs(address.sin_port) == 26003, "IPv4 actual peer redirected");
        } else {
            int zero = 0;
            REQUIRE(setsockopt(fd, IPPROTO_IPV6, IPV6_V6ONLY, &zero, sizeof(zero)) == 0, "enable dual stack");
            struct sockaddr_in6 address = ipv6(mode == 1 ? "::1" : "::ffff:127.0.0.1", 443);
            struct in6_addr original = address.sin6_addr;
            REQUIRE(connect(fd, (void *)&address, sizeof(address)) == 0, "IPv6 localhost443 redirect");
            REQUIRE(ntohs(address.sin6_port) == 443 && memcmp(&original, &address.sin6_addr, sizeof(original)) == 0, "IPv6 caller address remains immutable");
            socklen_t length = sizeof(address);
            REQUIRE(getpeername(fd, (void *)&address, &length) == 0 && ntohs(address.sin6_port) == 26003 && IN6_IS_ADDR_V4MAPPED(&address.sin6_addr), "IPv6 actual peer mapped and redirected");
        }
        REQUIRE(send(fd, "ping", 4, 0) == 4, "redirected send");
        char reply[2]; REQUIRE(recv(fd, reply, sizeof(reply), MSG_WAITALL) == 2 && memcmp(reply, "ok", 2) == 0, "redirected response");
        close(fd);
    }
}
static void bindings(void) {
    int fd = sock(AF_INET, SOCK_STREAM);
    struct sockaddr_in address = ipv4("0.0.0.0", 0);
    REQUIRE(bind(fd, (void *)&address, sizeof(address)) == 0, "wildcard IPv4 bind");
    REQUIRE(address.sin_addr.s_addr == INADDR_ANY, "IPv4 caller bind address preserved");
    socklen_t length = sizeof(address);
    REQUIRE(getsockname(fd, (void *)&address, &length) == 0 && ntohl(address.sin_addr.s_addr) == INADDR_LOOPBACK, "wildcard IPv4 rewritten to loopback");
    close(fd);
    fd = sock(AF_INET6, SOCK_STREAM);
    struct sockaddr_in6 address6 = ipv6("::", 0);
    REQUIRE(bind(fd, (void *)&address6, sizeof(address6)) == 0, "wildcard IPv6 bind");
    REQUIRE(IN6_IS_ADDR_UNSPECIFIED(&address6.sin6_addr), "IPv6 caller bind address preserved");
    length = sizeof(address6);
    REQUIRE(getsockname(fd, (void *)&address6, &length) == 0 && IN6_IS_ADDR_LOOPBACK(&address6.sin6_addr), "wildcard IPv6 rewritten to loopback");
    close(fd);
}
static void unix_rights(void) {
    int pair[2]; REQUIRE(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0, "AF_UNIX socketpair");
    int original = open("/dev/null", O_RDONLY | O_CLOEXEC); REQUIRE(original >= 0, "open passed file");
    char control[CMSG_SPACE(sizeof(int))] = {0};
    char payload = 'u'; struct iovec vector = { .iov_base = &payload, .iov_len = 1 };
    struct msghdr message = { .msg_iov = &vector, .msg_iovlen = 1, .msg_control = control, .msg_controllen = sizeof(control) };
    struct cmsghdr *header = CMSG_FIRSTHDR(&message);
    header->cmsg_level = SOL_SOCKET; header->cmsg_type = SCM_RIGHTS; header->cmsg_len = CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(header), &original, sizeof(original));
    REQUIRE(sendmsg(pair[0], &message, 0) == 1, "AF_UNIX descriptor sendmsg");
    memset(control, 0, sizeof(control)); payload = 0; message.msg_controllen = sizeof(control);
    REQUIRE(recvmsg(pair[1], &message, 0) == 1 && payload == 'u', "AF_UNIX descriptor recvmsg");
    header = CMSG_FIRSTHDR(&message);
    REQUIRE(header && header->cmsg_level == SOL_SOCKET && header->cmsg_type == SCM_RIGHTS && header->cmsg_len == CMSG_LEN(sizeof(int)), "AF_UNIX descriptor intact");
    int received = -1; memcpy(&received, CMSG_DATA(header), sizeof(received));
    REQUIRE(received >= 0 && fcntl(received, F_GETFD) >= 0, "received descriptor usable");
    close(received); close(original); close(pair[0]); close(pair[1]);
}
static void datagrams(int port) {
    int fd = sock(AF_INET, SOCK_DGRAM);
    struct sockaddr_in local = ipv4("127.0.0.1", port);
    const char *payloads[] = {"sendmmsg-first", "sendmmsg-second", "sendmmsg-third"};
    struct iovec vectors[3]; struct mmsghdr batch[3] = {0};
    for (int i = 0; i < 3; i++) {
        vectors[i].iov_base = (void *)payloads[i]; vectors[i].iov_len = strlen(payloads[i]);
        batch[i].msg_hdr = (struct msghdr){ .msg_name = &local, .msg_namelen = sizeof(local), .msg_iov = &vectors[i], .msg_iovlen = 1 };
    }
    REQUIRE(sendmmsg(fd, batch, 3, 0) == 3, "local sendmmsg batch succeeds");
    for (int i = 0; i < 3; i++) REQUIRE(batch[i].msg_len == strlen(payloads[i]), "sendmmsg msg_len copied back");
    REQUIRE(ntohs(local.sin_port) == port && ntohl(local.sin_addr.s_addr) == INADDR_LOOPBACK, "sendmmsg caller address preserved");
    struct iovec direct_vector = { .iov_base = (void *)"sendmsg-local", .iov_len = 13 };
    struct msghdr direct_message = { .msg_name = &local, .msg_namelen = sizeof(local), .msg_iov = &direct_vector, .msg_iovlen = 1 };
    REQUIRE(sendmsg(fd, &direct_message, 0) == 13, "local UDP sendmsg");
    struct sockaddr_in remote = ipv4("192.0.2.1", port);
    struct iovec denied_vector = { .iov_base = (void *)"blocked-mixed-first", .iov_len = 19 };
    struct mmsghdr denied_batch[2] = {0};
    denied_batch[0].msg_hdr = (struct msghdr){ .msg_name = &local, .msg_namelen = sizeof(local), .msg_iov = &denied_vector, .msg_iovlen = 1 };
    denied_batch[1].msg_hdr = (struct msghdr){ .msg_name = &remote, .msg_namelen = sizeof(remote), .msg_iov = &denied_vector, .msg_iovlen = 1 };
    errno = 0; rejected(sendmmsg(fd, denied_batch, 2, 0), EACCES, "mixed sendmmsg fails before sending any member");
    REQUIRE(denied_batch[0].msg_len == 0 && denied_batch[1].msg_len == 0, "mixed blocked batch leaves caller outputs alone");
    REQUIRE(sendmmsg(fd, NULL, 0, 0) == 0, "empty sendmmsg");
    REQUIRE(connect(fd, (void *)&local, sizeof(local)) == 0, "local UDP connect");
    const char *connected = "connected-sendmmsg";
    struct iovec connected_vector = { .iov_base = (void *)connected, .iov_len = strlen(connected) };
    struct mmsghdr connected_batch = { .msg_hdr = { .msg_iov = &connected_vector, .msg_iovlen = 1 } };
    REQUIRE(sendmmsg(fd, &connected_batch, 1, 0) == 1 && connected_batch.msg_len == strlen(connected), "connected sendmmsg copyback");
    close(fd);
}
static struct sockaddr_in shared_destination;
static atomic_int race_running;
static void *mutate(void *unused) {
    (void)unused;
    _Atomic uint32_t *address = (_Atomic uint32_t *)&shared_destination.sin_addr.s_addr;
    while (atomic_load_explicit(&race_running, memory_order_relaxed)) {
        atomic_store_explicit(address, htonl(0xc0000201), memory_order_relaxed);
        for (volatile int spin = 0; spin < 100; spin++) {}
        atomic_store_explicit(address, htonl(INADDR_LOOPBACK), memory_order_relaxed);
        for (volatile int spin = 0; spin < 100; spin++) {}
    }
    return NULL;
}
static void address_race(int port, int iterations, int *sent, int *denied) {
    int fd = sock(AF_INET, SOCK_DGRAM);
    shared_destination = ipv4("127.0.0.1", port);
    pthread_t thread; atomic_store(&race_running, 1);
    REQUIRE(pthread_create(&thread, NULL, mutate, NULL) == 0, "create address mutator");
    *sent = *denied = 0;
    for (int i = 0; i < iterations * 4; i++) {
        errno = 0;
        int result;
        if (i % 2) {
            struct iovec vector = { .iov_base = (void *)"R", .iov_len = 1 };
            struct msghdr message = { .msg_name = &shared_destination, .msg_namelen = sizeof(shared_destination), .msg_iov = &vector, .msg_iovlen = 1 };
            result = sendmsg(fd, &message, 0);
        } else {
            result = sendto(fd, "R", 1, 0, (void *)&shared_destination, sizeof(shared_destination));
        }
        if (result == 1) (*sent)++;
        else if (result == -1 && errno == EACCES) (*denied)++;
        else fail("shared destination escaped frozen allowed/denied result");
        if ((i + 1) % iterations == 0 && *sent > 0 && *denied > 0) break;
    }
    atomic_store(&race_running, 0); REQUIRE(pthread_join(thread, NULL) == 0, "join mutator");
    close(fd);
    REQUIRE(*sent > 0 && *denied > 0, "scheduler did not exercise both race destinations after four bounded samples");
}
static void inherited_gate(char **argv) {
    pid_t child = fork(); REQUIRE(child >= 0, "fork policy child");
    if (child == 0) {
        char *arguments[] = {argv[0], argv[1], argv[2], argv[3], "inherited", NULL};
        execv(argv[0], arguments);
        _exit(3);
    }
    int status = 0;
    REQUIRE(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0, "gate remains active across fork and exec");
}
struct reader_data { int fd; int count; };
static void *reader(void *data) {
    struct reader_data *request = data;
    char payload; struct iovec vector = { .iov_base = &payload, .iov_len = 1 };
    struct msghdr message = { .msg_iov = &vector, .msg_iovlen = 1 };
    for (int i = 0; i < request->count; i++) REQUIRE(recvmsg(request->fd, &message, 0) == 1, "benchmark receive");
    return NULL;
}
static double benchmark(int count) {
    int pair[2]; REQUIRE(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0, "benchmark pair");
    pthread_t thread; struct reader_data request = { .fd = pair[1], .count = count };
    REQUIRE(pthread_create(&thread, NULL, reader, &request) == 0, "benchmark reader");
    char payload = 'b'; struct iovec vector = { .iov_base = &payload, .iov_len = 1 };
    struct msghdr message = { .msg_iov = &vector, .msg_iovlen = 1 };
    struct timespec start, end; REQUIRE(clock_gettime(CLOCK_MONOTONIC, &start) == 0, "benchmark clock");
    for (int i = 0; i < count; i++) REQUIRE(sendmsg(pair[0], &message, 0) == 1, "benchmark send");
    REQUIRE(pthread_join(thread, NULL) == 0, "benchmark join");
    REQUIRE(clock_gettime(CLOCK_MONOTONIC, &end) == 0, "benchmark clock end");
    close(pair[0]); close(pair[1]);
    return 1000.0 * (end.tv_sec - start.tv_sec) + (end.tv_nsec - start.tv_nsec) / 1000000.0;
}
int main(int argc, char **argv) {
    REQUIRE(argc == 5, "arguments: UDP-port race-iterations bench-iterations mode");
    int port = atoi(argv[1]), race_count = atoi(argv[2]), count = atoi(argv[3]);
    REQUIRE(port > 0 && race_count > 0 && count > 0, "positive arguments");
    int sent = 0, denied = 0;
    if (!strcmp(argv[4], "policy")) {
        external_rejections(); inherited_gate(argv); redirects(); bindings(); unix_rights(); datagrams(port);
        address_race(port, race_count, &sent, &denied);
        printf("{\"policyPassed\":true,\"raceSent\":%d,\"raceDenied\":%d,\"raceIterations\":%d}\n", sent, denied, sent + denied);
    } else if (!strcmp(argv[4], "inherited")) {
        external_rejections();
    } else {
        REQUIRE(!strcmp(argv[4], "benchmark"), "known mode");
        double duration = benchmark(count);
        printf("{\"sendmsgIterations\":%d,\"sendmsgMilliseconds\":%.6f}\n", count, duration);
    }
    return 0;
}

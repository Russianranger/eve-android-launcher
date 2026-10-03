#define _GNU_SOURCE 1
#include <sys/types.h>
#include "proot-network-fixture.h"
#include "../native/eve-client-network.c"

static Tracee tracee;
static Extension extension = { .tracee = &tracee };

static void start(Sysnum syscall, word_t arg2, word_t arg3)
{
    memset(&tracee, 0, sizeof(tracee));
    tracee.syscall = syscall;
    tracee.registers[ORIGINAL][SYSARG_2] = arg2;
    tracee.registers[ORIGINAL][SYSARG_3] = arg3;
    memcpy(tracee.registers[CURRENT], tracee.registers[ORIGINAL], sizeof(tracee.registers[ORIGINAL]));
}

static int enter(void)
{
    int status = eve_client_network_callback(&extension, SYSCALL_ENTER_START, 0, 0);
    tracee.status = status;
    memcpy(tracee.registers[MODIFIED], tracee.registers[CURRENT], sizeof(tracee.registers[CURRENT]));
    return status;
}

int main(void)
{
    struct sockaddr_in local = { .sin_family = AF_INET, .sin_port = htons(443) };
    struct sockaddr_in remote = { .sin_family = AF_INET, .sin_port = htons(443) };
    struct sockaddr_in *copied;
    struct msghdr message = {0}, *copied_message;
    struct mmsghdr messages[2] = {0}, *copied_messages;
    assert(inet_pton(AF_INET, "127.0.0.1", &local.sin_addr) == 1);
    assert(inet_pton(AF_INET, "192.0.2.1", &remote.sin_addr) == 1);
    assert(eve_client_network_callback(&extension, INITIALIZATION, 0, 0) == 0);
    assert(extension.filtered_sysnums != NULL);
    /* Exactly these four argument-only calls avoid the additional exit stop.
     * sendmmsg must retain one because it copies lengths back to the caller. */
    assert(extension.filtered_sysnums[2].number == PR_connect && extension.filtered_sysnums[2].flags == 0);
    assert(extension.filtered_sysnums[3].number == PR_bind && extension.filtered_sysnums[3].flags == 0);
    assert(extension.filtered_sysnums[4].number == PR_sendto && extension.filtered_sysnums[4].flags == 0);
    assert(extension.filtered_sysnums[5].number == PR_sendmsg && extension.filtered_sysnums[5].flags == 0);
    assert(extension.filtered_sysnums[6].number == PR_sendmmsg && extension.filtered_sysnums[6].flags == FILTER_SYSEXIT);
    assert(eve_client_network_callback(&extension, INHERIT_PARENT, 0, 0) == 1);
    assert(eve_client_network_callback(&extension, INHERIT_CHILD, 0, 0) == 0);
    start(PR_connect, (word_t)&remote, sizeof(remote));
    assert(enter() == -EACCES);
    start(PR_connect, (word_t)&local, sizeof(local));
    assert(enter() == 0);
    copied = (void *)tracee.registers[CURRENT][SYSARG_2];
    assert(copied != &local && ntohs(copied->sin_port) == 26003);
    assert(ntohs(local.sin_port) == 443);
    /* Frozen syscall arguments do not change with caller-owned shared data. */
    local.sin_addr = remote.sin_addr;
    assert(ntohl(copied->sin_addr.s_addr) == INADDR_LOOPBACK);
    assert(inet_pton(AF_INET, "127.0.0.1", &local.sin_addr) == 1);
    local.sin_port = htons(26000);
    start(PR_connect, (word_t)&local, sizeof(local));
    assert(enter() == 0);
    copied = (void *)tracee.registers[CURRENT][SYSARG_2];
    assert(copied != &local && ntohs(copied->sin_port) == 26000);
    local.sin_addr = remote.sin_addr;
    assert(ntohl(copied->sin_addr.s_addr) == INADDR_LOOPBACK);
    assert(inet_pton(AF_INET, "127.0.0.1", &local.sin_addr) == 1);
    local.sin_port = htons(443);
    start(PR_sendto, 0, 0);
    tracee.registers[ORIGINAL][SYSARG_5] = (word_t)&remote;
    tracee.registers[ORIGINAL][SYSARG_6] = sizeof(remote);
    assert(enter() == -EACCES);
    message.msg_name = &remote; message.msg_namelen = sizeof(remote);
    start(PR_sendmsg, (word_t)&message, 0);
    assert(enter() == -EACCES);
    message.msg_name = &local; message.msg_namelen = sizeof(local);
    start(PR_sendmsg, (word_t)&message, 0);
    assert(enter() == 0);
    copied_message = (void *)tracee.registers[CURRENT][SYSARG_2];
    assert(copied_message != &message && copied_message->msg_name != &local);
    assert(ntohs(((struct sockaddr_in *)copied_message->msg_name)->sin_port) == 26003);
    messages[0].msg_hdr = message; messages[1].msg_hdr = message;
    messages[1].msg_hdr.msg_name = &remote;
    start(PR_sendmmsg, (word_t)messages, 2);
    assert(enter() == -EACCES);
    messages[1].msg_hdr = message;
    start(PR_sendmmsg, (word_t)messages, 2);
    assert(enter() == 0);
    copied_messages = (void *)tracee.registers[CURRENT][SYSARG_2];
    assert(copied_messages != messages);
    copied_messages[0].msg_len = 17; copied_messages[1].msg_len = 23;
    tracee.registers[CURRENT][SYSARG_RESULT] = 2;
    assert(eve_client_network_callback(&extension, SYSCALL_EXIT_START, 0, 0) == 0);
    assert(messages[0].msg_len == 17 && messages[1].msg_len == 23);
    assert(messages[0].msg_hdr.msg_name == &local);
    start(PR_io_uring_setup, 0, 0); assert(enter() == -EACCES);
    start(PR_socketcall, 0, 0); assert(enter() == -EACCES);
    puts("Actual PRoot callback: TCP/UDP/message egress checks, frozen arguments, child policy and sendmmsg output passed");
    return 0;
}

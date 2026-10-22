/* SPDX-License-Identifier: GPL-2.0-or-later
 * Shared by the actual PRoot filter builder and host BPF regression fixtures.
 * No tracee memory is dereferenced: every nonzero pointer/length stays trapped.
 */
#ifndef EVE_SENDTO_FILTER_H
#define EVE_SENDTO_FILTER_H
#include <stddef.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#define EVE_SENDTO_FILTER_LENGTH 11
#define EVE_SENDTO_FILTER(syscall, flag) \
 BPF_JUMP(BPF_JMP + BPF_JEQ + BPF_K, (syscall), 0, 10), \
 BPF_STMT(BPF_LD + BPF_W + BPF_ABS, offsetof(struct seccomp_data, args[4])), \
 BPF_JUMP(BPF_JMP + BPF_JEQ + BPF_K, 0, 0, 7), \
 BPF_STMT(BPF_LD + BPF_W + BPF_ABS, offsetof(struct seccomp_data, args[4]) + 4), \
 BPF_JUMP(BPF_JMP + BPF_JEQ + BPF_K, 0, 0, 5), \
 BPF_STMT(BPF_LD + BPF_W + BPF_ABS, offsetof(struct seccomp_data, args[5])), \
 BPF_JUMP(BPF_JMP + BPF_JEQ + BPF_K, 0, 0, 3), \
 BPF_STMT(BPF_LD + BPF_W + BPF_ABS, offsetof(struct seccomp_data, args[5]) + 4), \
 BPF_JUMP(BPF_JMP + BPF_JEQ + BPF_K, 0, 0, 1), \
 BPF_STMT(BPF_RET + BPF_K, SECCOMP_RET_ALLOW), \
 BPF_STMT(BPF_RET + BPF_K, SECCOMP_RET_TRACE + (flag))
#endif

/* SPDX-License-Identifier: GPL-2.0-or-later
 * Opt-in PRoot socket policy for the EVE startup/login session.
 * The immutable server runtime and ordinary PRoot sessions are unchanged.
 */
#define _GNU_SOURCE 1
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <linux/netlink.h>

/* Return one when a private syscall argument must replace this address.
 * Never modify the caller's shared sockaddr: another Wine thread may use it.
 */
static int eve_address(struct sockaddr_storage *storage, size_t length, int binding)
{
	if (length < sizeof(sa_family_t)) return -EINVAL;
	switch (storage->ss_family) {
	case AF_UNIX:
	case AF_NETLINK:
		return 0;
	case AF_UNSPEC: /* UDP disconnect, not a new destination. */
		return binding ? -EAFNOSUPPORT : 0;
	case AF_INET: {
		struct sockaddr_in *in = (struct sockaddr_in *)storage;
		uint32_t ip;
		int changed = 0;
		if (length < sizeof(*in)) return -EINVAL;
		ip = ntohl(in->sin_addr.s_addr);
		if (binding && ip == INADDR_ANY) {
			in->sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			changed = 1;
		} else if ((ip >> 24) != 127) return -EACCES;
		if (!binding && ntohs(in->sin_port) == 443) {
			in->sin_port = htons(26003);
			changed = 1;
		}
		return changed;
	}
	case AF_INET6: {
		struct sockaddr_in6 *in = (struct sockaddr_in6 *)storage;
		int changed = 0;
		if (length < sizeof(*in)) return -EINVAL;
		if (binding && IN6_IS_ADDR_UNSPECIFIED(&in->sin6_addr)) {
			in->sin6_addr = in6addr_loopback;
			changed = 1;
		} else if (IN6_IS_ADDR_V4MAPPED(&in->sin6_addr)) {
			if (in->sin6_addr.s6_addr[12] != 127) return -EACCES;
		} else if (!IN6_IS_ADDR_LOOPBACK(&in->sin6_addr)) return -EACCES;
		if (!binding && ntohs(in->sin6_port) == 443) {
			/* The server listens on IPv4. A dual-stack IPv6 socket
			 * reaches it through a mapped address; AF_INET would be
			 * invalid for the original AF_INET6 socket. */
			if (IN6_IS_ADDR_LOOPBACK(&in->sin6_addr)) {
				memset(&in->sin6_addr, 0, sizeof(in->sin6_addr));
				in->sin6_addr.s6_addr[10] = 0xff;
				in->sin6_addr.s6_addr[11] = 0xff;
				in->sin6_addr.s6_addr[12] = 127;
				in->sin6_addr.s6_addr[15] = 1;
			}
			in->sin6_port = htons(26003);
			changed = 1;
		}
		return changed;
	}
	default:
		return -EAFNOSUPPORT;
	}
}

static int eve_socket(int domain, int type, int protocol)
{
	if (domain == AF_UNIX) return 0;
	if (domain == AF_NETLINK) return protocol == NETLINK_ROUTE ? 0 : -EACCES;
	if (domain != AF_INET && domain != AF_INET6) return -EAFNOSUPPORT;
	type &= ~(SOCK_CLOEXEC | SOCK_NONBLOCK);
	return type == SOCK_STREAM || type == SOCK_DGRAM ? 0 : -EACCES;
}

#ifndef EVE_NETWORK_POLICY_ONLY
#include "extension/extension.h"
#include "tracee/tracee.h"
#include "tracee/abi.h"
#include "tracee/mem.h"
#include "syscall/sysnum.h"

static int eve_check_address(Tracee *tracee, word_t address, word_t length,
		int binding, word_t *replacement)
{
	struct sockaddr_storage storage;
	int status;
	*replacement = address;
	if (address == 0) return length == 0 ? 0 : -EFAULT;
	if (length > sizeof(storage)) return -EINVAL;
	memset(&storage, 0, sizeof(storage));
	status = read_data(tracee, &storage, address, length);
	if (status < 0) return status;
	status = eve_address(&storage, length, binding);
	if (status < 0) {
		fprintf(stderr, "EVE client network: blocked socket destination family=%u errno=%d\n",
			(unsigned) storage.ss_family, -status);
		return status;
	}
	if (storage.ss_family != AF_INET && storage.ss_family != AF_INET6) return 0;
	/* Freeze every validated IP destination, including unchanged loopback
	 * addresses, so shared Wine thread memory cannot change after checking. */
	*replacement = alloc_mem(tracee, length);
	if (*replacement == 0) return -ENOMEM;
	if (status > 0 && !binding
	    && ((storage.ss_family == AF_INET && ntohs(((struct sockaddr_in *)&storage)->sin_port) == 26003)
	        || (storage.ss_family == AF_INET6 && ntohs(((struct sockaddr_in6 *)&storage)->sin6_port) == 26003)))
		fprintf(stderr, "EVE client network: localhost:443 -> 26003\n");
	return write_data(tracee, *replacement, &storage, length);
}

static int eve_check_message(Tracee *tracee, struct msghdr *message)
{
	word_t replacement;
	int status;
	status = eve_check_address(tracee, (word_t) message->msg_name,
		message->msg_namelen, 0, &replacement);
	if (status < 0) return status;
	message->msg_name = (void *)replacement;
	return 0;
}

int eve_client_network_callback(Extension *extension, ExtensionEvent event,
		intptr_t data1 UNUSED, intptr_t data2 UNUSED)
{
	Tracee *tracee = TRACEE(extension);
	static FilteredSysnum filtered[] = {
		{ PR_socket, FILTER_SYSEXIT }, { PR_socketpair, FILTER_SYSEXIT },
		/* These checks only replace immutable input arguments at entry. PRoot
		 * restores the stack before the next syscall without an exit stop.
		 * sendmmsg still needs exit notification for msg_len copyback. */
		{ PR_connect, 0 }, { PR_bind, 0 },
		{ PR_sendto, 0 }, { PR_sendmsg, 0 },
		{ PR_sendmmsg, FILTER_SYSEXIT }, { PR_socketcall, FILTER_SYSEXIT },
		{ PR_io_uring_setup, FILTER_SYSEXIT }, { PR_io_uring_enter, FILTER_SYSEXIT },
		{ PR_io_uring_register, FILTER_SYSEXIT }, FILTERED_SYSNUM_END
	};
	if (event == INITIALIZATION) {
		extension->filtered_sysnums = filtered;
		fprintf(stderr, "EVE client network: loopback gate active; localhost:443 -> 26003\n");
		return 0;
	}
	if (event == INHERIT_PARENT) return 1;
	if (event == INHERIT_CHILD) {
		extension->filtered_sysnums = filtered;
		return 0;
	}
	if (event == SYSCALL_EXIT_START && get_sysnum(tracee, ORIGINAL) == PR_sendmmsg) {
		/* sendmmsg reports each sent length through the original array.
		 * Only the input copy was private; copy those output fields back. */
		word_t original = peek_reg(tracee, ORIGINAL, SYSARG_2);
		word_t copied = peek_reg(tracee, MODIFIED, SYSARG_2);
		long sent = (long)peek_reg(tracee, CURRENT, SYSARG_RESULT);
		word_t index;
		if (tracee->status >= 0 && sent > 0 && sent <= 1024 && copied != original) {
			for (index = 0; index < (word_t)sent; index++) {
				unsigned length;
				size_t offset = index * sizeof(struct mmsghdr) + offsetof(struct mmsghdr, msg_len);
				int status = read_data(tracee, &length, copied + offset, sizeof(length));
				if (status < 0) return status;
				status = write_data(tracee, original + offset, &length, sizeof(length));
				if (status < 0) return status;
			}
		}
		return 0;
	}
	if (event != SYSCALL_ENTER_START) return 0;
	switch (get_sysnum(tracee, ORIGINAL)) {
	case PR_socket:
		return eve_socket(peek_reg(tracee, ORIGINAL, SYSARG_1),
			peek_reg(tracee, ORIGINAL, SYSARG_2), peek_reg(tracee, ORIGINAL, SYSARG_3));
	case PR_socketpair:
		return peek_reg(tracee, ORIGINAL, SYSARG_1) == AF_UNIX ? 0 : -EAFNOSUPPORT;
	case PR_socketcall: /* This APK's Wine/FEX host ABI is native ARM64. */
	case PR_io_uring_setup:
	case PR_io_uring_enter:
	case PR_io_uring_register:
		return -EACCES;
	case PR_connect:
	case PR_bind:
	case PR_sendto: {
		Sysnum syscall = get_sysnum(tracee, ORIGINAL);
		Reg argument = syscall == PR_sendto ? SYSARG_5 : SYSARG_2;
		Reg length_argument = syscall == PR_sendto ? SYSARG_6 : SYSARG_3;
		word_t replacement;
		int status = eve_check_address(tracee, peek_reg(tracee, ORIGINAL, argument),
			peek_reg(tracee, ORIGINAL, length_argument), syscall == PR_bind, &replacement);
		if (status < 0) return status;
		poke_reg(tracee, argument, replacement);
		return 0;
	}
	case PR_sendmsg: {
		struct msghdr message;
		word_t source = peek_reg(tracee, ORIGINAL, SYSARG_2), target;
		int status;
		if (sizeof_word(tracee) != sizeof(void *)) return -EAFNOSUPPORT;
		status = read_data(tracee, &message, source, sizeof(message));
		if (status < 0) return status;
		status = eve_check_message(tracee, &message);
		if (status < 0) return status;
		if ((word_t)message.msg_name == 0) return 0;
		target = alloc_mem(tracee, sizeof(message));
		if (target == 0) return -ENOMEM;
		status = write_data(tracee, target, &message, sizeof(message));
		if (status < 0) return status;
		poke_reg(tracee, SYSARG_2, target);
		return 0;
	}
	case PR_sendmmsg: {
		struct mmsghdr messages[1024];
		word_t count = peek_reg(tracee, ORIGINAL, SYSARG_3), target;
		size_t size;
		int status;
		word_t index;
		if (sizeof_word(tracee) != sizeof(void *)) return -EAFNOSUPPORT;
		if (count > 1024) return -EINVAL;
		if (count == 0) return 0;
		size = count * sizeof(messages[0]);
		status = read_data(tracee, messages, peek_reg(tracee, ORIGINAL, SYSARG_2), size);
		if (status < 0) return status;
		for (index = 0; index < count; index++) {
			status = eve_check_message(tracee, &messages[index].msg_hdr);
			if (status < 0) return status;
		}
		target = alloc_mem(tracee, size);
		if (target == 0) return -ENOMEM;
		status = write_data(tracee, target, messages, size);
		if (status < 0) return status;
		poke_reg(tracee, SYSARG_2, target);
		return 0;
	}
	default:
		return 0;
	}
}
#endif

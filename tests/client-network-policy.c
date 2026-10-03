#define EVE_NETWORK_POLICY_ONLY 1
#include "../native/eve-client-network.c"
#include <assert.h>

static struct sockaddr_storage ipv4(const char *ip, int port)
{
	struct sockaddr_storage storage = {0};
	struct sockaddr_in *in = (struct sockaddr_in *)&storage;
	in->sin_family = AF_INET;
	in->sin_port = htons(port);
	assert(inet_pton(AF_INET, ip, &in->sin_addr) == 1);
	return storage;
}

static struct sockaddr_storage ipv6(const char *ip, int port)
{
	struct sockaddr_storage storage = {0};
	struct sockaddr_in6 *in = (struct sockaddr_in6 *)&storage;
	in->sin6_family = AF_INET6;
	in->sin6_port = htons(port);
	assert(inet_pton(AF_INET6, ip, &in->sin6_addr) == 1);
	return storage;
}

int main(void)
{
	struct sockaddr_storage storage;
	storage = ipv4("127.0.0.1", 443);
	assert(eve_address(&storage, sizeof(struct sockaddr_in), 0) == 1);
	assert(ntohs(((struct sockaddr_in *)&storage)->sin_port) == 26003);
	storage = ipv4("127.0.0.1", 26000);
	assert(eve_address(&storage, sizeof(struct sockaddr_in), 0) == 0);
	storage = ipv4("192.0.2.1", 443);
	assert(eve_address(&storage, sizeof(struct sockaddr_in), 0) == -EACCES);
	storage = ipv4("192.168.1.2", 26000);
	assert(eve_address(&storage, sizeof(struct sockaddr_in), 1) == -EACCES);
	storage = ipv4("0.0.0.0", 0);
	assert(eve_address(&storage, sizeof(struct sockaddr_in), 1) == 1);
	assert(ntohl(((struct sockaddr_in *)&storage)->sin_addr.s_addr) == INADDR_LOOPBACK);
	storage = ipv6("::1", 443);
	assert(eve_address(&storage, sizeof(struct sockaddr_in6), 0) == 1);
	assert(IN6_IS_ADDR_V4MAPPED(&((struct sockaddr_in6 *)&storage)->sin6_addr));
	assert(((struct sockaddr_in6 *)&storage)->sin6_addr.s6_addr[12] == 127);
	assert(ntohs(((struct sockaddr_in6 *)&storage)->sin6_port) == 26003);
	storage = ipv6("::ffff:127.0.0.1", 443);
	assert(eve_address(&storage, sizeof(struct sockaddr_in6), 0) == 1);
	storage = ipv6("::ffff:192.0.2.1", 443);
	assert(eve_address(&storage, sizeof(struct sockaddr_in6), 0) == -EACCES);
	storage = ipv6("2001:db8::1", 443);
	assert(eve_address(&storage, sizeof(struct sockaddr_in6), 0) == -EACCES);
	storage = ipv6("::", 0);
	assert(eve_address(&storage, sizeof(struct sockaddr_in6), 1) == 1);
	assert(IN6_IS_ADDR_LOOPBACK(&((struct sockaddr_in6 *)&storage)->sin6_addr));
	memset(&storage, 0, sizeof(storage));
	storage.ss_family = AF_UNSPEC;
	assert(eve_address(&storage, sizeof(struct sockaddr_in), 1) == -EAFNOSUPPORT);
	assert(eve_address(&storage, sizeof(struct sockaddr_in), 0) == 0);
	storage.ss_family = AF_UNIX;
	assert(eve_address(&storage, sizeof(storage), 0) == 0);
	assert(eve_address(&storage, 1, 0) == -EINVAL);
	storage.ss_family = AF_INET;
	assert(eve_address(&storage, sizeof(sa_family_t), 0) == -EINVAL);
	assert(eve_socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0) == 0);
	assert(eve_socket(AF_INET6, SOCK_DGRAM | SOCK_NONBLOCK, 0) == 0);
	assert(eve_socket(AF_INET, SOCK_RAW, 0) == -EACCES);
	assert(eve_socket(AF_PACKET, SOCK_RAW, 0) == -EAFNOSUPPORT);
	assert(eve_socket(AF_NETLINK, SOCK_RAW, NETLINK_ROUTE) == 0);
	assert(eve_socket(AF_NETLINK, SOCK_RAW, NETLINK_KOBJECT_UEVENT) == -EACCES);
	puts("EVE socket policy IPv4/IPv6, TLS remap, LAN/remote/raw denial and loopback binds passed");
	return 0;
}

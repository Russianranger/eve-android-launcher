/* Small syscall-register/memory fixture for the real PRoot callback. */
#include <assert.h>
#include <stdint.h>
#include <string.h>
#define UNUSED __attribute__((unused))
typedef uintptr_t word_t;
typedef enum { ORIGINAL, CURRENT, MODIFIED } RegVersion;
typedef enum { SYSARG_1, SYSARG_2, SYSARG_3, SYSARG_4, SYSARG_5, SYSARG_6, SYSARG_RESULT } Reg;
typedef enum { PR_socket, PR_socketpair, PR_connect, PR_bind, PR_sendto,
    PR_sendmsg, PR_sendmmsg, PR_socketcall, PR_io_uring_setup,
    PR_io_uring_enter, PR_io_uring_register } Sysnum;
typedef enum { INITIALIZATION, INHERIT_PARENT, INHERIT_CHILD,
    SYSCALL_ENTER_START, SYSCALL_EXIT_START } ExtensionEvent;
typedef struct { Sysnum number; unsigned flags; } FilteredSysnum;
#define FILTER_SYSEXIT 1
#define FILTERED_SYSNUM_END {0, 0}
typedef struct {
    word_t registers[3][7];
    Sysnum syscall;
    int status;
    unsigned char scratch[128 * 1024];
    size_t used;
} Tracee;
typedef struct { Tracee *tracee; FilteredSysnum *filtered_sysnums; } Extension;
#define TRACEE(extension) ((extension)->tracee)
static word_t peek_reg(const Tracee *tracee, RegVersion version, Reg reg)
{ return tracee->registers[version][reg]; }
static void poke_reg(Tracee *tracee, Reg reg, word_t value)
{ tracee->registers[CURRENT][reg] = value; }
static Sysnum get_sysnum(const Tracee *tracee, RegVersion version UNUSED)
{ return tracee->syscall; }
static size_t sizeof_word(const Tracee *tracee UNUSED) { return sizeof(word_t); }
static int read_data(const Tracee *tracee UNUSED, void *destination, word_t address, word_t size)
{ memcpy(destination, (void *)address, size); return 0; }
static int write_data(Tracee *tracee UNUSED, word_t address, const void *source, word_t size)
{ memcpy((void *)address, source, size); return 0; }
static word_t alloc_mem(Tracee *tracee, ssize_t size)
{
    word_t result = (word_t)&tracee->scratch[tracee->used];
    size_t next = (size + 15) & ~(size_t)15;
    assert(tracee->used + next <= sizeof(tracee->scratch));
    tracee->used += next;
    return result;
}

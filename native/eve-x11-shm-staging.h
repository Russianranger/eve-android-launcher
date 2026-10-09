/* SPDX-License-Identifier: MIT
 * Separate CPU staging for the private software-framebuffer Xvnc transport.
 * The Vulkan source remains owned by Mesa. Never replace its rendering fence.
 * Included both by the checksum-locked Mesa WSI patch and the native fixture.
 */
#ifndef EVE_X11_SHM_STAGING_H
#define EVE_X11_SHM_STAGING_H

#include <xcb/xcb.h>
#include <xcb/xcbext.h>
#include <xcb/shm.h>
#include <sys/ipc.h>
#include <sys/shm.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <time.h>

/* Match libxcb 1.15's generated fixed-size MIT-SHM requests while using only
 * the existing core libxcb ABI. The installed shm.h supplies the protocol
 * structs/opcodes; no libxcb-shm symbols or SONAME are required. This extension
 * ID is lazily allocated and cached by core XCB, just like generated bindings.
 */
static xcb_extension_t eve_x11_shm_extension = {"MIT-SHM", 0};
_Static_assert(sizeof(xcb_shm_query_version_request_t) == 4, "MIT-SHM QueryVersion layout");
_Static_assert(sizeof(xcb_shm_attach_request_t) == 16, "MIT-SHM Attach layout");
_Static_assert(sizeof(xcb_shm_detach_request_t) == 8, "MIT-SHM Detach layout");
_Static_assert(sizeof(xcb_shm_put_image_request_t) == 40, "MIT-SHM PutImage layout");

static inline unsigned
eve_x11_shm_send_fixed(xcb_connection_t *conn, void *payload, size_t size,
                      uint8_t opcode, uint8_t is_void)
{
   xcb_protocol_request_t protocol = {
      .count = 2, .ext = &eve_x11_shm_extension, .opcode = opcode, .isvoid = is_void,
   };
   /* XCB reserves indices -2 and -1 relative to the supplied vector. It fills
    * the major/minor opcode and length in the native-order protocol header. */
   struct iovec parts[4] = {{0}};
   parts[2].iov_base = payload;
   parts[2].iov_len = size;
   parts[3].iov_base = NULL;
   parts[3].iov_len = (0 - size) & 3;
   return xcb_send_request(conn, XCB_REQUEST_CHECKED, parts + 2, &protocol);
}

static inline xcb_shm_query_version_cookie_t
eve_x11_shm_query_version(xcb_connection_t *conn)
{
   xcb_shm_query_version_request_t request = {0};
   return (xcb_shm_query_version_cookie_t) {
      .sequence = eve_x11_shm_send_fixed(conn, &request, sizeof(request), XCB_SHM_QUERY_VERSION, 0),
   };
}

static inline xcb_shm_query_version_reply_t *
eve_x11_shm_query_version_reply(xcb_connection_t *conn,
                               xcb_shm_query_version_cookie_t cookie,
                               xcb_generic_error_t **error)
{
   return (xcb_shm_query_version_reply_t *)xcb_wait_for_reply(conn, cookie.sequence, error);
}

static inline xcb_void_cookie_t
eve_x11_shm_attach_checked(xcb_connection_t *conn, xcb_shm_seg_t segment,
                          uint32_t shmid, uint8_t read_only)
{
   xcb_shm_attach_request_t request = {
      .shmseg = segment, .shmid = shmid, .read_only = read_only,
   };
   return (xcb_void_cookie_t) {
      .sequence = eve_x11_shm_send_fixed(conn, &request, sizeof(request), XCB_SHM_ATTACH, 1),
   };
}

static inline xcb_void_cookie_t
eve_x11_shm_detach_checked(xcb_connection_t *conn, xcb_shm_seg_t segment)
{
   xcb_shm_detach_request_t request = {.shmseg = segment};
   return (xcb_void_cookie_t) {
      .sequence = eve_x11_shm_send_fixed(conn, &request, sizeof(request), XCB_SHM_DETACH, 1),
   };
}

static inline xcb_void_cookie_t
eve_x11_shm_put_image_checked(xcb_connection_t *conn, xcb_drawable_t drawable,
                             xcb_gcontext_t gc, uint16_t total_width,
                             uint16_t total_height, uint16_t source_width,
                             uint16_t source_height, uint8_t depth,
                             xcb_shm_seg_t segment)
{
   xcb_shm_put_image_request_t request = {
      .drawable = drawable, .gc = gc, .total_width = total_width,
      .total_height = total_height, .src_width = source_width,
      .src_height = source_height, .depth = depth,
      .format = XCB_IMAGE_FORMAT_Z_PIXMAP, .shmseg = segment,
   };
   /* Source/destination coordinates, send_event, offset and padding are zero. */
   return (xcb_void_cookie_t) {
      .sequence = eve_x11_shm_send_fixed(conn, &request, sizeof(request), XCB_SHM_PUT_IMAGE, 1),
   };
}

#define EVE_X11_SHM_MAX_BYTES (32u * 1024u * 1024u)
#ifndef EVE_X11_SHM_SHMGET
#define EVE_X11_SHM_SHMGET shmget
#endif
#ifndef EVE_X11_SHM_SHMAT
#define EVE_X11_SHM_SHMAT shmat
#endif
#ifndef EVE_X11_SHM_ATTACH
#define EVE_X11_SHM_ATTACH eve_x11_shm_attach_checked
#endif

enum eve_x11_shm_result {
   EVE_X11_SHM_OK,
   EVE_X11_SHM_FALLBACK,
   EVE_X11_SHM_OUT_OF_DATE,
   EVE_X11_SHM_SURFACE_LOST,
};

struct eve_x11_shm_stage {
   int shmid;
   uint8_t *map;
   size_t size;
   uint32_t row_pitch;
   uint16_t width, height, total_width;
   xcb_shm_seg_t segment;
   bool attached, marked, enabled, pending, fallback_reported, pending_sampled;
   uint64_t stage_id, completed_presents, pending_copy_ns;
   xcb_void_cookie_t put_cookie;
   xcb_get_geometry_cookie_t barrier_cookie;
};

static inline uint64_t
eve_x11_shm_now(void)
{
   struct timespec value;
   if (clock_gettime(CLOCK_MONOTONIC, &value) != 0)
      return 0;
   return (uint64_t)value.tv_sec * UINT64_C(1000000000) + value.tv_nsec;
}

static inline uint64_t
eve_x11_shm_elapsed(uint64_t start)
{
   uint64_t end = eve_x11_shm_now();
   return start && end >= start ? end - start : 0;
}

static inline void
eve_x11_shm_fallback(struct eve_x11_shm_stage *stage, const char *reason)
{
   stage->enabled = false;
   if (stage->fallback_reported)
      return;
   stage->fallback_reported = true;
   /* reason is always a fixed internal literal, never user input. */
   fprintf(stderr, "EVE_X11_SHM {\"format\":\"eve-x11-shm-1\","
           "\"mode\":\"fallback\",\"stageId\":%" PRIu64 ",\"reason\":\"%s\"}\n",
           stage->stage_id, reason);
}

static inline enum eve_x11_shm_result
eve_x11_shm_stage_wait(struct eve_x11_shm_stage *stage, xcb_connection_t *conn)
{
   if (!stage->pending)
      return stage->enabled ? EVE_X11_SHM_OK : EVE_X11_SHM_FALLBACK;

   uint64_t began = stage->pending_sampled ? eve_x11_shm_now() : 0;
   xcb_generic_error_t *geometry_error = NULL;
   xcb_get_geometry_reply_t *geometry = xcb_get_geometry_reply(
      conn, stage->barrier_cookie, &geometry_error);
   /* This reply's request was queued AFTER the checked SHM PutImage on the
    * same connection. Our private fb Xvnc has finished reading the segment.
    * Do not mark it reusable before this reply or a terminal connection error.
    */
   xcb_generic_error_t *put_error = xcb_request_check(conn, stage->put_cookie);
   stage->pending = false;
   uint64_t waited = stage->pending_sampled ? eve_x11_shm_elapsed(began) : 0;
   enum eve_x11_shm_result result = EVE_X11_SHM_OK;
   if (!geometry || geometry_error || xcb_connection_has_error(conn)) {
      eve_x11_shm_fallback(stage, "surface_lost");
      result = EVE_X11_SHM_SURFACE_LOST;
   } else if (put_error) {
      eve_x11_shm_fallback(stage, "put_rejected");
      result = EVE_X11_SHM_FALLBACK;
   } else {
      if (stage->completed_presents == UINT64_MAX) {
         eve_x11_shm_fallback(stage, "counter_limit");
         result = EVE_X11_SHM_FALLBACK;
      } else {
         stage->completed_presents++;
         if (stage->completed_presents <= 3 || stage->completed_presents % 300 == 0)
            fprintf(stderr, "EVE_X11_SHM {\"format\":\"eve-x11-shm-1\","
                    "\"mode\":\"active\",\"stageId\":%" PRIu64 ","
                    "\"width\":%u,\"height\":%u,\"rowPitch\":%u,"
                    "\"sizeBytes\":%zu,\"completedPresents\":%" PRIu64 ","
                    "\"pendingBeforeOverwrite\":false,\"barrierAfterPut\":true,"
                    "\"copyNs\":%" PRIu64 ",\"serverWaitNs\":%" PRIu64 "}\n",
                    stage->stage_id, stage->width, stage->height, stage->row_pitch,
                    stage->size, stage->completed_presents, stage->pending_copy_ns, waited);
      }
      if (result == EVE_X11_SHM_OK &&
          (geometry->width != stage->width || geometry->height != stage->height))
         result = EVE_X11_SHM_OUT_OF_DATE;
   }
   free(geometry_error);
   free(put_error);
   free(geometry);
   return result;
}

static inline void
eve_x11_shm_stage_finish(struct eve_x11_shm_stage *stage, xcb_connection_t *conn)
{
   if (!stage->stage_id) {
      stage->shmid = -1;
      return;
   }
   if (stage->pending)
      (void)eve_x11_shm_stage_wait(stage, conn);
   if (stage->attached) {
      if (!xcb_connection_has_error(conn)) {
         xcb_generic_error_t *error = xcb_request_check(
            conn, eve_x11_shm_detach_checked(conn, stage->segment));
         free(error);
      }
      stage->attached = false;
   }
   if (stage->map) {
      (void)shmdt(stage->map);
      stage->map = NULL;
   }
   if (stage->shmid >= 0 && !stage->marked)
      (void)shmctl(stage->shmid, IPC_RMID, NULL);
   stage->shmid = -1;
   stage->segment = 0;
   stage->enabled = false;
   stage->pending = false;
   stage->size = 0;
}

static inline bool
eve_x11_shm_stage_init(struct eve_x11_shm_stage *stage, xcb_connection_t *conn,
                      uint32_t width, uint32_t height, uint32_t row_pitch,
                      size_t source_capacity)
{
   static atomic_uint_fast64_t next_stage_id = ATOMIC_VAR_INIT(1);
   memset(stage, 0, sizeof(*stage));
   stage->shmid = -1;
   stage->stage_id = atomic_fetch_add_explicit(&next_stage_id, 1, memory_order_relaxed);
   uint64_t bytes = (uint64_t)row_pitch * height;
   if (!stage->stage_id || !width || !height || width > UINT16_MAX ||
       height > UINT16_MAX || row_pitch % 4 || (uint64_t)width * 4 > row_pitch ||
       row_pitch / 4 > UINT16_MAX || !bytes || bytes > EVE_X11_SHM_MAX_BYTES ||
       bytes > source_capacity || bytes > SIZE_MAX) {
      eve_x11_shm_fallback(stage, "bounds");
      return false;
   }
   const xcb_query_extension_reply_t *extension = xcb_get_extension_data(conn, &eve_x11_shm_extension);
   if (!extension || !extension->present || xcb_connection_has_error(conn)) {
      eve_x11_shm_fallback(stage, "extension_unavailable");
      return false;
   }
   /* Shared pixmaps, DRI3 and external Vulkan host imports are unnecessary. */
   xcb_generic_error_t *version_error = NULL;
   xcb_shm_query_version_reply_t *version = eve_x11_shm_query_version_reply(
      conn, eve_x11_shm_query_version(conn), &version_error);
   bool version_ok = version && !version_error && version->major_version >= 1;
   free(version);
   free(version_error);
   if (!version_ok) {
      eve_x11_shm_fallback(stage, "version_unavailable");
      return false;
   }
   stage->size = (size_t)bytes;
   stage->width = width;
   stage->height = height;
   stage->total_width = row_pitch / 4;
   stage->row_pitch = row_pitch;
   stage->shmid = EVE_X11_SHM_SHMGET(IPC_PRIVATE, stage->size, IPC_CREAT | 0600);
   if (stage->shmid < 0) {
      eve_x11_shm_fallback(stage, "allocation_failed");
      eve_x11_shm_stage_finish(stage, conn);
      return false;
   }
   void *mapped = EVE_X11_SHM_SHMAT(stage->shmid, NULL, 0);
   if (mapped == (void *)-1) {
      eve_x11_shm_fallback(stage, "map_failed");
      eve_x11_shm_stage_finish(stage, conn);
      return false;
   }
   stage->map = mapped;
   /* Linux and our pinned PRoot retain marked segments while a mapping exists.
    * Mark before remote attach so abrupt client exit cannot strand a segment.
    */
   if (shmctl(stage->shmid, IPC_RMID, NULL) != 0) {
      eve_x11_shm_fallback(stage, "mark_failed");
      eve_x11_shm_stage_finish(stage, conn);
      return false;
   }
   stage->marked = true;
   stage->segment = xcb_generate_id(conn);
   xcb_generic_error_t *attach_error = xcb_request_check(conn,
      EVE_X11_SHM_ATTACH(conn, stage->segment, stage->shmid, 1));
   bool attached = !attach_error && !xcb_connection_has_error(conn);
   free(attach_error);
   if (!attached) {
      eve_x11_shm_fallback(stage, "attach_rejected");
      eve_x11_shm_stage_finish(stage, conn);
      return false;
   }
   stage->attached = true;
   stage->enabled = true;
   return true;
}

static inline enum eve_x11_shm_result
eve_x11_shm_stage_put(struct eve_x11_shm_stage *stage, xcb_connection_t *conn,
                     xcb_drawable_t drawable, xcb_gcontext_t gc, uint8_t depth,
                     const void *source, size_t source_capacity)
{
   if (!stage->enabled)
      return EVE_X11_SHM_FALLBACK;
   enum eve_x11_shm_result result = eve_x11_shm_stage_wait(stage, conn);
   if (result != EVE_X11_SHM_OK)
      return result;
   if (!source || source_capacity < stage->size) {
      eve_x11_shm_fallback(stage, "source_bounds");
      return EVE_X11_SHM_FALLBACK;
   }
   stage->pending_sampled = stage->completed_presents < 3 ||
      (stage->completed_presents != UINT64_MAX && (stage->completed_presents + 1) % 300 == 0);
   uint64_t began = stage->pending_sampled ? eve_x11_shm_now() : 0;
   memcpy(stage->map, source, stage->size);
   stage->pending_copy_ns = stage->pending_sampled ? eve_x11_shm_elapsed(began) : 0;
   stage->put_cookie = eve_x11_shm_put_image_checked(
      conn, drawable, gc, stage->total_width, stage->height,
      stage->width, stage->height, depth, stage->segment);
   stage->barrier_cookie = xcb_get_geometry(conn, drawable);
   stage->pending = true;
   if (xcb_flush(conn) <= 0 || xcb_connection_has_error(conn))
      return eve_x11_shm_stage_wait(stage, conn);
   /* The independent staging bytes remain pending. Mesa can release its
    * Vulkan source now, but no caller can overwrite this stage before wait().
    */
   return EVE_X11_SHM_OK;
}

#endif

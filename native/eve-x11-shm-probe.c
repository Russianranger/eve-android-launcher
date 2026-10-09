/* SPDX-License-Identifier: MIT
 * CI-only native protocol/lifetime fixture using the exact production helper.
 * It does not initialize Turnip, render on Adreno, or claim an EVE FPS result.
 */
#define _POSIX_C_SOURCE 200809L
#include <xcb/xcb.h>
#include <xcb/shm.h>
#include <sys/ipc.h>
#include <sys/shm.h>
#include <errno.h>
#include <signal.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static int fault_mode, last_allocated = -1;
static inline xcb_void_cookie_t eve_x11_shm_attach_checked(
   xcb_connection_t *, xcb_shm_seg_t, uint32_t, uint8_t);
static int fixture_shmget(key_t key, size_t size, int flags)
{
   if (fault_mode == 1) { errno = ENOMEM; return -1; }
   return last_allocated = shmget(key, size, flags);
}
static void *fixture_shmat(int id, const void *address, int flags)
{
   if (fault_mode == 2) { errno = EACCES; return (void *)-1; }
   return shmat(id, address, flags);
}
static xcb_void_cookie_t fixture_attach(xcb_connection_t *conn,
                                       xcb_shm_seg_t segment, uint32_t id,
                                       uint8_t read_only)
{
   /* Exercise a real checked server rejection, not a mocked successful cookie. */
   return eve_x11_shm_attach_checked(conn, segment, fault_mode == 3 ? UINT32_MAX : id, read_only);
}
#define EVE_X11_SHM_SHMGET fixture_shmget
#define EVE_X11_SHM_SHMAT fixture_shmat
#define EVE_X11_SHM_ATTACH fixture_attach
#include "eve-x11-shm-staging.h"

struct surface {
   xcb_connection_t *conn;
   xcb_window_t window;
   xcb_gcontext_t gc;
   uint8_t depth;
   uint32_t width, height, pitch;
   uint8_t *source;
   size_t capacity;
};

static void pause_frame(void)
{
   struct timespec delay = {0, 650000000};
   while (nanosleep(&delay, &delay) && errno == EINTR) { }
}

static int check_cookie(xcb_connection_t *conn, xcb_void_cookie_t cookie)
{
   xcb_generic_error_t *error = xcb_request_check(conn, cookie);
   int good = !error && !xcb_connection_has_error(conn);
   free(error);
   return good;
}

static int surface_open(struct surface *surface, uint32_t width, uint32_t height)
{
   memset(surface, 0, sizeof(*surface));
   surface->conn = xcb_connect(NULL, NULL);
   if (xcb_connection_has_error(surface->conn)) return 0;
   xcb_screen_t *screen = xcb_setup_roots_iterator(xcb_get_setup(surface->conn)).data;
   if (!screen || screen->root_depth != 24 ||
       xcb_get_setup(surface->conn)->image_byte_order != XCB_IMAGE_ORDER_LSB_FIRST) return 0;
   surface->width = width; surface->height = height; surface->pitch = width * 4;
   surface->capacity = (size_t)surface->pitch * height;
   surface->depth = screen->root_depth;
   surface->source = malloc(surface->capacity);
   if (!surface->source) return 0;
   surface->window = xcb_generate_id(surface->conn);
   uint32_t black = 0;
   if (!check_cookie(surface->conn, xcb_create_window_checked(surface->conn,
       surface->depth, surface->window, screen->root, 0, 0, width, height, 0,
       XCB_WINDOW_CLASS_INPUT_OUTPUT, screen->root_visual, XCB_CW_BACK_PIXEL, &black))) return 0;
   surface->gc = xcb_generate_id(surface->conn);
   if (!check_cookie(surface->conn, xcb_create_gc_checked(
       surface->conn, surface->gc, surface->window, 0, NULL))) return 0;
   return check_cookie(surface->conn, xcb_map_window_checked(surface->conn, surface->window));
}

static void surface_close(struct surface *surface)
{
   if (surface->conn) {
      if (!xcb_connection_has_error(surface->conn)) {
         if (surface->gc) (void)check_cookie(surface->conn, xcb_free_gc_checked(surface->conn, surface->gc));
         if (surface->window) (void)check_cookie(surface->conn, xcb_destroy_window_checked(surface->conn, surface->window));
      }
      xcb_disconnect(surface->conn);
   }
   free(surface->source);
   memset(surface, 0, sizeof(*surface));
}

static void fill_frame(struct surface *surface, unsigned frame)
{
   static const uint8_t colors[3][3] = {{8,16,24}, {48,32,16}, {16,48,32}};
   for (uint32_t y = 0; y < surface->height; ++y)
      for (uint32_t x = 0; x < surface->width; ++x) {
         uint8_t *pixel = surface->source + (size_t)y * surface->pitch + x * 4;
         int center = x >= 64 && x < 128 && y >= 64 && y < 128;
         pixel[0] = center ? 64 : colors[frame % 3][2];
         pixel[1] = center ? 223 : colors[frame % 3][1];
         pixel[2] = center ? 32 : colors[frame % 3][0];
         pixel[3] = 255;
      }
}

static int verify_frame(struct surface *surface, unsigned frame)
{
   static const uint8_t colors[3][3] = {{8,16,24}, {48,32,16}, {16,48,32}};
   xcb_generic_error_t *error = NULL;
   xcb_get_image_reply_t *image = xcb_get_image_reply(surface->conn,
      xcb_get_image(surface->conn, XCB_IMAGE_FORMAT_Z_PIXMAP, surface->window,
                    0, 0, surface->width, surface->height, UINT32_MAX), &error);
   int good = image && !error && image->depth == 24 &&
      (size_t)xcb_get_image_data_length(image) == surface->capacity;
   if (good) {
      const uint8_t *pixels = xcb_get_image_data(image);
      const unsigned positions[][2] = {{34,34}, {96,96}, {0,0},
         {surface->width-1,surface->height-1}};
      for (size_t index = 0; index < sizeof(positions)/sizeof(positions[0]); ++index) {
         unsigned x = positions[index][0], y = positions[index][1];
         const uint8_t *pixel = pixels + (size_t)y * surface->pitch + x * 4;
         int center = x == 96 && y == 96;
         good = good && pixel[0] == (center ? 64 : colors[frame % 3][2]) &&
            pixel[1] == (center ? 223 : colors[frame % 3][1]) &&
            pixel[2] == (center ? 32 : colors[frame % 3][0]);
      }
   }
   free(error); free(image);
   return good;
}

static int ordinary_put(struct surface *surface)
{
   uint64_t maximum = (uint64_t)xcb_get_maximum_request_length(surface->conn) * 4;
   if (maximum <= sizeof(xcb_put_image_request_t) + surface->pitch) return 0;
   uint32_t lines = (maximum - sizeof(xcb_put_image_request_t) - 4) / surface->pitch;
   for (uint32_t y = 0; y < surface->height; y += lines) {
      uint32_t count = surface->height - y < lines ? surface->height - y : lines;
      if (!check_cookie(surface->conn, xcb_put_image_checked(surface->conn,
          XCB_IMAGE_FORMAT_Z_PIXMAP, surface->window, surface->gc,
          surface->width, count, 0, y, 0, surface->depth, count * surface->pitch,
          surface->source + (size_t)y * surface->pitch))) return 0;
   }
   return 1;
}

static int stage_gone(int id)
{
   struct shmid_ds stats;
   return id >= 0 && shmctl(id, IPC_STAT, &stats) == -1;
}

struct delayed_release {
   xcb_connection_t *connection;
   atomic_bool call_returned;
   int observed_blocked;
};

static void *release_server(void *argument)
{
   struct delayed_release *release = argument;
   struct timespec delay = {0, 200000000};
   while (nanosleep(&delay, &delay) && errno == EINTR) { }
   release->observed_blocked = !atomic_load_explicit(&release->call_returned, memory_order_acquire);
   (void)check_cookie(release->connection, xcb_ungrab_server_checked(release->connection));
   return NULL;
}

static int fixture_delayed_lifetime(struct surface *surface, int teardown)
{
   struct eve_x11_shm_stage stage;
   if (!eve_x11_shm_stage_init(&stage, surface->conn, surface->width,
       surface->height, surface->pitch, surface->capacity)) return 0;
   int id = stage.shmid;
   xcb_connection_t *grab = xcb_connect(NULL, NULL);
   int good = !xcb_connection_has_error(grab);
   if (good) {
      (void)xcb_grab_server(grab);
      xcb_get_input_focus_reply_t *focus = xcb_get_input_focus_reply(
         grab, xcb_get_input_focus(grab), NULL);
      good = focus != NULL;
      free(focus);
   }
   fill_frame(surface, 0);
   good = good && eve_x11_shm_stage_put(&stage, surface->conn, surface->window,
      surface->gc, surface->depth, surface->source, surface->capacity) == EVE_X11_SHM_OK && stage.pending;
   /* No synchronous image read occurs here: Xvnc is genuinely barred from
    * consuming that first SHM put. The Vulkan source is already independent. */
   memset(surface->source, 0xee, surface->capacity);
   struct delayed_release release = {.connection = grab};
   atomic_init(&release.call_returned, false);
   pthread_t thread;
   int started = good && pthread_create(&thread, NULL, release_server, &release) == 0;
   if (!started) {
      (void)check_cookie(grab, xcb_ungrab_server_checked(grab));
      eve_x11_shm_stage_finish(&stage, surface->conn);
      xcb_disconnect(grab);
      return 0;
   }
   uint64_t began = eve_x11_shm_now();
   if (teardown)
      eve_x11_shm_stage_finish(&stage, surface->conn);
   else {
      fill_frame(surface, 1);
      good = eve_x11_shm_stage_put(&stage, surface->conn, surface->window,
         surface->gc, surface->depth, surface->source, surface->capacity) == EVE_X11_SHM_OK;
   }
   atomic_store_explicit(&release.call_returned, true, memory_order_release);
   uint64_t waited = eve_x11_shm_elapsed(began);
   int joined = pthread_join(thread, NULL);
   good = good && joined == 0 && release.observed_blocked && waited >= 100000000;
   if (!teardown)
      good = good && eve_x11_shm_stage_wait(&stage, surface->conn) == EVE_X11_SHM_OK;
   good = good && stage.completed_presents == (teardown ? 1u : 2u) && verify_frame(surface, teardown ? 0 : 1);
   eve_x11_shm_stage_finish(&stage, surface->conn);
   good = good && stage_gone(id) && !stage.map && !stage.attached && !stage.pending;
   xcb_disconnect(grab);
   return good;
}

static int fixture_frames(struct surface *surface)
{
   struct eve_x11_shm_stage stages[3];
   memset(stages, 0, sizeof(stages));
   int good = fixture_delayed_lifetime(surface, 0) && fixture_delayed_lifetime(surface, 1);
   int pending_teardown = 0;
   for (unsigned i = 0; i < 3; ++i) {
      if (!eve_x11_shm_stage_init(&stages[i], surface->conn, surface->width,
          surface->height, surface->pitch, surface->capacity)) { good = 0; break; }
      fill_frame(surface, i);
      if (eve_x11_shm_stage_put(&stages[i], surface->conn, surface->window,
          surface->gc, surface->depth, surface->source, surface->capacity) != EVE_X11_SHM_OK)
         { good = 0; break; }
      /* Vulkan's source may immediately be reused after the independent copy. */
      memset(surface->source, 0xcc, surface->capacity);
      good = good && stages[i].pending && verify_frame(surface, i);
      pause_frame();
   }
   /* Repeated overwrite must drain that SAME stage's pending server read. */
   for (unsigned i = 0; good && i < 9; ++i) {
      fill_frame(surface, i);
      good = eve_x11_shm_stage_put(&stages[0], surface->conn, surface->window,
         surface->gc, surface->depth, surface->source, surface->capacity) == EVE_X11_SHM_OK;
      memset(surface->source, 0xdd, surface->capacity);
      good = good && verify_frame(surface, i);
   }
   for (unsigned i = 0; i < 3; ++i) {
      if (!stages[i].stage_id) continue;
      int id = stages[i].shmid;
      pending_teardown += stages[i].pending;
      eve_x11_shm_stage_finish(&stages[i], surface->conn);
      good = good && !stages[i].pending && !stages[i].map && !stages[i].attached &&
         stages[i].completed_presents >= 1 && stage_gone(id);
      eve_x11_shm_stage_finish(&stages[i], surface->conn);
   }
   good = good && pending_teardown == 3;

   /* Old-stage geometry mismatch cannot permit an unchecked overwrite. */
   struct eve_x11_shm_stage resize_stage;
   memset(&resize_stage, 0, sizeof(resize_stage));
   if (good) good = eve_x11_shm_stage_init(&resize_stage, surface->conn,
      surface->width, surface->height, surface->pitch, surface->capacity);
   if (good) {
      uint32_t extent[] = {320, 240};
      good = check_cookie(surface->conn, xcb_configure_window_checked(surface->conn,
         surface->window, XCB_CONFIG_WINDOW_WIDTH | XCB_CONFIG_WINDOW_HEIGHT, extent));
      fill_frame(surface, 0);
      good = good && eve_x11_shm_stage_put(&resize_stage, surface->conn, surface->window,
         surface->gc, surface->depth, surface->source, surface->capacity) == EVE_X11_SHM_OK;
      good = good && eve_x11_shm_stage_wait(&resize_stage, surface->conn) == EVE_X11_SHM_OUT_OF_DATE;
   }
   if (resize_stage.stage_id) {
      int id = resize_stage.shmid;
      eve_x11_shm_stage_finish(&resize_stage, surface->conn);
      good = good && stage_gone(id);
   }
   if (good) {
      free(surface->source);
      surface->width = 320; surface->height = 240; surface->pitch = 1280;
      surface->capacity = (size_t)surface->pitch * surface->height;
      surface->source = malloc(surface->capacity);
      good = surface->source != NULL;
      struct eve_x11_shm_stage replacement;
      memset(&replacement, 0, sizeof(replacement));
      if (good) good = eve_x11_shm_stage_init(&replacement, surface->conn,
         surface->width, surface->height, surface->pitch, surface->capacity);
      if (good) {
         fill_frame(surface, 2);
         good = eve_x11_shm_stage_put(&replacement, surface->conn, surface->window,
            surface->gc, surface->depth, surface->source, surface->capacity) == EVE_X11_SHM_OK &&
            eve_x11_shm_stage_wait(&replacement, surface->conn) == EVE_X11_SHM_OK && verify_frame(surface, 2);
      }
      if (replacement.stage_id) {
         int id = replacement.shmid;
         eve_x11_shm_stage_finish(&replacement, surface->conn);
         good = good && stage_gone(id);
      }
   }
   return good;
}

static int fixture_negatives(struct surface *surface)
{
   int good = 1;
   for (int fault = 1; fault <= 3; ++fault) {
      fault_mode = fault; last_allocated = -1;
      struct eve_x11_shm_stage stage;
      int created = eve_x11_shm_stage_init(&stage, surface->conn,
         surface->width, surface->height, surface->pitch, surface->capacity);
      good = good && !created && !stage.map && !stage.attached && !stage.pending;
      if (last_allocated >= 0) good = good && stage_gone(last_allocated);
      fault_mode = 0;
      fill_frame(surface, fault % 3);
      good = good && ordinary_put(surface) && verify_frame(surface, fault % 3);
      eve_x11_shm_stage_finish(&stage, surface->conn);
   }
   const uint32_t invalid[][3] = {
      {0,480,2560}, {65536,480,262144}, {640,65536,2560},
      {640,480,2559}, {640,480,4}, {640,480,UINT32_MAX},
      {640,65535,2560}, {640,480,262144},
   };
   for (size_t i = 0; i < sizeof(invalid)/sizeof(invalid[0]); ++i) {
      struct eve_x11_shm_stage stage;
      memset(&stage, 0, sizeof(stage));
      good = good && !eve_x11_shm_stage_init(&stage, surface->conn,
         invalid[i][0], invalid[i][1], invalid[i][2], SIZE_MAX);
      good = good && !stage.map && !stage.attached;
      eve_x11_shm_stage_finish(&stage, surface->conn);
   }
   struct eve_x11_shm_stage capacity;
   memset(&capacity, 0, sizeof(capacity));
   good = good && !eve_x11_shm_stage_init(&capacity, surface->conn,
      surface->width, surface->height, surface->pitch, surface->capacity - 1);
   eve_x11_shm_stage_finish(&capacity, surface->conn);
   return good;
}

static int fixture_no_extension(struct surface *surface)
{
   struct eve_x11_shm_stage stage;
   int good = !eve_x11_shm_stage_init(&stage, surface->conn, surface->width,
      surface->height, surface->pitch, surface->capacity) && stage.fallback_reported &&
      !stage.map && !stage.attached;
   fill_frame(surface, 1);
   good = good && ordinary_put(surface) && verify_frame(surface, 1);
   eve_x11_shm_stage_finish(&stage, surface->conn);
   return good;
}

static int fixture_server_death(struct surface *surface, pid_t server_pid)
{
   struct eve_x11_shm_stage stage;
   if (!eve_x11_shm_stage_init(&stage, surface->conn, surface->width,
       surface->height, surface->pitch, surface->capacity)) return 0;
   int id = stage.shmid;
   xcb_connection_t *grab = xcb_connect(NULL, NULL);
   if (xcb_connection_has_error(grab)) {
      xcb_disconnect(grab);
      eve_x11_shm_stage_finish(&stage, surface->conn);
      return 0;
   }
   (void)xcb_grab_server(grab);
   xcb_get_input_focus_reply_t *focus = xcb_get_input_focus_reply(
      grab, xcb_get_input_focus(grab), NULL);
   int good = focus != NULL;
   free(focus);
   fill_frame(surface, 0);
   good = good && eve_x11_shm_stage_put(&stage, surface->conn, surface->window,
      surface->gc, surface->depth, surface->source, surface->capacity) == EVE_X11_SHM_OK && stage.pending;
   int killed = kill(server_pid, SIGKILL) == 0;
   if (!killed) (void)check_cookie(grab, xcb_ungrab_server_checked(grab));
   enum eve_x11_shm_result drained = eve_x11_shm_stage_wait(&stage, surface->conn);
   good = good && killed && drained == EVE_X11_SHM_SURFACE_LOST;
   eve_x11_shm_stage_finish(&stage, surface->conn);
   int removed = 0;
   /* The server's mapping is released by the PRoot exit event. Allow a bounded
    * dispatcher delay, and verify actual segment removal rather than flags. */
   for (unsigned i = 0; i < 100 && !removed; ++i) {
      removed = stage_gone(id);
      if (!removed) {
         struct timespec delay = {0, 10000000};
         while (nanosleep(&delay, &delay) && errno == EINTR) { }
      }
   }
   good = good && !stage.map && !stage.pending && !stage.attached && removed;
   xcb_disconnect(grab);
   return good;
}

int main(int argc, char **argv)
{
   uint32_t width = 640, height = 480;
   enum { FRAMES, NEGATIVES, NO_EXTENSION, SERVER_DEATH } mode = FRAMES;
   pid_t server_pid = -1;
   for (int i = 1; i < argc; ++i) {
      if (!strcmp(argv[i], "--fixture")) continue;
      if (!strcmp(argv[i], "--negative-controls")) mode = NEGATIVES;
      else if (!strcmp(argv[i], "--expect-extension-unavailable")) mode = NO_EXTENSION;
      else if (!strcmp(argv[i], "--server-death")) mode = SERVER_DEATH;
      else if (!strcmp(argv[i], "--width") && ++i < argc) width = strtoul(argv[i], NULL, 10);
      else if (!strcmp(argv[i], "--height") && ++i < argc) height = strtoul(argv[i], NULL, 10);
      else if (!strcmp(argv[i], "--server-pid") && ++i < argc) server_pid = strtol(argv[i], NULL, 10);
      else return 2;
   }
   if (width < 128 || height < 128 || width > 1280 || height > 720 ||
       (mode == SERVER_DEATH && server_pid <= 1)) return 2;
   struct surface surface;
   int good = surface_open(&surface, width, height);
   if (good) {
      if (mode == FRAMES) good = fixture_frames(&surface);
      else if (mode == NEGATIVES) good = fixture_negatives(&surface);
      else if (mode == NO_EXTENSION) good = fixture_no_extension(&surface);
      else good = fixture_server_death(&surface, server_pid);
   }
   surface_close(&surface);
   printf("{\"format\":1,\"helper\":\"eve-x11-shm-probe-1\",\"passed\":%s,"
          "\"mode\":\"%s\",\"width\":%u,\"height\":%u,"
          "\"frames\":%u,\"reuseVerified\":%s,\"resizeVerified\":%s,"
          "\"pendingTeardownVerified\":%s,\"delayedReuseVerified\":%s,"
          "\"delayedTeardownVerified\":%s,\"cleanupVerified\":%s}\n",
          good ? "true" : "false", mode == FRAMES ? "fixture" : mode == NEGATIVES ? "negative-controls" :
          mode == NO_EXTENSION ? "extension-unavailable" : "server-death", width, height,
          mode == FRAMES && good ? 3 : 0, mode == FRAMES && good ? "true" : "false",
          mode == FRAMES && good ? "true" : "false", mode == FRAMES && good ? "true" : "false",
          mode == FRAMES && good ? "true" : "false", mode == FRAMES && good ? "true" : "false",
          good ? "true" : "false");
   return good ? 0 : 1;
}

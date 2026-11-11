/*
 * libFuzzer harness for bareiron's serverbound packet handling.
 *
 * The input is the byte stream a client sends over one TCP connection. It is replayed through the
 * same per-client steps as the server's main loop (read length + packet id, look up the connection
 * state, handlePacket, periodic server tick, disconnect on error/EOF). recv()/send() are replaced
 * (link-time --wrap) by an in-memory stream and a sink, so no sockets are involved and nothing can
 * block. The server's globals are reset before every input.
 *
 *   fuzz_session: the stream starts at the handshake (all connection states reachable).
 *   fuzz_play   : (-DPREJOIN) a valid handshake/login/configuration preamble is replayed first, so
 *                 the input is a stream of play-state packets from a freshly joined player.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#include "globals.h"
#include "procedures.h"
#include "tools.h"
#include "varnum.h"

void handlePacket (int client_fd, int length, int packet_id, int state);

#define MAX_PACKETS 64

static const uint8_t *in_buf;
static size_t in_len, in_pos;

ssize_t __wrap_recv (int fd, void *buf, size_t n, int flags) {
  (void)fd;
  size_t avail = in_len - in_pos;
  size_t k = n < avail ? n : avail;
  if (k) memcpy(buf, in_buf + in_pos, k);
  if (!(flags & MSG_PEEK)) in_pos += k;
  return (ssize_t)k; // 0 once the stream is exhausted: the client closed the connection
}

ssize_t __wrap_send (int fd, const void *buf, size_t n, int flags) {
  (void)fd; (void)buf; (void)flags;
  return (ssize_t)n;
}

#ifdef PREJOIN
// Handshake (login intent), Login Start ("fuzz"), Login Acknowledged, Client Information,
// Serverbound Known Packs, Acknowledge Finish Configuration.
static const uint8_t prefix[] = {
  0x10, 0x00, 0x84, 0x06, 0x09, 'l', 'o', 'c', 'a', 'l', 'h', 'o', 's', 't', 0x63, 0xDD, 0x02,
  0x16, 0x00, 0x04, 'f', 'u', 'z', 'z',
        0xA1, 0xB2, 0xC3, 0xD4, 0xE5, 0xF6, 0x07, 0x18, 0x29, 0x3A, 0x4B, 0x5C, 0x6D, 0x7E, 0x8F, 0x90,
  0x01, 0x03,
  0x0F, 0x00, 0x05, 'e', 'n', '_', 'U', 'S', 0x0A, 0x00, 0x01, 0x7F, 0x01, 0x00, 0x01, 0x00,
  0x01, 0x07,
  0x01, 0x03,
};
#else
static const uint8_t prefix[] = { 0 };
#define NO_PREFIX
#endif

static void reset_server_state (void) {
  memset(block_changes, 0, sizeof(block_changes));
  for (int i = 0; i < MAX_BLOCK_CHANGES; i ++) block_changes[i].block = 0xFF;
  block_changes_count = 0;
  memset(player_data, 0, sizeof(player_data));
  for (int i = 0; i < MAX_PLAYERS; i ++) {
    player_data[i].client_fd = -1;
    client_states[i * 2] = -1;
    client_states[i * 2 + 1] = STATE_NONE;
  }
  player_data_count = 0;
  memset(mob_data, 0, sizeof(mob_data));
  memset(recv_buffer, 0, sizeof(recv_buffer));
  recv_count = 0;
  total_bytes_received = 0;
  world_seed = INITIAL_WORLD_SEED;
  rng_seed = INITIAL_RNG_SEED;
  world_seed = splitmix64(world_seed);
  rng_seed = splitmix64(rng_seed);
  world_time = 0;
  server_ticks = 0;
  client_count = 1;
}

int LLVMFuzzerInitialize (int *argc, char ***argv) {
  (void)argc; (void)argv;
  // The server logs every packet to stdout: send that to a small in-memory sink (it fills up and
  // further writes just fail), keeping stderr for sanitizer reports.
  static char sink[4096];
  FILE *quiet = fmemopen(sink, sizeof(sink), "w");
  if (!quiet) return 1;
  stdout = quiet;
  // Block changes are written through to ./world.bin (never read back after startup).
  FILE *f = fopen("world.bin", "wb");
  if (f) {
    static BlockChange blank[MAX_BLOCK_CHANGES];
    fwrite(blank, 1, sizeof(blank), f);
    fwrite(player_data, 1, sizeof(player_data), f);
    fclose(f);
  }
  return 0;
}

int LLVMFuzzerTestOneInput (const uint8_t *data, size_t size) {
  size_t total = sizeof(prefix) * (sizeof(prefix) > 1) + size;
  uint8_t *stream = malloc(total ? total : 1);
  if (!stream) return 0;
  size_t off = 0;
  #ifndef NO_PREFIX
  memcpy(stream, prefix, sizeof(prefix));
  off = sizeof(prefix);
  #endif
  if (size) memcpy(stream + off, data, size);
  in_buf = stream; in_len = total; in_pos = 0;

  reset_server_state();
  int client_fd = memfd_create("client", 0);
  if (client_fd < 0) { free(stream); return 0; }

  for (int packets = 0; packets < MAX_PACKETS; packets ++) {
    if (recv(client_fd, &recv_buffer, 2, MSG_PEEK) < 2) break;

    int length = readVarInt(client_fd);
    if (length == (int)VARNUM_ERROR) break;
    int packet_id = readVarInt(client_fd);
    if (packet_id == (int)VARNUM_ERROR) break;

    int state = getClientState(client_fd);
    if (state == STATE_NONE && length == 254 && packet_id == 122) break;

    handlePacket(client_fd, length - sizeVarInt(packet_id), packet_id, state);
    if (recv_count == 0 || recv_count == -1) break;

    if (packets % 2 == 1) handleServerTick(TIME_BETWEEN_TICKS);
  }

  // A handler may already have disconnected (and closed) the client.
  if (fcntl(client_fd, F_GETFD) != -1) disconnectClient(&client_fd, 0);
  in_buf = NULL;
  free(stream);
  return 0;
}

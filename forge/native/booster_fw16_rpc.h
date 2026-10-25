#ifndef FORGE_BOOSTER_FW16_RPC_H
#define FORGE_BOOSTER_FW16_RPC_H

#include <stddef.h>
#include <stdint.h>

// Explicit versioned optional TLVs; no change to original motor/crank domain.
enum {
  FORGE_FW16_RPC_REQUEST = 0x46470001u,
  FORGE_FW16_RPC_REPLY = 0x46478001u,
  FORGE_FW16_RPC_VERSION = 1,
  FORGE_FW16_RPC_BODY_BYTES = 512,
};
struct ForgeFw16Rpc {
  uint32_t version;       // 0
  uint32_t body_length;   // 4, UTF8 JSON byte count, no trailing NUL required
  uint64_t sequence;      // 8, positive and strictly increasing
  int64_t api_id;         // 16, audited original LocoApiId
  int64_t status;         // 24, request must be0; reply original RPC status
  char body[FORGE_FW16_RPC_BODY_BYTES]; // 32
};
static_assert(sizeof(ForgeFw16Rpc) == 544, "RPC extension ABI");

// Call sensor after the original RsSdkOutput Update, before the remaining graph.
// Call actuator after copying original RsSdkInput output into the reply packet.
// Return0 normally, -1 on protocol/internal error (caller must fail closed).
// Original RPC refusal is returned in the reply TLV, not changed into success.
extern "C" int forge_fw16_rpc_sensor(const uint8_t* payload, size_t bytes, uint64_t tick);
extern "C" int forge_fw16_rpc_actuator(uint8_t* payload, size_t bytes);

#endif

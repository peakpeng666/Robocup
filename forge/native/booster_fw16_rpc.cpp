// Local simulator command ingress through the ORIGINAL firmware RPC handler.
// Uses official SDK Request/Response C++ definitions, statically matched to
// 1.6.0.10 DWARF. No direct writes to private controller/mode state.
#include "booster_fw16_rpc.h"
#include "booster_fw16_visual_kick.h"
#include <booster/robot/rpc/request.hpp>
#include <booster/robot/rpc/response.hpp>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <initializer_list>
#include <stdexcept>
#include <string>

namespace {
using Request = booster::robot::Request;
using Response = booster::robot::Response;
using Json = nlohmann::json;
static_assert(sizeof(Request) == 48, "firmware Request DWARF");
static_assert(sizeof(booster::robot::RequestHeader) == 16, "firmware RequestHeader DWARF");
static_assert(sizeof(Response) == 40, "firmware Response DWARF");
using Init = void (*)(void*, const void*, const void*);
using Handler = Response (*)(void*, const Request&);
constexpr const char* initSymbol = "_ZN6module3rsm19BoosterApiRpcServer4InitERKSt10shared_ptrINS0_11ModeManagerEERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE";
constexpr const char* handleSymbol = "_ZN6module3rsm19BoosterApiRpcServer13HandleRequestERKN7booster5robot7RequestE";
void* rpcServer = nullptr;
Handler handler = nullptr;
bool pending = false;
uint64_t lastSequence = 0;
ForgeFw16Rpc reply{};
void* nativeLibrary = nullptr;
#ifdef FORGE_FW16_APPLICATION_API
void* messageServer = nullptr;
#endif

void* original(const char* name) {
  // The original scheduler loads librsm_modules with RTLD_LOCAL. Its symbols
  // are not in this preloaded shim's RTLD_NEXT scope. Take an explicit handle
  // to the ALREADY loaded module; never load a hardware component as recovery.
  const char* library = std::getenv("FORGE_BOOSTER_RPC_LIBRARY");
  if(library && *library && !nativeLibrary) {
    nativeLibrary = dlopen(library, RTLD_NOW | RTLD_NOLOAD);
    if(!nativeLibrary)
      throw std::runtime_error(std::string("RPC library not already loaded: ") + library);
  }
  void* result = dlsym(nativeLibrary ? nativeLibrary : RTLD_NEXT, name);
  if(!result) throw std::runtime_error(name);
  return result;
}
uint32_t read32(const void* address) {
  uint32_t result;
  std::memcpy(&result, address, sizeof(result));
  return result;
}
void keys(const Json& json, std::initializer_list<const char*> expected) {
  if(!json.is_object() || json.size() != expected.size())
    throw std::runtime_error("unexpected command object fields");
  for(const char* key : expected)
    if(!json.contains(key)) throw std::runtime_error("missing command field");
}
void number(const Json& json, const char* key) {
  if(!json.at(key).is_number() || !std::isfinite(json.at(key).get<double>()))
    throw std::runtime_error("nonfinite/non-numeric command field");
}
void mode(const Json& json) {
  keys(json, {"mode"});
  if(!json.at("mode").is_number_integer()) throw std::runtime_error("mode must be integer");
  const int value = json.at("mode").get<int>();
  if(value != 0 && value != 1 && value != 2 && value != 4)
    throw std::runtime_error("unsupported simulation mode");
}
void validate(const ForgeFw16Rpc& request, const std::string& body) {
  if(request.version != FORGE_FW16_RPC_VERSION || request.status ||
     request.sequence == 0 || request.sequence <= lastSequence)
    throw std::runtime_error("RPC version/reserved/sequence mismatch");
#ifdef FORGE_FW16_APPLICATION_API
  // Explicit, separately built application transport. Keep SDK JSON bytes
  // unchanged and let the original HandleRequest validate its own parameters.
  // This range is the public LocoApiId enum, including its three unused gaps.
  if(request.api_id < 2000 || request.api_id > 2042 || request.api_id == 2002 ||
     request.api_id == 2003 || request.api_id == 2014)
    throw std::runtime_error("API is not in the pinned public SDK LocoApiId enum");
  if(!body.empty()) (void)Json::parse(body);
  return;
#endif
  switch(request.api_id) {
    case 2008: // GetUp
    case 2017: // GetMode
    case 2018: // GetStatus
    case 2024: // Shoot
      if(!body.empty()) throw std::runtime_error("argumentless API requires empty body");
      return;
    case 2000: // ChangeMode
    case 2001: // Move
    case 2004: // RotateHead
    case 2025: // GetUpWithMode
    case 2038: // VisualKick
    case 2042: // SwitchGait
      break;
    default:
      throw std::runtime_error("API not in audited simulation allowlist");
  }
  const Json json = Json::parse(body);
  switch(request.api_id) {
    case 2000: case 2025: mode(json); break;
    case 2001:
      keys(json, {"vx", "vy", "vyaw"});
      for(const char* key : {"vx", "vy", "vyaw"}) number(json, key);
      break;
    case 2004:
      keys(json, {"pitch", "yaw"}); number(json, "pitch"); number(json, "yaw");
      break;
    case 2038:
      keys(json, {"start", "version"});
      if(!json.at("start").is_boolean() || !json.at("version").is_number_integer() ||
         (json.at("version") != 0 && json.at("version") != 1))
        throw std::runtime_error("invalid VisualKick version/start");
      break;
    case 2042:
      keys(json, {"gait_type"});
      if(!json.at("gait_type").is_number_integer() ||
         json.at("gait_type").get<int>() < 0 || json.at("gait_type").get<int>() > 2)
        throw std::runtime_error("invalid original gait type");
      break;
  }
}
} // namespace

#ifdef FORGE_FW16_APPLICATION_API
extern "C" void forgeMessageInit(void*, const void*) __asm__(
    "_ZN6module3rsm19BoosterApiMsgServer4InitERKSt10shared_ptrINS0_11ModeManagerEE");
extern "C" void forgeMessageInit(void* self, const void* manager) {
  try {
    const char* symbol = "_ZN6module3rsm19BoosterApiMsgServer4InitERKSt10shared_ptrINS0_11ModeManagerEE";
    reinterpret_cast<void (*)(void*, const void*)>(original(symbol))(self, manager);
    if(messageServer && messageServer != self) throw std::runtime_error("multiple original message servers");
    messageServer = self;
    std::fprintf(stderr, "FORGE_FW16_VISUAL_KICK_READY original_message_handler=1\n");
  } catch(const std::exception& error) {
    std::fprintf(stderr, "FORGE_FW16_MESSAGE_INIT_ERROR: %s\n", error.what()); std::_Exit(72);
  }
}

static void visualKick(const uint8_t* bytes, uint64_t tick) {
  ForgeFw16VisualKick input{}; std::memcpy(&input, bytes, sizeof(input));
  if(!messageServer || input.version != 1 || input.sequence != tick + 1 ||
     input.nanosec >= 1000000000u || input.frame_length > sizeof(input.frame_id))
    throw std::runtime_error("invalid original visual kick envelope or missing Init");
  for(double value : input.values) if(!std::isfinite(value)) throw std::runtime_error("nonfinite visual kick input");
  // Allocate, populate, dispatch, and destroy using the original generated IDL
  // functions. No guessed object layout or private controller state writes.
  // This generated IDL class also inherits TopicDataType. createData/deleteData
  // are member functions: AArch64 x0 is this, x1 is deleteData's data argument.
  // The pinned createData body ignores this and allocates/constructs a new Kick.
  void* message = reinterpret_cast<void* (*)(void*)>(original("_ZN5brain3msg4Kick10createDataEv"))(nullptr);
  if(!message) throw std::runtime_error("original Kick allocation failed");
  const auto destroy = reinterpret_cast<void (*)(void*, void*)>(original("_ZN5brain3msg4Kick10deleteDataEPv"));
  try {
    void* header = reinterpret_cast<void* (*)(void*)>(original("_ZN5brain3msg4Kick6headerEv"))(message);
    void* stamp = reinterpret_cast<void* (*)(void*)>(original("_ZN8std_msgs3msg6Header5stampEv"))(header);
    reinterpret_cast<void (*)(void*, int32_t)>(original("_ZN18builtin_interfaces3msg4Time3secEi"))(stamp, input.sec);
    reinterpret_cast<void (*)(void*, uint32_t)>(original("_ZN18builtin_interfaces3msg4Time7nanosecEj"))(stamp, input.nanosec);
    const std::string frame(input.frame_id, input.frame_length);
    reinterpret_cast<void (*)(void*, const std::string&)>(original("_ZN8std_msgs3msg6Header8frame_idERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE"))(header, frame);
    const char* fields[] = {"_ZN5brain3msg4Kick1xEd", "_ZN5brain3msg4Kick1yEd", "_ZN5brain3msg4Kick3dirEd",
      "_ZN5brain3msg4Kick6goal_xEd", "_ZN5brain3msg4Kick6goal_yEd", "_ZN5brain3msg4Kick20robot_theta_to_fieldEd", "_ZN5brain3msg4Kick5powerEd"};
    for(unsigned i = 0; i < 7; ++i) reinterpret_cast<void (*)(void*, double)>(original(fields[i]))(message, input.values[i]);
    reinterpret_cast<void (*)(void*, const void*)>(original("_ZN6module3rsm19BoosterApiMsgServer20VisualKickMsgHandlerEPKv"))(messageServer, message);
    std::fprintf(stderr, "FORGE_FW16_VISUAL_KICK tick=%llu original_handler=1\n", static_cast<unsigned long long>(tick));
  } catch(...) { destroy(message, message); throw; }
  destroy(message, message);
}
#endif

extern "C" void forgeRpcInit(void*, const void*, const void*) __asm__(
    "_ZN6module3rsm19BoosterApiRpcServer4InitERKSt10shared_ptrINS0_11ModeManagerEERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE");
extern "C" void forgeRpcInit(void* self, const void* manager, const void* address) {
  try {
    if(rpcServer && rpcServer != self) throw std::runtime_error("multiple native RPC servers in one robot process");
    reinterpret_cast<Init>(original(initSymbol))(self, manager, address);
    handler = reinterpret_cast<Handler>(original(handleSymbol));
    rpcServer = self;
    std::fprintf(stderr, "FORGE_FW16_RPC_READY original_handle_request=1\n");
  } catch(const std::exception& error) {
    std::fprintf(stderr, "FORGE_FW16_RPC_INIT_ERROR: %s\n", error.what());
    std::_Exit(71);
  }
}

extern "C" int forge_fw16_rpc_sensor(const uint8_t* payload, size_t bytes, uint64_t tick) {
  try {
    if(bytes != 4000 || pending) throw std::runtime_error("RPC payload/pending reply mismatch");
    const uint32_t length = read32(payload);
    if(length < 8 || length > bytes) throw std::runtime_error("invalid RPC TLV envelope");
    const uint8_t* command = nullptr;
    const uint8_t* kick = nullptr;
    for(uint32_t at = 8; at < length;) {
      if(length - at < 8) throw std::runtime_error("truncated RPC TLV header");
      const uint32_t key = read32(payload + at), size = read32(payload + at + 4);
      if(size > length - at - 8) throw std::runtime_error("truncated RPC TLV value");
      if(key == FORGE_FW16_RPC_REQUEST) {
        if(command || size != sizeof(ForgeFw16Rpc)) throw std::runtime_error("duplicate/wrong-sized RPC TLV");
        command = payload + at + 8;
      }
      if(key == FORGE_FW16_VISUAL_KICK) {
        if(kick || size != sizeof(ForgeFw16VisualKick)) throw std::runtime_error("duplicate/wrong-sized visual kick TLV");
        kick = payload + at + 8;
      }
      at += 8 + size;
    }
    if(kick) {
#ifdef FORGE_FW16_APPLICATION_API
      visualKick(kick, tick);
#else
      throw std::runtime_error("visual kick payload requires application API build");
#endif
    }
    if(!command) return 0;
    ForgeFw16Rpc request;
    std::memcpy(&request, command, sizeof(request));
    if(request.body_length > sizeof(request.body)) throw std::runtime_error("RPC body exceeds512B");
    const std::string body(request.body, request.body_length);
    validate(request, body);
    if(!rpcServer || !handler) throw std::runtime_error("original RPC server Init not captured");
    booster::robot::RequestHeader header(request.api_id);
    header.SetExpectResponse(true);
    const Response result = handler(rpcServer, Request(header, body));
    const std::string responseBody = result.GetBody();
    if(responseBody.size() > sizeof(reply.body)) throw std::runtime_error("original RPC reply exceeds512B");
    reply = {};
    reply.version = FORGE_FW16_RPC_VERSION;
    reply.body_length = responseBody.size();
    reply.sequence = request.sequence;
    reply.api_id = request.api_id;
    reply.status = result.GetHeader().GetStatus();
    std::memcpy(reply.body, responseBody.data(), responseBody.size());
    pending = true;
    lastSequence = request.sequence;
    std::fprintf(stderr, "FORGE_FW16_RPC tick=%llu sequence=%llu api=%lld status=%lld\n",
        static_cast<unsigned long long>(tick), static_cast<unsigned long long>(reply.sequence),
        static_cast<long long>(reply.api_id), static_cast<long long>(reply.status));
    return 0;
  } catch(const std::exception& error) {
    std::fprintf(stderr, "FORGE_FW16_RPC_ERROR tick=%llu: %s\n",
        static_cast<unsigned long long>(tick), error.what());
    return -1;
  }
}

extern "C" int forge_fw16_rpc_actuator(uint8_t* payload, size_t bytes) {
  if(!pending) return 0;
  const uint32_t length = read32(payload), size = sizeof(reply), key = FORGE_FW16_RPC_REPLY;
  if(bytes != 4000 || length < 8 || length > bytes || bytes - length < sizeof(reply) + 8) return -1;
  std::memcpy(payload + length, &key, 4);
  std::memcpy(payload + length + 4, &size, 4);
  std::memcpy(payload + length + 8, &reply, sizeof(reply));
  const uint32_t total = length + 8 + sizeof(reply);
  std::memcpy(payload, &total, 4);
  pending = false;
  return 0;
}

#pragma once
#include <nlohmann/json.hpp>
#include <sys/socket.h>
#include <unistd.h>
#include <cerrno>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace OfficialApplication
{
using Json = nlohmann::json;
struct Packet { Json data; std::vector<uint8_t> pixels; };
inline void transfer(int fd, void* address, size_t length, bool sending)
{
  auto* p = static_cast<uint8_t*>(address);
  while(length)
  {
    const auto n = sending ? ::send(fd, p, length, MSG_NOSIGNAL) : ::recv(fd, p, length, 0);
    if(n < 0 && errno == EINTR) continue;
    if(n <= 0) throw std::runtime_error("official application socket closed or timed out");
    p += n; length -= static_cast<size_t>(n);
  }
}
inline void send(int fd, const Json& data, const std::vector<uint8_t>& pixels = {})
{
  std::string text = data.dump(-1, ' ', false, Json::error_handler_t::strict);
  if(text.size() > 1048576 || pixels.size() > 16777216) throw std::runtime_error("application frame too large");
  uint32_t sizes[3] = {0x41504746u, static_cast<uint32_t>(text.size()), static_cast<uint32_t>(pixels.size())};
  transfer(fd, sizes, sizeof(sizes), true);
  transfer(fd, text.data(), text.size(), true);
  if(!pixels.empty()) transfer(fd, const_cast<uint8_t*>(pixels.data()), pixels.size(), true);
}
inline Packet receive(int fd)
{
  uint32_t sizes[3]; transfer(fd, sizes, sizeof(sizes), false);
  if(sizes[0] != 0x41504746u || !sizes[1] || sizes[1] > 1048576 || sizes[2] > 16777216)
    throw std::runtime_error("invalid application frame envelope");
  std::string text(sizes[1], '\0'); transfer(fd, text.data(), text.size(), false);
  Packet packet{Json::parse(text), std::vector<uint8_t>(sizes[2])};
  if(sizes[2]) transfer(fd, packet.pixels.data(), sizes[2], false);
  return packet;
}
}

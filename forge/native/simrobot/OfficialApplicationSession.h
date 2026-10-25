#pragma once
#include "OfficialApplicationWire.h"
#include "OfficialPortContract.h"
#include <sys/un.h>
#include <algorithm>
#include <cstdio>
#include <cstring>

namespace OfficialApplication
{
class Session
{
  int fd = -1;
  uint64_t step = 0;
  bool stopped = false;
  std::string robot;
  static std::vector<Session*>& all() { static auto* value = new std::vector<Session*>; return *value; }
  static void stopAll() { for(auto* value : all()) value->stopNoThrow(); }
public:
  Session(const std::string& path, const std::string& robot) : robot(robot)
  {
    if(path.size() >= sizeof(sockaddr_un::sun_path)) throw std::runtime_error("application socket path too long");
    fd = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    sockaddr_un address{}; address.sun_family = AF_UNIX; std::strcpy(address.sun_path, path.c_str());
    if(fd < 0 || ::connect(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)))
      throw std::runtime_error("official application not listening for " + robot);
    ucred peer{}; socklen_t length = sizeof(peer);
    if(::getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &length) || peer.uid != ::getuid())
      throw std::runtime_error("official application peer is not this user's local process");
    timeval timeout{60, 0};
    ::setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    ::setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    send(fd, {{"version",1},{"kind","hello"},{"contract",portContract()}});
    const auto hello = receive(fd);
    if(!hello.pixels.empty() || hello.data.at("kind") != "ready")
      throw std::runtime_error("application contract handshake not acknowledged");
    requirePortContract(hello.data.at("contract"));
    all().push_back(this);
    static const bool registered = [] { std::atexit(stopAll); return true; }(); (void)registered;
    std::fprintf(stderr, "AUDIT official_application_connected robot=%s peer_pid=%d\n", robot.c_str(), peer.pid);
  }
  ~Session()
  {
    stopNoThrow(); all().erase(std::remove(all().begin(), all().end(), this), all().end());
    if(fd >= 0) ::close(fd);
  }
  Json exchange(const Json& input, const std::vector<uint8_t>& pixels)
  {
    if(stopped || input.at("step").get<uint64_t>() != step + 1) throw std::runtime_error("application exchange sequence mismatch");
    send(fd, input, pixels); auto reply = receive(fd);
    if(!reply.pixels.empty() || reply.data.at("version") != 1 || reply.data.at("kind") != "commands" || reply.data.at("step") != input.at("step"))
      throw std::runtime_error("official application response identity mismatch");
    ++step; return reply.data;
  }
  void stopNoThrow()
  {
    if(stopped || fd < 0) return;
    stopped = true;
    try {
      send(fd, {{"version", 1}, {"kind", "stop"}}); const auto reply = receive(fd);
      if(reply.data.at("kind") != "stopped" || reply.data.at("step") != step)
        throw std::runtime_error("application STOP not acknowledged");
      std::fprintf(stderr, "AUDIT official_application_stopped robot=%s steps=%llu\n", robot.c_str(), static_cast<unsigned long long>(step));
    } catch(const std::exception& error) { std::fprintf(stderr, "OFFICIAL_APPLICATION_STOP_ERROR robot=%s reason=%s\n", robot.c_str(), error.what()); }
  }
};
}

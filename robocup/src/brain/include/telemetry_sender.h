#pragma once

#include <atomic>
#include <netinet/in.h>
#include <string>
#include <thread>

class Brain;

class TelemetrySender
{
public:
    explicit TelemetrySender(Brain *brain);
    ~TelemetrySender();

    void start();
    void stop();

private:
    std::string buildPacket() const;
    void loop();

    Brain *brain_;
    std::atomic<bool> running_{false};
    std::thread thread_;
    int socket_fd_{-1};
    sockaddr_in dest_addr_{};
    std::string host_;
    int port_{15000};
    double rate_hz_{1.0};
    int max_obstacles_{40};
    int obstacle_threshold_{0};
    double obstacle_memory_ms_{500.0};
};

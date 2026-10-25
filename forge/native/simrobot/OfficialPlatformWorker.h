#pragma once
#include <condition_variable>
#include <exception>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <thread>

namespace OfficialApplication
{
// One persistent worker per robot. Only independent socket IO runs here.
// Physics reads, rendering, actuator writes, and referee access stay on the
// simulator thread. wait() is the mandatory barrier before the next step.
class PlatformWorker
{
  std::mutex mutex;
  std::condition_variable changed;
  std::function<void()> pending;
  std::exception_ptr failure;
  bool busy = false, closing = false;
  std::thread thread;
public:
  PlatformWorker() : thread([this] {
    std::unique_lock lock(mutex);
    for(;;)
    {
      changed.wait(lock, [this] { return closing || static_cast<bool>(pending); });
      if(closing) return;
      auto task = std::move(pending);
      lock.unlock();
      std::exception_ptr error;
      try { task(); } catch(...) { error = std::current_exception(); }
      lock.lock(); failure = error; busy = false; changed.notify_all();
    }
  }) {}
  ~PlatformWorker()
  {
    { std::unique_lock lock(mutex); changed.wait(lock, [this] { return !busy; }); closing = true; }
    changed.notify_all(); thread.join();
  }
  void begin(std::function<void()> task)
  {
    std::lock_guard lock(mutex);
    if(busy || closing || failure) throw std::runtime_error("official worker reused before successful barrier");
    pending = std::move(task); busy = true; changed.notify_all();
  }
  void wait()
  {
    std::unique_lock lock(mutex);
    changed.wait(lock, [this] { return !busy; });
    if(failure) std::rethrow_exception(failure);
  }
};
}

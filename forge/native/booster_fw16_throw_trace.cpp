// Opt-in diagnostic preload only. Preserve the original exception and handler.
#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>
#include <execinfo.h>
#include <pthread.h>
#include <cstring>
#include <typeinfo>
#include <unistd.h>

static void locate(const char* label, void* address)
{
  Dl_info location{};
  if(dladdr(address, &location) && location.dli_fbase)
    std::fprintf(stderr, "FORGE_NATIVE_ADDRESS label=%s address=%p module=%s offset=0x%lx symbol=%s\n",
      label, address, location.dli_fname ? location.dli_fname : "?",
      reinterpret_cast<unsigned long>(address) - reinterpret_cast<unsigned long>(location.dli_fbase),
      location.dli_sname ? location.dli_sname : "?");
  else
    std::fprintf(stderr, "FORGE_NATIVE_ADDRESS label=%s address=%p module=anonymous\n", label, address);
}

extern "C" int pthread_mutex_lock(pthread_mutex_t* mutex)
{
  using Lock = int (*)(pthread_mutex_t*);
  static Lock original = reinterpret_cast<Lock>(dlsym(RTLD_NEXT, "pthread_mutex_lock"));
  if(!original) _exit(74);
  const int result = original(mutex);
  if(result)
  {
    unsigned words[sizeof(pthread_mutex_t) / sizeof(unsigned)];
    std::memcpy(words, mutex, sizeof(words));
    std::fprintf(stderr, "FORGE_NATIVE_MUTEX_ERROR result=%d mutex=%p words=", result, static_cast<void*>(mutex));
    for(unsigned value : words) std::fprintf(stderr, "%08x,", value);
    std::fprintf(stderr, "\n");
    locate("mutex", mutex);
    locate("lock-caller", __builtin_return_address(0));
    std::fflush(stderr);
  }
  return result;
}

#ifndef FORGE_TRACE_NO_WORKER
extern "C" void trace_worker(void* self) asm("_ZN5utils11thread_pool17LastingThreadFuncclEv");
extern "C" void trace_worker(void* self)
{
  using Worker = void (*)(void*);
  static void* library = dlopen("/vendor/lib/motion/libutils_thread_pool.so", RTLD_NOW | RTLD_NOLOAD);
  static Worker original = library ? reinterpret_cast<Worker>(dlsym(library, "_ZN5utils11thread_pool17LastingThreadFuncclEv")) : nullptr;
  if(!original) _exit(74);
  void* references[4];
  std::memcpy(references, self, sizeof(references));
  std::fprintf(stderr, "FORGE_NATIVE_WORKER self=%p stop=%p condition=%p mutex=%p queue=%p\n", self,
    references[0], references[1], references[2], references[3]);
  locate("worker-mutex", references[2]);
  std::fflush(stderr);
  original(self);
}
#endif

extern "C" [[noreturn]] void __cxa_throw(void* object, std::type_info* type, void (*destroy)(void*))
{
  using Throw = void (*)(void*, std::type_info*, void (*)(void*));
  static Throw original = reinterpret_cast<Throw>(dlsym(RTLD_NEXT, "__cxa_throw"));
  std::fprintf(stderr, "FORGE_NATIVE_EXCEPTION type=%s\n", type ? type->name() : "null");
  void* frames[40];
  const int count = backtrace(frames, 40);
  for(int i = 0; i < count; ++i)
  {
    Dl_info location{};
    if(dladdr(frames[i], &location) && location.dli_fbase)
      std::fprintf(stderr, "FORGE_NATIVE_BACKTRACE frame=%d module=%s offset=0x%lx symbol=%s\n", i,
        location.dli_fname ? location.dli_fname : "?",
        reinterpret_cast<unsigned long>(frames[i]) - reinterpret_cast<unsigned long>(location.dli_fbase),
        location.dli_sname ? location.dli_sname : "?");
  }
  std::fflush(stderr);
  if(!original) _exit(74);
  original(object, type, destroy);
  __builtin_unreachable();
}

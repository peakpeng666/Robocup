#pragma once
#include <atomic>
#include <chrono>
#include <cstdio>
struct BenchBucket {const char* name;std::atomic<unsigned long long> calls{0},ns{0}; explicit BenchBucket(const char*n):name(n){} ~BenchBucket(){fprintf(stderr,"PERF_STAGE name=%s calls=%llu wall_ns=%llu\n",name,calls.load(),ns.load());}};
struct BenchScope {BenchBucket& b;std::chrono::steady_clock::time_point begin;explicit BenchScope(BenchBucket& x):b(x),begin(std::chrono::steady_clock::now()){}~BenchScope(){b.ns.fetch_add(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-begin).count(),std::memory_order_relaxed);b.calls.fetch_add(1,std::memory_order_relaxed);}};
#define BENCH_SCOPE(name) static BenchBucket _benchBucket(name);BenchScope _benchScope(_benchBucket)

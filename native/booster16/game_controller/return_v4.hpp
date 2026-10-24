#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cmath>
#include <stdexcept>
#include <limits>
namespace booster16::game_controller {
struct ReturnV4 {
  std::uint8_t player=0,team=0,fallen=0;
  std::array<float,3> pose_mm_rad{};
  float ball_age_s=-1;
  std::array<float,2> ball_mm{};
};
inline void validateReturn(const ReturnV4& p,std::uint8_t team,std::uint8_t maxPlayer) {
  if(!team || !maxPlayer || maxPlayer>20 || p.team!=team || !p.player || p.player>maxPlayer || p.fallen>1)
    throw std::invalid_argument("invalid return identity or fallen flag");
  for(float v:p.pose_mm_rad)if(!std::isfinite(v))throw std::invalid_argument("nonfinite return pose");
  for(float v:p.ball_mm)if(!std::isfinite(v))throw std::invalid_argument("nonfinite return ball");
  if(!std::isfinite(p.ball_age_s) || (p.ball_age_s<0 && p.ball_age_s!=-1))
    throw std::invalid_argument("invalid ball age");
}
inline ReturnV4 decodeReturnV4(const std::uint8_t* data,std::size_t size,std::uint8_t team,std::uint8_t maxPlayer) {
  static_assert(sizeof(float)==4 && std::numeric_limits<float>::is_iec559,"requires IEEE754 float32");
  if(!data || size!=32 || std::memcmp(data,"RGrt",4) || data[4]!=4)
    throw std::invalid_argument("invalid return header/version/length");
  ReturnV4 out;out.player=data[5];out.team=data[6];out.fallen=data[7];
  auto get=[&](std::size_t pos){std::uint32_t bits=0;for(unsigned i=0;i<4;++i)bits|=std::uint32_t(data[pos+i])<<(8*i);float v;std::memcpy(&v,&bits,4);return v;};
  for(unsigned i=0;i<3;++i)out.pose_mm_rad[i]=get(8+4*i);
  out.ball_age_s=get(20);for(unsigned i=0;i<2;++i)out.ball_mm[i]=get(24+4*i);
  validateReturn(out,team,maxPlayer);return out;
}
inline std::array<std::uint8_t,32> encodeReturnV4(const ReturnV4& p,std::uint8_t team,std::uint8_t maxPlayer) {
  validateReturn(p,team,maxPlayer);
  std::array<std::uint8_t,32> out{};std::memcpy(out.data(),"RGrt",4);
  out[4]=4;out[5]=p.player;out[6]=p.team;out[7]=p.fallen;
  auto put=[&](std::size_t pos,float v){std::uint32_t bits;std::memcpy(&bits,&v,4);for(unsigned i=0;i<4;++i)out[pos+i]=(bits>>(8*i))&255;};
  for(unsigned i=0;i<3;++i)put(8+4*i,p.pose_mm_rad[i]);
  put(20,p.ball_age_s);for(unsigned i=0;i<2;++i)put(24+4*i,p.ball_mm[i]);return out;
}
} // namespace booster16::game_controller

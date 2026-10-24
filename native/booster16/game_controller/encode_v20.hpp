#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <stdexcept>

namespace booster16::game_controller {
template<class T> auto fieldColour(const T& t, int) -> decltype(t.fieldPlayerColour) { return t.fieldPlayerColour; }
template<class T> auto fieldColour(const T& t, long) -> decltype(t.fieldPlayerColor) { return t.fieldPlayerColor; }
template<class T> auto keeperColour(const T& t, int) -> decltype(t.goalkeeperColour) { return t.goalkeeperColour; }
template<class T> auto keeperColour(const T& t, long) -> decltype(t.goalkeeperColor) { return t.goalkeeperColor; }
// Explicit little-endian wire serialization. Source is the BHuman RoboCup base
// packet, not its derived GameControllerData timestamp/true-data metadata.
// No socket, timer, referee mutation, or version/penalty normalization occurs here.
template<class Packet>
std::array<std::uint8_t, 158> encodeV20(const Packet& p) {
  if(p.version != 20 || p.playersPerTeam == 0 || p.playersPerTeam > 20 ||
     p.state > 4 || p.setPlay > 6 || p.stopped > 1 || p.firstHalf > 1 ||
     p.gamePhase > 3 || p.competitionType > 2 ||
     p.teams[0].teamNumber == p.teams[1].teamNumber)
    throw std::invalid_argument("invalid v20 referee packet");
  if(p.kickingTeam != 255 && p.kickingTeam != p.teams[0].teamNumber &&
     p.kickingTeam != p.teams[1].teamNumber)
    throw std::invalid_argument("kicking team is not in this match");
  std::array<std::uint8_t, 158> out{};
  std::size_t n=0;
  auto byte=[&](std::uint8_t v){out.at(n++)=v;};
  auto word=[&](std::uint16_t v){byte(v & 255);byte(v >> 8);};
  for(char c : {'R','G','m','e'}) byte(c);
  byte(20);byte(p.packetNumber);byte(p.playersPerTeam);byte(p.competitionType);
  byte(p.stopped);byte(p.gamePhase);byte(p.state);byte(p.setPlay);
  byte(p.firstHalf);byte(p.kickingTeam);word(p.secsRemaining);word(p.secondaryTime);
  for(const auto& t:p.teams) {
    if(t.goalkeeper > 20 || fieldColour(t,0) > 9 || keeperColour(t,0) > 9)
      throw std::invalid_argument("invalid team metadata");
    byte(t.teamNumber);byte(fieldColour(t,0));byte(keeperColour(t,0));
    byte(t.goalkeeper);byte(t.score);byte(t.penaltyShot);word(t.singleShots);word(t.messageBudget);
    for(const auto& r:t.players) {
      if(r.penalty > 13) throw std::invalid_argument("unknown v20 penalty");
      byte(r.penalty);byte(r.secsTillUnpenalised);byte(r.cautions);
    }
  }
  if(n != out.size()) throw std::invalid_argument("incorrect player array length");
  return out;
}
} // namespace booster16::game_controller

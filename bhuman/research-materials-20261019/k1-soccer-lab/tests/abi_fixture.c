#include <stdio.h>
#include <string.h>
#include "RoboCupGameControlData.h"

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  if (!strcmp(argv[1], "sizes")) {
    printf("%zu %zu %zu %zu\n", sizeof(struct RoboCupGameControlData),
           sizeof(struct RoboCupGameControlReturnData), sizeof(struct TeamInfo), sizeof(struct RobotInfo));
    return 0;
  }
  if (!strcmp(argv[1], "control")) {
    struct RoboCupGameControlData d = {0};
    memcpy(d.header, GAMECONTROLLER_STRUCT_HEADER, 4);
    d.version = GAMECONTROLLER_STRUCT_VERSION;
    d.packetNumber = 251; d.playersPerTeam = 3;
    d.competitionType = COMPETITION_TYPE_MIDDLE; d.stopped = 1;
    d.gamePhase = GAME_PHASE_NORMAL; d.state = STATE_PLAYING;
    d.setPlay = SET_PLAY_INDIRECT_FREE_KICK; d.firstHalf = 1;
    d.kickingTeam = 42; d.secsRemaining = -5; d.secondaryTime = 17;
    d.teams[0].teamNumber = 42; d.teams[0].fieldPlayerColour = TEAM_BLUE;
    d.teams[0].goalkeeperColour = TEAM_GREEN; d.teams[0].goalkeeper = 3;
    d.teams[0].messageBudget = 4321; d.teams[0].players[1].penalty = PENALTY_PUSHING;
    d.teams[0].players[1].secsTillUnpenalised = 12; d.teams[0].players[1].cautions = 1;
    d.teams[1].teamNumber = 43; d.teams[1].messageBudget = 1234;
    fwrite(&d, sizeof(d), 1, stdout); return 0;
  }
  if (!strcmp(argv[1], "status")) {
    struct RoboCupGameControlReturnData d = {0};
    memcpy(d.header, GAMECONTROLLER_RETURN_STRUCT_HEADER, 4);
    d.version = GAMECONTROLLER_RETURN_STRUCT_VERSION; d.playerNum = 2;
    d.teamNum = 42; d.fallen = 0;
    d.pose[0] = 1500.25f; d.pose[1] = -220.5f; d.pose[2] = 0.75f;
    d.ballAge = 0.125f; d.ball[0] = 450.5f; d.ball[1] = -13.25f;
    fwrite(&d, sizeof(d), 1, stdout); return 0;
  }
  return 2;
}

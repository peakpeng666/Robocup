// Explicit native-controller request and feedback. Disabled in official teams.
#pragma once
#include "Streaming/AutoStreamable.h"

STREAMABLE(NativeMotionCommand,
{,
  (bool)(false) enabled,
  (unsigned)(0) sourcePhysicsTick,
  (int)(0) requestedMode,
  (int)(0) gait,
  (double)(0.) vx,
  (double)(0.) vy,
  (double)(0.) vyaw,
  (bool)(false) headValid,
  (double)(0.) headYaw,
  (double)(0.) headPitch,
  (bool)(false) getUp,
  (unsigned)(0) kickSequence,
});

STREAMABLE(NativeMotionState,
{,
  (bool)(false) valid,
  (unsigned)(0) physicsTick,
  (unsigned)(0) nativeTicks,
  (int)(-1) mode,
  (int)(0) bodyControl,
  (int)(0) lastRpcApi,
  (int)(0) lastRpcStatus,
  (unsigned)(0) refusedRpcs,
  (unsigned)(0) acceptedGetUps,
  (unsigned)(0) completedKickPhases,
});

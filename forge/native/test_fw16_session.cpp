#include "simrobot/Fw16Session.h"
#include <cassert>
#include <iostream>

int main(int argc, char** argv)
{
  if(argc != 3) return 10;
  try
  {
    const std::string kind = argv[2];
    const bool native = kind == "native" || kind == "sdknative" || kind == "sdkvisualnative" || kind == "sdkvisualstressnative";
    ForgeFw16::Session session(argv[1], "robot5");
    for(unsigned i = 0; i < (kind == "native" ? 500u : kind == "gaitrefusal" ? 80u : kind == "sdkvisualstressnative" ? 67u : 4u); ++i)
    {
      ForgeFw16::Sensors sensor;
      sensor.physicsTick = 100 + i;
      sensor.physicsTime = .2 + i * .002;
      sensor.stepLength = .002;
      if(kind == "roundedstep")
      {
        sensor.stepLength = static_cast<float>(.002);
        sensor.physicsTime = .2 + i * sensor.stepLength;
      }
      sensor.acc = {0., 0., 9.81};
      for(unsigned j = 0; j < 22; ++j) sensor.q[j] = native ? 0. : j * .01;
      ForgeFw16::Request request;
      request.sourcePhysicsTick = kind == "stale" ? 0 : sensor.physicsTick;
      request.mode = kind == "native" ? 1 : 2;
      if(kind == "damping" && i > 0) request.mode = 0;
      if(kind == "skip" && i == 1) ++sensor.physicsTick;
      if(kind == "badclock" && i == 1) sensor.physicsTime += .001;
      const bool external = kind.rfind("sdk", 0) == 0;
      ForgeFw16Rpc sdk{};
      if(external && i < 3)
      {
        const char* body = i == 0 ? " { \"mode\" : 1 }\n" : i == 1 ? "" : "{\"start\":false}";
        sdk.version = 1; sdk.sequence = kind == "sdkbadsequence" && i == 1 ? 1 : i + 1;
        sdk.api_id = i == 0 ? 2000 : i == 1 ? 2018 : 2038;
        sdk.body_length = std::strlen(body);
        std::memcpy(sdk.body, body, sdk.body_length);
      }
      const auto* command = external && i < 3 ? &sdk : nullptr;
      ForgeFw16VisualKick kick{};
      if(kind.rfind("sdkvisual", 0) == 0 && i >= 3)
      {
        kick.version = 1; kick.sequence = i + 1; kick.sec = 0; kick.nanosec = i * 2000000;
        const double values[] = {.4, -.2, .3, 4., 1., -.1, .5};
        std::copy(std::begin(values), std::end(values), kick.values);
        const char* frame = i % 2 ? "original-visual-kick-input" : "";
        kick.frame_length = std::strlen(frame); std::memcpy(kick.frame_id, frame, kick.frame_length);
      }
      const auto& output = session.step(sensor, request, command, external, kick.version ? &kick : nullptr);
      assert(output.steps == i + 1 && output.physicsTick == sensor.physicsTick);
      for(unsigned j = 0; j < 22; ++j)
      {
        if(!native)
        {
          assert(std::abs(output.q[j] - (sensor.q[j] + .5)) < 1e-6);
          assert(output.kp[j] == 10. && output.limit[j] == 36.);
        }
      }
      if(external)
      {
        assert(output.feedback.samples == i + 1 && output.feedback.valid && output.feedback.motors == 22);
        assert(output.rpcReply.api_id == (i < 3 ? sdk.api_id : 0));
        if(i == 2 && !native) assert(output.rpcReply.status == 501 && output.refusedRpcs == 1);
      }
      // A second Motion/console read must not advance the original timer.
      const auto& duplicate = session.step(sensor, request, command, external);
      assert(duplicate.steps == i + 1);
      if(kind == "gaitrefusal" && i == 79) assert(duplicate.refusedRpcs == 1);
    }
    session.stop();
    std::cout << "PASS exact_clock_and_duplicate_reuse\n";
    return 0;
  }
  catch(const std::exception& error)
  {
    std::cerr << error.what() << '\n';
    return 2;
  }
}

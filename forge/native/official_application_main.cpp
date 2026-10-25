// Simulator platform entry for the pinned official Brain and VisionNode.
// Their algorithms, behavior tree, perception, and SDK serialization are reused.
#include "brain.h"
#include "booster_vision/vision_node.h"
#include "booster_vision/base/data_syncer.hpp"
#include "OfficialApplicationWire.h"
#include "OfficialGameState.h"
#include "OfficialPortContract.h"
#include <booster/robot/b1/b1_loco_api.hpp>
#include <booster_msgs/msg/rpc_req_msg.hpp>
#include <rcl/time.h>
#include <filesystem>
#include <fstream>
#include <cstring>
#include <chrono>
#include <zlib.h>
#include <sys/un.h>
#include <sys/stat.h>

using OfficialApplication::Json;
namespace booster_interface { msg::BoosterApiReqMsg CreateChangeModeMsg(booster::robot::RobotMode); }
namespace {
Json requests = Json::array(), kick;
std::ofstream events;
uint64_t currentStep = 0, sdkCount = 0, kickCount = 0;
bool operatorInput = false;
void event(Json value) { value["step"] = currentStep; events << value.dump() << '\n'; }
void clockAt(const rclcpp::Node::SharedPtr& node, int64_t ns)
{
  auto* clock = node->get_clock()->get_clock_handle();
  if(rcl_enable_ros_time_override(clock) != RCL_RET_OK || rcl_set_ros_time_override(clock, ns) != RCL_RET_OK)
    throw std::runtime_error("cannot drive official ROS clock from simulation");
}
game_controller_interface::msg::GameControlData game(const Json& j, int ownTeam)
{
  const auto projection = OfficialApplication::projectDemoHlV12(j.at("normalized"), ownTeam);
  game_controller_interface::msg::GameControlData result;
  std::copy_n("RGme", 4, result.header.begin()); result.version = 12;
  result.packet_number = j.at("packet"); result.players_per_team = j.at("players");
  result.game_type = 1; result.state = projection.state; result.first_half = j.at("first_half");
  result.kick_off_team = j.at("kicking_team"); result.secondary_state = projection.secondary;
  result.secondary_state_info[0] = result.kick_off_team;
  result.secondary_state_info[1] = projection.phase;
  result.secs_remaining = std::max(0, j.at("remaining").get<int>());
  result.secondary_time = std::max(0, j.at("secondary_time").get<int>());
  for(unsigned t = 0; t < 2; ++t)
  {
    const auto& src = j.at("teams").at(t); auto& dst = result.teams[t];
    dst.team_number = src.at("number"); dst.score = src.at("score"); dst.field_player_colour = src.at("color");
    dst.players.resize(11);
    for(unsigned p = 0; p < 11; ++p)
    {
      const auto& player = src.at("players").at(p);
      dst.players[p].penalty = player.at("penalty");
      dst.players[p].secs_till_unpenalised = player.at("remaining");
      dst.players[p].yellow_card_count = player.at("cautions");
      dst.players[p].red_card_count = player.at("sent_off");
    }
  }
  return result;
}
}

void forge_application_sdk(const booster_msgs::msg::RpcReqMsg& message)
{
  const auto api = Json::parse(message.header).at("api_id").get<int64_t>();
  if(requests.size() >= 64 || message.body.size() > 512) throw std::runtime_error("official SDK queue exceeds wire limits");
  Json request{{"uuid", message.uuid}, {"api_id", api}, {"body", message.body},
               {"origin", operatorInput ? "operator" : "official_brain"}};
  requests.push_back(request); ++sdkCount;
  request["event"] = "SDK_REQUEST"; event(request);
}
void forge_application_kick(const brain::msg::Kick& message)
{
  kick = {{"sec", message.header.stamp.sec}, {"nanosec", message.header.stamp.nanosec},
          {"frame_id", message.header.frame_id}, {"values", {message.x, message.y, message.dir,
          message.goal_x, message.goal_y, message.robot_theta_to_field, message.power}}};
  ++kickCount; event({{"event", "VISUAL_KICK_INPUT"}, {"message", kick}});
}

int main(int argc, char** argv)
{
  int listener = -1, connection = -1;
  try
  {
    const char* socketPath = std::getenv("FORGE_APPLICATION_SOCKET");
    const char* directory = std::getenv("FORGE_APPLICATION_OUTPUT");
    const char* visionConfig = std::getenv("FORGE_APPLICATION_VISION");
    if(!socketPath || !directory || !visionConfig || std::strlen(socketPath) >= sizeof(sockaddr_un::sun_path))
      throw std::runtime_error("explicit simulator socket/output/vision config required");
    const std::filesystem::path output(directory);
    std::filesystem::create_directories(output / "camera");
    events.open(output / "application.jsonl", std::ios::out | std::ios::app);
    if(!events) throw std::runtime_error("cannot open application evidence");
    rclcpp::init(argc, argv);
    auto brain = std::make_shared<Brain>();
    clockAt(brain, 0);
    brain->init();
    const char* geometryPath = std::getenv("FORGE_APPLICATION_GEOMETRY");
    if(!geometryPath) throw std::runtime_error("explicit physical arena geometry required");
    std::ifstream geometryFile(geometryPath); Json geometry; geometryFile >> geometry;
    const auto& f = geometry.at("field");
    if(f.size() != 9) throw std::runtime_error("official field geometry needs nine dimensions");
    brain->config->fieldDimensions = {f[0],f[1],f[2],f[3],f[4],f[5],f[6],f[7],f[8]};
    brain->config->calcMapLines(); brain->config->calcMapMarkings();
    brain->locator->fieldMarkers.clear();
    brain->locator->init(brain->config->fieldDimensions, brain->config->get_min_marker_count(), brain->config->get_max_residual());
    rclcpp::NodeOptions options;
    options.parameter_overrides({rclcpp::Parameter("save_data", false), rclcpp::Parameter("save_depth", false),
                                rclcpp::Parameter("use_sim_time", true)});
    auto vision = std::make_shared<booster_vision::VisionNode>("official_sim_vision", options);
    clockAt(vision, 0);
    vision->Init(visionConfig, "");
    listener = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    sockaddr_un address{}; address.sun_family = AF_UNIX; std::strcpy(address.sun_path, socketPath);
    if(listener < 0 || ::bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) || ::listen(listener, 1))
      throw std::runtime_error("cannot open simulator-only application listener");
    ::chmod(socketPath, 0600);
    std::ofstream(output / "ready.json") << Json({{"pid", ::getpid()}, {"sdk", "original_serialization"},
      {"vision", "original_ProcessData_ProcessSegmentationData"}, {"brain", "original_tick"},
      {"clock_offset_ns", 0}}).dump(2);
    connection = ::accept4(listener, nullptr, nullptr, SOCK_CLOEXEC);
    if(connection < 0) throw std::runtime_error("application accept failed");
    timeval timeout{60, 0};
    ::setsockopt(connection, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    ::setsockopt(connection, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    const auto hello = OfficialApplication::receive(connection);
    if(!hello.pixels.empty() || hello.data.at("kind") != "hello") throw std::runtime_error("missing real2sim contract handshake");
    OfficialApplication::requirePortContract(hello.data.at("contract"));
    event({{"event","PORT_CONTRACT"},{"contract",OfficialApplication::portContract()}});
    OfficialApplication::send(connection, {{"version",1},{"kind","ready"},{"contract",OfficialApplication::portContract()}});
    uint64_t frames = 0, decisions = 0, detectionObjects = 0, balls = 0, peerMessages = 0, replies = 0, refusals = 0;
    bool cameraConfigured = false;
    int previousPlanner = -1;
    Json previousBehavior;
    double visionSeconds = 0., brainSeconds = 0., evidenceSeconds = 0.;
    using WallClock = std::chrono::steady_clock;
    const auto elapsed = [](auto start) { return std::chrono::duration<double>(WallClock::now() - start).count(); };
    for(;;)
    {
      auto packet = OfficialApplication::receive(connection); const auto& j = packet.data;
      if(j.at("version") != 1) throw std::runtime_error("unsupported official application protocol");
      if(j.at("kind") == "stop")
      {
        const Json result{{"status", "PASS"}, {"steps", currentStep}, {"brain_ticks", decisions},
          {"camera_frames", frames}, {"detection_objects", detectionObjects}, {"ball_detections", balls},
          {"sdk_requests", sdkCount}, {"sdk_replies", replies}, {"sdk_refusals", refusals},
          {"kick_messages", kickCount}, {"teammate_messages", peerMessages},
          {"runtime", "official_source_with_simulator_platform_IO"}, {"full_real2sim_qualified", false}};
        std::ofstream(output / "result.json") << result.dump(2) << '\n';
        events.flush(); OfficialApplication::send(connection, {{"version", 1}, {"kind", "stopped"}, {"step", currentStep}});
        break;
      }
      if(j.at("kind") != "step" || j.at("step").get<uint64_t>() != currentStep + 1)
        throw std::runtime_error("application physics step skipped or duplicated");
      ++currentStep;
      const int64_t ns = j.at("time_ns");
      if(ns != static_cast<int64_t>(currentStep) * 2000000LL) throw std::runtime_error("application time is not physical time");
      clockAt(brain, ns); clockAt(vision, ns);
      requests = Json::array(); kick = nullptr;
      const auto& feedback = j.at("feedback");
      const int planner = feedback.at("planner");
      if(planner != previousPlanner)
      { event({{"event", "NATIVE_PLANNER"}, {"planner", planner}}); previousPlanner = planner; }
      if(feedback.at("samples") != currentStep || feedback.at("serial").size() != 22 || feedback.at("parallel").size() != 22)
        throw std::runtime_error("stale native publisher feedback");
      booster_interface::msg::LowState low;
      for(unsigned axis = 0; axis < 3; ++axis)
      { low.imu_state.rpy[axis] = feedback.at("rpy").at(axis); low.imu_state.gyro[axis] = feedback.at("gyro").at(axis); low.imu_state.acc[axis] = feedback.at("acc").at(axis); }
      for(const auto name : {"serial", "parallel"})
      {
        auto& states = std::string(name) == "serial" ? low.motor_state_serial : low.motor_state_parallel;
        for(const auto& src : feedback.at(name))
        { booster_interface::msg::MotorState state; state.q = src[0]; state.dq = src[1]; state.tau_est = src[2]; state.mode = src[3]; states.push_back(state); }
      }
      brain->lowStateCallback(low);
      booster_interface::msg::Odometer odom;
      odom.x = feedback.at("odometer")[0]; odom.y = feedback.at("odometer")[1]; odom.theta = feedback.at("odometer")[2];
      brain->odometerCallback(odom);
      geometry_msgs::msg::Pose head;
      head.position.x = feedback.at("head_position")[0]; head.position.y = feedback.at("head_position")[1]; head.position.z = feedback.at("head_position")[2];
      head.orientation.x = feedback.at("head_orientation")[0]; head.orientation.y = feedback.at("head_orientation")[1];
      head.orientation.z = feedback.at("head_orientation")[2]; head.orientation.w = feedback.at("head_orientation")[3];
      brain->headPoseCallback(head);
      booster_interface::msg::RawBytesMsg recovery;
      recovery.msg = {feedback.at("recovery").get<uint8_t>(), feedback.at("recovery_available").get<uint8_t>(), feedback.at("planner").get<uint8_t>()};
      brain->recoveryStateCallback(recovery);
      if(j.contains("sdk_reply"))
      { auto reply = j.at("sdk_reply"); reply["event"] = "SDK_REPLY"; event(reply); ++replies; refusals += reply.at("status").get<int>() != 0; }
      if(currentStep == 1 || currentStep % 50 == 0)
      {
        const auto& src = j.at("game");
        const int ownTeam = brain->config->get_team_id();
        const auto msg = game(src, ownTeam);
        brain->gameControlCallback(msg);
        const auto projection = OfficialApplication::projectDemoHlV12(src.at("normalized"), ownTeam);
        if(projection.ownActiveRestart)
        {
          // v12 has no active-restart field: preserve the original callback's
          // restart memory without inventing preparation delays in v20 PLAYING.
          brain->data->isFreekickKickingOff = true;
          brain->data->freekickKickoffStartTime = brain->get_clock()->now();
          const std::string kind = src.at("normalized").at("restart");
          brain->data->isDirectShoot = kind == "direct_free" || kind == "penalty" || kind == "goal_kick";
          const Json names{{"direct_free","DIRECT_FREEKICK"},{"indirect_free","INDIRECT_FREEKICK"},
            {"penalty","PENALTY_KICK"},{"throw_in","THROW_IN"},{"goal_kick","GOAL_KICK"},{"corner","CORNER_KICK"}};
          brain->data->realGameSubState = names.at(kind).get<std::string>();
        }
        event({{"event","REFEREE_ADAPTER"}, {"source",src}, {"target_state",msg.state},
          {"target_secondary",msg.secondary_state}, {"target_phase",projection.phase},
          {"own_team",ownTeam}, {"own_active_restart",projection.ownActiveRestart}});
      }
      for(const auto& peer : j.at("peers"))
      { brain->communication->forgeReceiveTeamPacket(peer.get<std::vector<unsigned char>>()); ++peerMessages; }
      if(currentStep == 1 || currentStep == 1500)
      {
        operatorInput = true;
        const auto command = booster_interface::CreateChangeModeMsg(currentStep == 1 ? booster::robot::RobotMode::kPrepare : booster::robot::RobotMode::kWalking);
        booster_msgs::msg::RpcReqMsg message;
        message.uuid = "operator-mode-" + std::to_string(currentStep);
        message.header = Json({{"api_id", command.api_id}}).dump(); message.body = command.body;
        forge_application_sdk(message);
        operatorInput = false;
      }
      if(j.contains("camera"))
      {
        const auto visionStart = WallClock::now();
        const auto& c = j.at("camera"); const unsigned width = c.at("width"), height = c.at("height");
        const size_t rgbSize = size_t(width) * height * 3, depthSize = size_t(width) * height * sizeof(float);
        if(width != 544 || height != 448 || packet.pixels.size() != rgbSize + depthSize) throw std::runtime_error("camera payload mismatch");
        auto info = std::make_shared<sensor_msgs::msg::CameraInfo>(); info->width = width; info->height = height;
        info->k = {c.at("fx"), 0., c.at("cx"), 0., c.at("fy"), c.at("cy"), 0., 0., 1.};
        if(!cameraConfigured)
        { brain->imageCameraInfoCallback(info); brain->depthCameraInfoCallback(info); vision->CameraInfoCallback(info); cameraConfigured = true; }
        cv::Mat rgb(height, width, CV_8UC3, packet.pixels.data()), bgr;
        cv::cvtColor(rgb, bgr, cv::COLOR_RGB2BGR);
        cv::Mat depth(height, width, CV_32FC1); std::memcpy(depth.data, packet.pixels.data() + rgbSize, depthSize);
        booster_vision::SyncedDataBlock data;
        const double time = ns * 1e-9;
        data.color_data = {bgr, time}; data.depth_data = {depth, time};
        data.pose_data = {booster_vision::Pose(head.position.x, head.position.y, head.position.z,
          head.orientation.x, head.orientation.y, head.orientation.z, head.orientation.w), time};
        vision_interface::msg::Detections detections; detections.header.stamp = brain->now();
        vision_interface::msg::LineSegments lines; lines.header = detections.header;
        vision->ProcessData(data, detections); vision->ProcessSegmentationData(data, lines);
        brain->detectionsCallback(detections); brain->fieldLineCallback(lines);
        auto depthMessage = std::make_shared<sensor_msgs::msg::Image>();
        depthMessage->header = detections.header; depthMessage->width = width; depthMessage->height = height;
        depthMessage->encoding = "32FC1"; depthMessage->step = width * sizeof(float);
        depthMessage->data.assign(packet.pixels.begin() + rgbSize, packet.pixels.end());
        brain->depthImageCallback(depthMessage);
        visionSeconds += elapsed(visionStart);
        const auto evidenceStart = WallClock::now();
        ++frames; detectionObjects += detections.detected_objects.size(); balls += brain->data->ballDetected;
        const std::string stem = std::to_string(currentStep);
        cv::imwrite((output / "camera" / (stem + ".png")).string(), bgr);
        // Retain every original float bit while avoiding gigabytes of redundant sky depth.
        std::vector<unsigned char> planes(depthSize);
        const size_t count = size_t(width) * height;
        for(size_t byte = 0; byte < 4; ++byte)
          for(size_t pixel = 0; pixel < count; ++pixel) planes[byte * count + pixel] = depth.data[pixel * 4 + byte];
        const auto depthPath = output / "camera" / (stem + ".depth-f32-byteplanes.gz");
        gzFile raw = gzopen(depthPath.c_str(), "wb1");
        if(!raw) throw std::runtime_error("cannot open lossless depth evidence");
        const int written = gzwrite(raw, planes.data(), depthSize);
        const int closed = gzclose(raw);
        if(written != static_cast<int>(depthSize) || closed != Z_OK)
          throw std::runtime_error("cannot save lossless depth evidence");
        Json objects = Json::array();
        for(const auto& object : detections.detected_objects)
          objects.push_back({{"label", object.label}, {"confidence", object.confidence},
            {"bbox", {object.xmin, object.ymin, object.xmax, object.ymax}},
            {"position", object.position}, {"position_projection", object.position_projection},
            {"received_pos", object.received_pos}, {"position_confidence", object.position_confidence}});
        event({{"event", "OFFICIAL_PERCEPTION"}, {"objects", detections.detected_objects.size()},
          {"detections", objects},
          {"depth_encoding", "f32le-byteplanes-gzip"}, {"depth_crc32", crc32(0, depth.data, depthSize)},
          {"ball_detected", brain->data->ballDetected}, {"line_coordinates", lines.coordinates.size()}, {"time_ns", ns}});
        evidenceSeconds += elapsed(evidenceStart);
      }
      if(currentStep % 5 == 0)
      {
        const auto start = WallClock::now(); brain->tick(); ++decisions; brainSeconds += elapsed(start);
        Json behavior{{"decision", brain->tree->getEntry<std::string>("decision")},
          {"game_state", brain->tree->getEntry<std::string>("gc_game_state")},
          {"game_sub_state_type", brain->tree->getEntry<std::string>("gc_game_sub_state_type")},
          {"game_sub_state", brain->tree->getEntry<std::string>("gc_game_sub_state")},
          {"wait_for_opponent_kickoff", brain->tree->getEntry<bool>("wait_for_opponent_kickoff")},
          {"native_planner", planner}, {"brain_visual_kick_flag", brain->data->tmImInVisualKick},
          {"lose_ball", brain->data->lose_ball}, {"ball_out", brain->tree->getEntry<bool>("ball_out")}};
        if(behavior != previousBehavior)
        {
          previousBehavior = behavior; behavior["event"] = "BEHAVIOR_TRANSITION";
          behavior["ball_range"] = brain->data->ball.range; behavior["cost"] = brain->data->tmMyCost;
          event(behavior);
        }
      }
      Json response{{"version", 1}, {"kind", "commands"}, {"step", currentStep}, {"sdk", requests}, {"kick", kick}};
      if(currentStep % 50 == 0) response["team"] = brain->communication->forgeTeamPacket();
      if(currentStep % 500 == 0)
      { event({{"event", "OFFICIAL_APPLICATION"}, {"brain_ticks", decisions}, {"frames", frames}, {"sdk_requests", sdkCount}, {"peer_messages", peerMessages},
          {"game_state", brain->tree->getEntry<std::string>("gc_game_state")},
          {"game_sub_state_type", brain->tree->getEntry<std::string>("gc_game_sub_state_type")},
          {"game_sub_state", brain->tree->getEntry<std::string>("gc_game_sub_state")},
          {"wait_for_opponent_kickoff", brain->tree->getEntry<bool>("wait_for_opponent_kickoff")},
          {"odom_calibrated", brain->tree->getEntry<bool>("odom_calibrated")},
          {"locator_markers", brain->data->getMarkersForLocator().size()},
          {"decision", brain->tree->getEntry<std::string>("decision")},
          {"ball_detected", brain->data->ballDetected},
          {"ball_relative", {brain->data->ball.posToRobot.x, brain->data->ball.posToRobot.y}},
          {"lead", brain->data->tmImLead}, {"cost_rank", brain->data->tmMyCostRank},
          {"brain_visual_kick_flag", brain->data->tmImInVisualKick}, {"native_planner", planner},
          {"native_visual_kick_active", planner == 12 || planner == 22},
          {"wall_seconds", {{"vision", visionSeconds}, {"brain", brainSeconds}, {"camera_evidence", evidenceSeconds}}},
          {"estimated_field_pose", {brain->data->robotPoseToField.x, brain->data->robotPoseToField.y, brain->data->robotPoseToField.theta}}}); events.flush(); }
      OfficialApplication::send(connection, response);
    }
    ::close(connection); ::close(listener); ::unlink(socketPath);
    vision.reset(); brain.reset(); rclcpp::shutdown(); return 0;
  }
  catch(const std::exception& error)
  {
    std::cerr << "OFFICIAL_APPLICATION_FAILED: " << error.what() << '\n';
    if(events) { event({{"event", "ERROR"}, {"message", error.what()}}); events.flush(); }
    if(connection >= 0) ::close(connection); if(listener >= 0) ::close(listener);
    return 1;
  }
}

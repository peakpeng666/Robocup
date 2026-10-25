// Standalone numerical test, no robot/mck/service/installer interaction.
// Example ARM build: aarch64-linux-gnu-g++ -std=c++17 -O2 -I/usr/include/eigen3
//   probe_booster_parallel.cpp -ldl -o probe_booster_parallel
// Run under a matching ARM environment with the original library path as argv[1].
#include "booster_parallel_bridge.hpp"
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <vector>

using namespace forge::booster_native;

static std::string quoted(const std::string& s) {
  std::ostringstream out;
  out << '"';
  for(unsigned char c : s) {
    if(c == '"' || c == '\\') out << '\\' << c;
    else if(c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c);
    else out << c;
  }
  return out.str() + '"';
}

int main(int argc, char** argv) {
  if(argc != 2) {
    std::cerr << "usage: probe_booster_parallel /path/to/libutils_robot_dynamics.so\n";
    return 2;
  }
  unsigned cases = 0, failures = 0;
  double maxColdFk = 0., maxSeededFk = 0., maxJacFd = 0., maxInverseJacFd = 0.;
  double maxVelocity = 0., maxWork = 0., maxForce = 0., maxCondition = 0.;
  std::vector<std::string> details;
  try {
    // The vendor math ELF references glog without a DT_NEEDED entry. mck loads
    // it globally; the standalone probe supplies that same logging dependency.
    if(!dlopen("libglog.so.0", RTLD_NOW | RTLD_GLOBAL))
      throw std::runtime_error(std::string("glog dependency: ") + dlerror());
    ParallelKinematics native(argv[1]);
    for(unsigned leg : {0u, 1u})
      for(double pitch : {-0.3, -0.15, 0., 0.2})
        for(double roll : {-0.1, 0., 0.1}) {
          ++cases;
          try {
            const Vector2 q{pitch, roll}, dq{0.31, -0.23};
            const AnkleState state = native.serialToCrank(q, dq, leg);
            int coldStatus = -999, seededStatus = -999;
            const double coldError = (native.crankToSerial(state.q, leg, nullptr, &coldStatus) - q).norm();
            const double seededError = (native.crankToSerial(state.q, leg, &q, &seededStatus) - q).norm();
            Matrix2 fd;
            constexpr double eps = 1e-6;
            for(int column = 0; column < 2; ++column) {
              Vector2 plus = q, minus = q;
              plus[column] += eps;
              minus[column] -= eps;
              const Vector2 qp = native.ik(native.params, native.internalOrientation(plus, leg), false);
              const Vector2 qm = native.ik(native.params, native.internalOrientation(minus, leg), false);
              fd.col(column) = (qp - qm) / (2. * eps);
            }
            if(!fd.allFinite()) throw std::runtime_error("non-finite finite difference");
            const double jacError = (state.jacobian - fd).norm();
            const double inverseError = (state.jacobian.inverse() - fd).norm();
            const double velocityError = (state.jacobian.inverse() * state.dq - dq).norm();
            const Vector2 motorTau{2.7, -1.4};
            const Vector2 serialTau = native.motorToSerialTorque(state, motorTau);
            const double workError = std::abs(motorTau.dot(state.dq) - serialTau.dot(dq));
            const double forceError = (native.serialToMotorTorque(state, serialTau) - motorTau).norm();
            const double condition = state.jacobian.norm() * state.jacobian.inverse().norm();
            maxColdFk = std::max(maxColdFk, coldError);
            maxSeededFk = std::max(maxSeededFk, seededError);
            maxJacFd = std::max(maxJacFd, jacError);
            maxInverseJacFd = std::max(maxInverseJacFd, inverseError);
            maxVelocity = std::max(maxVelocity, velocityError);
            maxWork = std::max(maxWork, workError);
            maxForce = std::max(maxForce, forceError);
            maxCondition = std::max(maxCondition, condition);
            const bool pass = coldError < 1e-4 && seededError < 1e-4 && jacError < 1e-4 &&
                              velocityError < 1e-10 && workError < 1e-10 && forceError < 1e-10;
            failures += !pass;
            std::ostringstream row;
            row << std::setprecision(17) << "{\"leg\":" << leg << ",\"serial_q\":[" << pitch << ',' << roll
                << "],\"crank_q\":[" << state.q.x() << ',' << state.q.y() << "],\"jacobian\":[["
                << state.jacobian(0,0) << ',' << state.jacobian(0,1) << "],[" << state.jacobian(1,0) << ','
                << state.jacobian(1,1) << "]],\"cold_fk_status\":" << coldStatus
                << ",\"seeded_fk_status\":" << seededStatus << ",\"cold_fk_error\":" << coldError
                << ",\"seeded_fk_error\":" << seededError << ",\"jac_fd_error\":" << jacError
                << ",\"inverse_jac_fd_error\":" << inverseError << ",\"pass\":" << (pass ? "true" : "false") << '}';
            details.push_back(row.str());
          } catch(const std::exception& error) {
            ++failures;
            std::ostringstream row;
            row << "{\"leg\":" << leg << ",\"serial_q\":[" << pitch << ',' << roll
                << "],\"pass\":false,\"error\":" << quoted(error.what()) << '}';
            details.push_back(row.str());
          }
        }
    // Verify that torque saturation happens before ankle coordinate conversion.
    if(limitedMotorTorque(0., 0., 2., 0., 40., 1., 1., 36.) != 36. ||
       limitedMotorTorque(0., 0., -2., 0., 40., 1., -1., 36.) != -36.) ++failures;
    bool rejected = false;
    try { native.serialToCrank({std::numeric_limits<double>::quiet_NaN(), 0.}, {0., 0.}, 0); }
    catch(const std::exception&) { rejected = true; }
    if(!rejected) ++failures;
  } catch(const std::exception& error) {
    ++failures;
    details.push_back("{\"pass\":false,\"error\":" + quoted(error.what()) + '}');
  }
  std::cout << std::setprecision(17)
            << "{\"schema\":\"forge.booster-native-parallel-probe/1\",\"library\":" << quoted(argv[1])
            << ",\"cases\":" << cases << ",\"failures\":" << failures
            << ",\"max_cold_fk_error\":" << maxColdFk << ",\"max_seeded_fk_error\":" << maxSeededFk
            << ",\"max_jacobian_finite_difference_error\":" << maxJacFd
            << ",\"max_inverse_jacobian_finite_difference_error\":" << maxInverseJacFd
            << ",\"max_velocity_roundtrip_error\":" << maxVelocity
            << ",\"max_virtual_work_error\":" << maxWork << ",\"max_force_roundtrip_error\":" << maxForce
            << ",\"max_frobenius_condition_bound\":" << maxCondition
            << ",\"conclusion\":\"" << (cases == 24 && failures == 0 ? "PASS" : "FAIL") << "\",\"samples\":[";
  for(std::size_t i = 0; i < details.size(); ++i) std::cout << (i ? "," : "") << details[i];
  std::cout << "]}\n";
  return cases == 24 && failures == 0 ? 0 : 1;
}

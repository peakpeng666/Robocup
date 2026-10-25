// Local simulation adapter for Booster K1 1.6.0.10's original kinematics library.
// ABI and geometry were recovered from the retained vendor ELF DWARF and Lua.
// No vendor implementation or model weights are reproduced here. See the
// firmware-serial-boundary-static evidence under runs/booster-integration.
#pragma once

#include <Eigen/Core>
#include <Eigen/LU>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <dlfcn.h>
#include <stdexcept>
#include <string>
#include <type_traits>

namespace forge::booster_native {
using Vector2 = Eigen::Vector2d;
using Matrix2 = Eigen::Matrix2d;

// Match native C++/Eigen argument types: replacing these with POD arrays changes
// AArch64's non-trivial object calling convention even when sizes are identical.
struct ParallelFootKineParams {
  double len_link_L, len_link_R, dist_joint_LR, r_joint, width_heel;
  double pitch_offset, roll_offset;
  Eigen::Vector3d pos_ankle_in_limb, pos_ankle_shift, pos_heel_in_foot;
};
static_assert(std::is_standard_layout_v<ParallelFootKineParams>);
static_assert(sizeof(ParallelFootKineParams) == 0x80);
static_assert(offsetof(ParallelFootKineParams, pitch_offset) == 0x28);
static_assert(offsetof(ParallelFootKineParams, roll_offset) == 0x30);
static_assert(offsetof(ParallelFootKineParams, pos_ankle_in_limb) == 0x38);
static_assert(offsetof(ParallelFootKineParams, pos_ankle_shift) == 0x50);
static_assert(offsetof(ParallelFootKineParams, pos_heel_in_foot) == 0x68);
static_assert(sizeof(Vector2) == 16 && sizeof(Matrix2) == 32);

inline ParallelFootKineParams k1Parameters() {
  constexpr double radians = 0.017453292519943295;
  return {0.1580, 0.0820, 0.0590, 0.0410, 0.0480,
          -102.6627 * radians, 31.4698 * radians,
          {0.0244, 0., -0.1617}, {0., 0., 0.}, {-0.0290, 0., 0.0175}};
}

// These are original Webots simulator settings, not a claim about motor-firmware
// current/temperature protection. Saturate in motor coordinates before J^T.
inline constexpr std::array<double, 22> webotsMotorTorqueLimits = {
  8., 8., 18., 18., 18., 18., 18., 18., 18., 18.,
  60., 50., 36., 60., 36., 36., 60., 50., 36., 60., 36., 36.};

struct AnkleState {
  Vector2 q; // Crank joint angles, with native parallel zero offsets removed.
  Vector2 dq;
  Matrix2 jacobian; // d(crank q) / d(physical serial [pitch, roll]).
};

class ParallelKinematics {
 public:
  using IK = Vector2 (*)(const ParallelFootKineParams&, Vector2, bool);
  using FK = Vector2 (*)(const ParallelFootKineParams&, Vector2,
                         const Vector2*, bool, int*);
  using Jac = Matrix2 (*)(const ParallelFootKineParams&, Vector2, Vector2);

  // Requires the original library and its dependencies on the same architecture.
  // Run probe_booster_parallel first; this class does not certify a binary hash.
  explicit ParallelKinematics(const char* library) {
    handle_ = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if(!handle_) throw std::runtime_error(std::string("dlopen: ") + dlerror());
    try {
      ik = symbol<IK>("_ZN5utils24parallel_foot_kinematics18CalcParallelFootIKERKNS0_22ParallelFootKineParamsEN5Eigen6MatrixIdLi2ELi1ELi0ELi2ELi1EEEb");
      fk = symbol<FK>("_ZN5utils24parallel_foot_kinematics18CalcParallelFootFKERKNS0_22ParallelFootKineParamsEN5Eigen6MatrixIdLi2ELi1ELi0ELi2ELi1EEEPKS6_bPi");
      jac = symbol<Jac>("_ZN5utils24parallel_foot_kinematics22CalcParallelFootJacInvERKNS0_22ParallelFootKineParamsEN5Eigen6MatrixIdLi2ELi1ELi0ELi2ELi1EEES6_");
    } catch(...) { dlclose(handle_); handle_ = nullptr; throw; }
  }
  ~ParallelKinematics() { if(handle_) dlclose(handle_); }
  ParallelKinematics(const ParallelKinematics&) = delete;
  ParallelKinematics& operator=(const ParallelKinematics&) = delete;

  static int rollDirection(unsigned leg) {
    if(leg > 1) throw std::invalid_argument("leg must be 0 (left) or 1 (right)");
    return leg == 0 ? 1 : -1;
  }
  static Vector2 internalOrientation(const Vector2& serial, unsigned leg) {
    return {serial.x() - 0.13956, serial.y() * rollDirection(leg)};
  }
  static Vector2 physicalOrientation(const Vector2& internal, unsigned leg) {
    return {internal.x() + 0.13956, internal.y() * rollDirection(leg)};
  }
  static Vector2 parallelZero() { return {1.5172, 2.0664}; }

  AnkleState serialToCrank(const Vector2& serialQ, const Vector2& serialDq,
                           unsigned leg) const {
    if(!serialQ.allFinite() || !serialDq.allFinite())
      throw std::runtime_error("non-finite serial state");
    const Vector2 foot = internalOrientation(serialQ, leg);
    const Vector2 crank = ik(params, foot, false);
    Matrix2 j = jac(params, crank, foot);
    j.col(1) *= rollDirection(leg);
    validateJacobian(j);
    AnkleState result{crank - parallelZero(), j * serialDq, j};
    if(!result.q.allFinite() || !result.dq.allFinite())
      throw std::runtime_error("non-finite native IK state");
    return result;
  }

  // Native FK's status is exposed without guessing its integer enumeration.
  // The probe checks actual geometric closure separately, including cold starts.
  Vector2 crankToSerial(const Vector2& crankQ, unsigned leg,
                        const Vector2* serialSeed = nullptr,
                        int* nativeStatus = nullptr) const {
    if(!crankQ.allFinite()) throw std::runtime_error("non-finite crank state");
    Vector2 seed;
    if(serialSeed) {
      if(!serialSeed->allFinite()) throw std::runtime_error("non-finite FK seed");
      seed = internalOrientation(*serialSeed, leg);
    }
    const Vector2 foot = fk(params, crankQ + parallelZero(),
                            serialSeed ? &seed : nullptr, false, nativeStatus);
    if(!foot.allFinite()) throw std::runtime_error("non-finite native FK result");
    return physicalOrientation(foot, leg);
  }

  static void validateJacobian(const Matrix2& j) {
    if(!j.allFinite() || !std::isfinite(j.determinant()) ||
       std::abs(j.determinant()) < 1e-12)
      throw std::runtime_error("singular/non-finite native ankle Jacobian");
    const double conditionBound = j.norm() * j.inverse().norm();
    if(!std::isfinite(conditionBound) || conditionBound > 1e8)
      throw std::runtime_error("ill-conditioned native ankle Jacobian");
  }

  // Static wrapper disassembly establishes that JacInv returns dQ/dfoot; the
  // numerical probe must additionally confirm this for the actual loaded ELF.
  static Vector2 motorToSerialTorque(const AnkleState& state,
                                     const Vector2& motorTorque) {
    validateJacobian(state.jacobian);
    if(!motorTorque.allFinite()) throw std::runtime_error("non-finite motor torque");
    const Vector2 result = state.jacobian.transpose() * motorTorque;
    if(!result.allFinite()) throw std::runtime_error("non-finite serial torque");
    return result;
  }
  static Vector2 serialToMotorTorque(const AnkleState& state,
                                     const Vector2& serialTorque) {
    validateJacobian(state.jacobian);
    if(!serialTorque.allFinite()) throw std::runtime_error("non-finite serial torque");
    const Vector2 result = state.jacobian.transpose().inverse() * serialTorque;
    if(!result.allFinite()) throw std::runtime_error("non-finite motor torque");
    return result;
  }

  ParallelFootKineParams params = k1Parameters();
  IK ik = nullptr;
  FK fk = nullptr;
  Jac jac = nullptr;

 private:
  template<typename T> T symbol(const char* name) {
    dlerror();
    void* address = dlsym(handle_, name);
    const char* error = dlerror();
    if(error || !address)
      throw std::runtime_error(std::string("dlsym: ") + (error ? error : name));
    return reinterpret_cast<T>(address);
  }
  void* handle_ = nullptr;
};

inline double limitedMotorTorque(double q, double dq, double qTarget,
                                 double dqTarget, double kp, double kd,
                                 double feedForward, double limit) {
  for(double value : {q, dq, qTarget, dqTarget, kp, kd, feedForward, limit})
    if(!std::isfinite(value)) throw std::runtime_error("non-finite motor command");
  if(limit <= 0.) throw std::invalid_argument("torque limit must be positive");
  // Native MITGroupController uses no weight multiplier. RsSdk wire carries no
  // weight. This reproduces PD+feedforward, with the chosen external limit.
  const double tau = kp * (qTarget - q) + kd * (dqTarget - dq) + feedForward;
  if(!std::isfinite(tau)) throw std::runtime_error("motor torque overflow");
  return std::clamp(tau, -limit, limit);
}
} // namespace forge::booster_native

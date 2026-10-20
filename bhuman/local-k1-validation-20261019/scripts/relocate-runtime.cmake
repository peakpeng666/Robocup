# Run with cmake -P scripts/relocate-runtime.cmake after copying this tree.
get_filename_component(ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
set(LIB "${ROOT}/bhuman-local/Build/Linux/SimRobot/Develop/libSimulatedRobot.so")
set(OLD "/home/peakpeng/Documents/Codex/2026-10-19/task/bhuman-local/Make/CMake/../../Util/onnxruntime/lib/Linux")
set(NEW "$ORIGIN/../../../../Util/onnxruntime/lib/Linux")
file(RPATH_CHANGE FILE "${LIB}" OLD_RPATH "${OLD}" NEW_RPATH "${NEW}")

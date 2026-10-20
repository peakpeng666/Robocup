cmake_minimum_required(VERSION 3.14)
project(whistle_detection LANGUAGES C CXX)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(yaml-cpp REQUIRED)
if(UNIX AND NOT APPLE)
  find_package(PkgConfig REQUIRED)

  pkg_check_modules(ALSA REQUIRED alsa)
  find_library(FFTW3F_LIB NAMES fftw3f)
  if(FFTW3F_LIB)
    set(FFTW_LIBRARIES ${FFTW3F_LIB})
    find_path(FFTW_INCLUDE_DIRS NAMES fftw3.h PATHS /usr/include)
  endif()
  if(NOT FFTW3F_LIB)
    pkg_check_modules(FFTW fftw3)
    if(FFTW_FOUND)
      set(FFTW_LIBRARIES ${FFTW_LIBRARIES} fftw3f)
      if(NOT FFTW_INCLUDE_DIRS)
        set(FFTW_INCLUDE_DIRS "/usr/include")
      endif()
    else()
      message(FATAL_ERROR "FFTW3 float required: install libfftw3-dev and ensure libfftw3f is available")
    endif()
  endif()

  set(DUERWEN_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/third_party")
  set(DUERWEN_INCLUDE_DIR "${DUERWEN_ROOT}/include")
  set(DUERWEN_LIB_DIR "${DUERWEN_ROOT}/lib")

  add_executable(whistle
    src/main.cpp
    src/whistle_detection.cpp
    third_party/src/duerwen_alsa.c
    third_party/src/RecvDataCache.c
  )

  add_executable(whistle_calibrate
    src/whistle_calibrate.cpp
    third_party/src/duerwen_alsa.c
    third_party/src/RecvDataCache.c
  )

  target_include_directories(whistle PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${ALSA_INCLUDE_DIRS}
    ${DUERWEN_INCLUDE_DIR}
    ${FFTW_INCLUDE_DIRS}
  )
  target_include_directories(whistle_calibrate PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${ALSA_INCLUDE_DIRS}
    ${DUERWEN_INCLUDE_DIR}
    ${FFTW_INCLUDE_DIRS}
  )
  ament_target_dependencies(whistle rclcpp std_msgs)
  target_link_libraries(whistle
    ${DUERWEN_LIB_DIR}/libduerwen_wakeup_DOA_v1.1.0_20251113.so
    ${ALSA_LIBRARIES}
    ${FFTW_LIBRARIES}
    pthread
  )
  target_link_libraries(whistle_calibrate
    ${ALSA_LIBRARIES}
    ${FFTW_LIBRARIES}
    yaml-cpp
    pthread
  )
  set_target_properties(whistle PROPERTIES
    BUILD_RPATH "${DUERWEN_LIB_DIR}"
    INSTALL_RPATH "$ORIGIN"
  )

  install(TARGETS whistle whistle_calibrate
    DESTINATION lib/${PROJECT_NAME}
  )
  install(FILES
    ${DUERWEN_LIB_DIR}/libduerwen_wakeup_DOA.so
    ${DUERWEN_LIB_DIR}/libduerwen_wakeup_DOA_v1.1.0_20251113.so
    DESTINATION lib/${PROJECT_NAME}
  )
else()
  message(STATUS "whistle_detection: skipping whistle executable on this platform; Linux robot dependencies are required.")
endif()

install(DIRECTORY config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()

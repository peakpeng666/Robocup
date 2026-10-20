cmake_minimum_required(VERSION 3.8)
project(ros2_sync_package)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(message_filters REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(vision_interface REQUIRED)
find_package(tf2 REQUIRED)
find_package(OpenCV 4.5 REQUIRED)
find_package(YAML-CPP REQUIRED)

# add_library(sync_node
#                       src/data_syncer.hpp
#                       src/pose.cpp
#                       )


include_directories(
  include
  ${OpenCV_INCLUDE_DIRS}
  ${YAML_CPP_INCLUDE_DIR}
  ${PCL_INCLUDE_DIRS}
  ${tf2_INCLUDE_DIRS}
)

# 2. 再 add_executable
add_executable(sync_node  src/data_syncer.cpp
                          src/sync_node.cpp)



ament_target_dependencies(sync_node
  rclcpp
  sensor_msgs
  std_msgs
  geometry_msgs
  message_filters
  vision_interface
  tf2
)

target_link_libraries(sync_node
    ${OpenCV_LIBRARIES}
    ${YAML_CPP_LIBRARIES}
)

# add_executable(sync_node  src/sync_node.cpp)


install(
  DIRECTORY include/
  DESTINATION include/
)

install(TARGETS sync_node
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
add_library(booster_vision_pose_estimator SHARED pose_estimator.cpp plane_detection.cpp plane_detection_icp.cpp)
target_link_libraries(booster_vision_pose_estimator PUBLIC ${OpenCV_LIBRARIES}
                                                           ${YAML_CPP_LIBRARIES}
                                                           booster_vision_base
                                                           yolov8_model)
install(TARGETS 
  booster_vision_pose_estimator
  # DESTINATION lib/${PROJECT_NAME})
  DESTINATION lib)

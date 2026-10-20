std_msgs/Header header
float64 x # ball pos to robot x
float64 y # ball pos to robot y
float64 dribble_dir # desired dribble dir relative to robot, rad
float64 pass_dir # desired pass dir relative to robot, rad
float64 goal_x # goal pos to robot x
float64 goal_y # goal pos to robot y
float64 robot_theta_to_field # robot theta to field, rad
int32 preferred_foot # 0 unknown, 1 left, 2 right; brain defaults/falls back to 2
float64 dribble_speed # dribble approach speed, m/s
float64 pass_speed # pass approach speed, m/s

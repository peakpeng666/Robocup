USER_UID=$(id -u)
USER_GID=$(id -g)
USERNAME=$(whoami)

MODE=${1:-normal}  # 支持传参

if [ "$MODE" = "debug" ]; then
    CMD="source /home/booster/Workspace/robocup/install/setup.bash && \
source /home/booster/ThirdParty/zed-ros/install/setup.bash && \
python3 -m debugpy --listen 0.0.0.0:5678 --wait-for-client /home/booster/Workspace/robocup/src/vision_segmentation/py_vision_segmentation/segmentation.py --zed-camera --visualize-output"
else
    CMD="source /home/booster/Workspace/robocup/install/setup.bash && \
source /home/booster/ThirdParty/zed-ros/install/setup.bash && \
python3 /home/booster/Workspace/robocup/src/vision_segmentation/py_vision_segmentation/segmentation.py --zed-camera"
fi

docker run --gpus all \
    --user ${USER_UID}:${USER_GID} \
    -v /home/booster/Workspace:/home/booster/Workspace \
    -v /home/booster/ThirdParty:/home/booster/ThirdParty \
    -v /dev/shm:/dev/shm \
    --network host \
    --ipc=host \
    --pid=host \
    -e HOME=/home/${USERNAME} \
    -e USER=${USERNAME} \
    -w /home/${USERNAME} \
    segmentation_v2 \
    /bin/bash -c "$CMD"
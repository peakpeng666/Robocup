import cv2
import numpy as np
from shapely.geometry import LineString, Point
from transforms3d.quaternions import quat2mat

def fit_plane_ransac(points, n_iterations=100, threshold=0.02, min_inliers=10, max_refine_points=1000):
    """
    使用RANSAC算法从3D点云中拟合平面
    
    Args:
        points: nx3 numpy数组, 包含点云数据
        n_iterations: RANSAC迭代次数
        threshold: 点到平面距离阈值(米)
        min_inliers: 最小内点数量
    
    Returns:
        tuple: (平面参数[a,b,c,d], 内点索引)
        平面方程: ax + by + cz + d = 0
    """
    import numpy as np
    if len(points) < 3:
        return None, None
    
    best_plane = None
    best_inliers = None
    max_inliers = 0
    
    for _ in range(n_iterations):
        # 1. 随机选择3个点
        idx = np.random.choice(len(points), 3, replace=False)
        p1, p2, p3 = points[idx]
        
        # 2. 计算平面参数
        # 平面法向量 = (p2-p1) × (p3-p1)
        v1 = p2 - p1
        v2 = p3 - p1
        normal = np.cross(v1, v2)
        normal = normal / np.linalg.norm(normal)  # 单位化
        d = -np.dot(normal, p1)
        plane = np.append(normal, d)
        
        # 3. 计算所有点到平面的距离
        distances = np.abs(np.dot(points, plane[:3]) + plane[3])
        
        # 4. 统计内点
        inliers = distances < threshold
        n_inliers = np.sum(inliers)
        
        # 5. 更新最佳结果
        if n_inliers > max_inliers and n_inliers >= min_inliers:
            max_inliers = n_inliers
            best_plane = plane
            best_inliers = inliers
                
    
    if best_plane is None:
        return None, None
    # 使用所有内点重新拟合平面以提高精度，但限制点的数量
    if np.sum(best_inliers) >= min_inliers:
        inlier_points = points[best_inliers]
        
        # 如果内点太多，随机采样
        if len(inlier_points) > max_refine_points:
            sample_idx = np.random.choice(len(inlier_points), max_refine_points, replace=False)
            inlier_points = inlier_points[sample_idx]
            
        # 计算质心
        center = np.mean(inlier_points, axis=0)
        centered_points = inlier_points - center
        
        # 使用协方差矩阵的特征值分解代替SVD
        cov = np.dot(centered_points.T, centered_points) / len(centered_points)
        eigenvals, eigenvecs = np.linalg.eigh(cov)
        
        # 最小特征值对应的特征向量就是法向量
        normal = eigenvecs[:, 0]  # 特征值按升序排列
        d = -np.dot(normal, center)
        best_plane = np.append(normal, d)
    return best_plane, best_inliers


def generate_plane_points(plane_params, x_range, y_range, step=0.1):
    """
    使用平面参数生成平面上的点
    
    Args:
        plane_params: [a,b,c,d] 平面方程 ax + by + cz + d = 0
        x_range: x轴范围 [min_x, max_x]
        y_range: y轴范围 [min_y, max_y]
        step: 采样步长
        
    Returns:
        points: nx3 numpy数组，包含生成的点云
    """
    import numpy as np
    
    if plane_params is None:
        return None
        
    a, b, c, d = plane_params
    
    # 创建网格点
    x = np.arange(x_range[0], x_range[1], step)
    y = np.arange(y_range[0], y_range[1], step)
    X, Y = np.meshgrid(x, y)
    
    # 根据平面方程计算z坐标: ax + by + cz + d = 0
    # 转换为: z = -(ax + by + d)/c
    if abs(c) < 1e-6:  # 避免除以零
        return None
    
    Z = -(a*X + b*Y + d)/c
    
    # 将网格点转换为点云格式
    points = np.column_stack((X.flatten(), Y.flatten(), Z.flatten()))
    
    return points

class Intrinsic:
    def __init__(self, width, height, fx, fy, cx, cy, distortion_coefss, ROI=[]):
        self.width = width
        self.height = height
        self.fx = fx
        self.fy = fy
        self.cx = cx
        self.cy = cy
        self.distorion_coeffs = distortion_coefss
        self.x_undistort_map = np.zeros((self.height, self.width), dtype=np.float32)
        self.y_undistort_map = np.zeros((self.height, self.width), dtype=np.float32)

        if len(ROI) == 0:
            ROI = [0, 0, height, width]
        # 创建网格坐标，使用步长2进行隔点采样
        us, vs = np.meshgrid(
            np.arange(ROI[1], ROI[3], 20),  
            np.arange(ROI[0], ROI[2], 20),  
            indexing='ij'
        )
        for v in range(0, height):
            for u in range(0,width):
                uv = np.array([u, v])
                x, y = self.deproject(uv)
                self.x_undistort_map[v, u] = x
                self.y_undistort_map[v, u] = y
        self.u = us
        self.v = vs
        self.x = self.x_undistort_map[vs, us]
        self.y = self.y_undistort_map[vs, us]
    def project(self, xyz):
        '''
        Project normalized image coordinates to pixel coordinates

        Parameters:
        xyz (numpy.ndarray): Normalized image coordinates [x, y, z]

        example:

        intr = get_intrinsics()
        print(intr)

        points = [
            [0, 0, 0],
            [0, 1, 0],
            [1, 0, 0],
            [1, 1, 0]
        ]

        for point in points:
            projected_points = intr.project(point)
            print(f'Projected point: {point} -> {projected_points}')
        '''

        u = self.fx * xyz[0] / (xyz[2] + 1e-10) + self.cx
        v = self.fy * xyz[1] / (xyz[2] + 1e-10) + self.cy
        if u < 0 or u >= self.width or v < 0 or v >= self.height:
            print(f'Warning: Projected point ({u}, {v}) is outside the image bounds')
            return None
        return np.array([u, v])

    def deproject(self, uv):
        '''
        Deproject pixel coordinates to normalized image coordinates

        Parameters:
        uv (numpy.ndarray): Pixel coordinates [u, v]
        '''
        x = (uv[0] - self.cx) / self.fx
        y = (uv[1] - self.cy) / self.fy

        if len(self.distorion_coeffs) == 0 or np.sum(self.distorion_coeffs) == 0:
            return np.array([x, y])

        xo = x
        yo = y

        for _ in range(10):
            r2 = x * x + y * y
            icdist = 1 / (1 + ((self.distorion_coeffs[4] * r2 + self.distorion_coeffs[1]) * r2 + self.distorion_coeffs[0]) * r2)
            xq = x / icdist
            yq = y / icdist
            delta_x = 2 * self.distorion_coeffs[2] * xq * yq + self.distorion_coeffs[3] * (r2 + 2 * xq * xq)
            delta_y = 2 * self.distorion_coeffs[3] * xq * yq + self.distorion_coeffs[2] * (r2 + 2 * yq * yq)
            x = (xo - delta_x) * icdist
            y = (yo - delta_y) * icdist

        return np.array([x, y])

    # implement the print function
    def __str__(self):
        return f'width: {self.width}\nheight: {self.height}\nfx: {self.fx}\nfy: {self.fy}\ncx: {self.cx}\ncy: {self.cy}\ndistortion_coeffs: {self.distorion_coeffs}'


def line_to_linestring(line):
    """Convert a line segment [x1,y1,x2,y2] to a LineString object"""
    return LineString([[line[0], line[1]], [line[2], line[3]]])


def find_intersection(line1, line2):
    line1 = line_to_linestring(line1)
    line2 = line_to_linestring(line2)
    intersection = line1.intersection(line2)
    if intersection:
        if isinstance(intersection, Point):
            return intersection.x, intersection.y


def extend_line_to_borders(line, image_height, image_width):
    """将线段延长到图像边缘"""
    x1, y1, x2, y2 = line

    # 计算直线斜率
    if x2 - x1 == 0:  # 垂直线
        new_y1 = 0
        new_y2 = image_height - 1
        return [x1, new_y1, x1, new_y2]

    slope = (y2 - y1) / (x2 - x1)
    b = y1 - slope * x1

    # 计算与边界的交点
    intersections = []

    # 与左边界交点 (x=0)
    y_left = b
    if 0 <= y_left <= image_height - 1:
        intersections.append((0, y_left))

    # 与右边界交点 (x=width-1)
    y_right = slope * (image_width - 1) + b
    if 0 <= y_right <= image_height - 1:
        intersections.append((image_width - 1, y_right))

    # 与上边界交点 (y=0)
    if slope != 0:
        x_top = -b / slope
        if 0 <= x_top <= image_width - 1:
            intersections.append((x_top, 0))

    # 与下边界交点 (y=height-1)
    if slope != 0:
        x_bottom = (image_height - 1 - b) / slope
        if 0 <= x_bottom <= image_width - 1:
            intersections.append((x_bottom, image_height - 1))

    # 选择最远的两个交点
    if len(intersections) >= 2:
        # 按照到原始中点的距离排序
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2
        intersections.sort(key=lambda p: (p[0] - mid_x) ** 2 + (p[1] - mid_y) ** 2)
        return [
            int(intersections[0][0]),
            int(intersections[0][1]),
            int(intersections[-1][0]),
            int(intersections[-1][1]),
        ]

    return line


def fit_line_by_least_squares(group):
    """使用最小二乘法拟合多条线段"""
    lines, lines_3d = zip(*group)
    # 收集所有端点
    points = []
    for line in lines:
        x1, y1, x2, y2 = line
        points.append([x1, y1])
        points.append([x2, y2])
    points = np.array(points)

    points_3d = []
    for line_3d in lines_3d:
        x1, y1, x2, y2 = line_3d
        points_3d.append([x1, y1])
        points_3d.append([x2, y2])
    points_3d = np.array(points_3d)
    return fit_line_by_points(points, clip_points=True), fit_line_by_points(points_3d)

def clip_point_to_line(point, line, height, width):
    """将点投影到直线上并限制在图像范围内"""
    x, y = point
    x1, y1, x2, y2 = line
    
    # 计算直线方向向量
    dx = x2 - x1
    dy = y2 - y1
    
    # 如果是一个点而不是线段，返回None
    if dx == 0 and dy == 0:
        return None
        
    # 计算点到直线的投影
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    
    # 计算投影点坐标
    px = x1 + t * dx
    py = y1 + t * dy
    
    # 限制在图像范围内
    px = max(0, min(px, width-1))
    py = max(0, min(py, height-1))
    
    return [px, py]

def fit_line_by_points(points, clip_points=False):
    # 计算点的质心
    centroid = np.mean(points, axis=0)

    # 构造矩阵A，每行是点到质心的向量
    centered_points = points - centroid
    A = centered_points.T @ centered_points

    # 计算特征值和特征向量
    eigenvalues, eigenvectors = np.linalg.eigh(A)

    # 最大特征值对应的特征向量就是直线的方向
    direction = eigenvectors[:, 1]  # 取最大特征值对应的特征向量

    # 将方向向量单位化
    direction = direction / np.linalg.norm(direction)

    # 计算直线上最远的两个点的投影
    projections = np.dot(centered_points, direction)
    min_proj = np.min(projections)
    max_proj = np.max(projections)

    # 计算直线上的两个端点
    point1 = centroid + min_proj * direction
    point2 = centroid + max_proj * direction

    # 将端点投影回直线并限制在图像范围内
    if clip_points:
        line = [point1[0], point1[1], point2[0], point2[1]]
        point1 = clip_point_to_line(point1, line, height=384, width=640)
        point2 = clip_point_to_line(point2, line, height=384, width=640)

    return [point1[0], point1[1], point2[0], point2[1]]


def calculate_angle_difference(line1, line2):
    # 计算方向向量
    dx1 = line1[2] - line1[0]
    dy1 = line1[3] - line1[1]
    dx2 = line2[2] - line2[0]
    dy2 = line2[3] - line2[1]

    # 计算角度（弧度）
    angle1 = np.arctan2(dy1, dx1)
    angle2 = np.arctan2(dy2, dx2)

    # 计算角度差的绝对值（0到π/2之间）
    diff = abs(angle1 - angle2) % np.pi
    if diff > np.pi / 2:
        diff = np.pi - diff

    # 归一化到0-1之间
    return diff / (np.pi / 2)


def get_lines(mask):
    """从掩膜中检测线段"""

    if mask is None:
        return None
    
    # 缩放到1/4大小
    # scale = 0.5
    # small_mask = cv2.resize(mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)

    # 在小图上检测
    lsd = cv2.createLineSegmentDetector(0)
    lines = lsd.detect(mask)

    if lines[0] is None:
        return None

    # 将检测到的线段坐标还原到原始尺寸
    lines = list(lines)
    # lines[0] = lines[0] / scale

    return lines


def get_lines_from_contour(mask):
    if mask is None:
        return None
    
    ret, binary = cv2.threshold(mask, 10, 255, cv2.THRESH_BINARY)
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    if contours:
        sorted_contours = sorted(contours, key=cv2.contourArea, reverse=True)
        lines = []
        for sorted_contour in sorted_contours:
            if len(sorted_contour) > 1:
                lines.append(fit_line_by_points(sorted_contour.squeeze(),clip_points=True))
        return lines or None
    else:
        return None


def transform_to_matrix(transform_msg):
    """Convert a TransformStamped message to a 4x4 transformation matrix"""

    # Extract the translation
    translation = np.array(
        [
            transform_msg.position.x,
            transform_msg.position.y,
            transform_msg.position.z,
        ]
    )

    # Extract the quaternion and convert to rotation matrix
    quaternion = [
        transform_msg.orientation.w,  #.Note: w first
        transform_msg.orientation.x,
        transform_msg.orientation.y,
        transform_msg.orientation.z,
    ]
    rotation = quat2mat(quaternion)

    # Create 4x4 transformation matrix
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = translation

    return matrix

def create_head_transform_matrix(z_comp, pitch_comp, yaw_comp):
    """Create 4x4 transformation matrix from headprime to head frame
    Args:
        z_comp: z translation in meters
        pitch_comp: pitch angle in degrees 
        yaw_comp: yaw angle in degrees
    Returns:
        4x4 transformation matrix
    """
    # Convert angles from degrees to radians
    pitch = pitch_comp * np.pi / 180
    yaw = yaw_comp * np.pi / 180
    
    # Create rotation matrices for pitch and yaw
    # pitch rotation around Y axis
    pitch_mat = np.array([
        [np.cos(pitch), 0, np.sin(pitch), 0],
        [0, 1, 0, 0], 
        [-np.sin(pitch), 0, np.cos(pitch), z_comp],
        [0, 0, 0, 1]
    ], dtype=np.float32)
    
    # yaw rotation around Z axis
    yaw_mat = np.array([
        [np.cos(yaw), -np.sin(yaw), 0, 0],
        [np.sin(yaw), np.cos(yaw), 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1]
    ], dtype=np.float32)

    # Combine rotations: yaw * pitch
    transform = yaw_mat @ pitch_mat
    
    return transform

def convert_2d_point_format(point):
    x = min(int(point[0] * 672 / 640),671)
    y = min(int(point[1] * 376 / 384),375)

    return [x, y]

def point_2d_to_3d(point, position_matrix, camera_params, depth):
    """将2D点投影到3D空间"""
    converted_point = convert_2d_point_format(point)
    if position_matrix is not None:
        return point_2d_to_3d_by_position_matrix(converted_point, position_matrix, camera_params)
    else:
        return point_2d_to_3d_by_depth(converted_point, camera_params, depth)

def point_2d_to_3d_by_depth(point, camera_params, depth):
    """计算射线与平面的交点
    Args:
        point: 2D点坐标 [u,v]
        camera_params: 相机内参
        depth: 平面参数 [a,b,c,d] (ax + by + cz + d = 0)
    
    Returns:
        position_3d: 3D交点坐标 [x,y,z]
    """
    # 获取平面参数
    plane_params = depth
    if plane_params is None:
        return None
    
    a, b, c, d = plane_params
    intric = camera_params

    # 获取归一化射线方向
    normalized_ray = np.array([
        intric.x_undistort_map[point[1], point[0]], 
        intric.y_undistort_map[point[1], point[0]], 
        1
    ])
    
    # 计算射线与平面的交点
    # 射线方程: P = t * normalized_ray
    # 平面方程: ax + by + cz + d = 0
    # 代入得: a(t*rx) + b(t*ry) + c(t*rz) + d = 0
    # 解得: t = -d / (a*rx + b*ry + c*rz)
    
    denominator = a*normalized_ray[0] + b*normalized_ray[1] + c*normalized_ray[2]
    if abs(denominator) < 1e-6:  # 射线平行于平面
        return None
        
    t = -d / denominator
    
    # 计算交点坐标
    position_3d = t * normalized_ray
    
    # # 1. 获取平面法向量
    # normal = np.array(plane_params[:3])
    # normal = normal / np.linalg.norm(normal)  # 单位化
    
    # # 2. 计算相机在平面上的投影点（新的原点）
    # # 相机位置是原点[0,0,0]，计算其到平面的投影
    # camera_pos = np.array([0., 0., 0.])
    # d = plane_params[3]
    # t = -d / (normal[0]*camera_pos[0] + normal[1]*camera_pos[1] + normal[2]*camera_pos[2] + 1e-10)
    # origin = camera_pos + t * normal
    
    # # 3. 构建从世界坐标系到平面坐标系的旋转矩阵
    # z_axis = normal
    
    # # 使用图像中心的射线方向作为x轴的基准
    # image_center = np.array([
    #     camera_params.x_undistort_map[360, 640],  # 图像中心点(720/2, 1280/2)
    #     camera_params.y_undistort_map[360, 640], 
    #     1
    # ])
    # image_center = image_center / np.linalg.norm(image_center)
    
    # # 将图像中心射线投影到平面上
    # forward_proj = image_center - np.dot(image_center, normal) * normal
    # y_axis = forward_proj / np.linalg.norm(forward_proj)  # 归一化
    
    # # 计算y轴 (保证右手坐标系)
    # x_axis = np.cross(z_axis, y_axis)
    
    # # 检查x轴是否指向正确方向（右侧）
    # # 可以通过检查x轴与图像右方向的点乘来确定
    # right_point = np.array([
    #     camera_params.x_undistort_map[360, 1279],  # 图像中点最右侧
    #     camera_params.y_undistort_map[360, 1279], 
    #     1
    # ])
    # right_proj = right_point - np.dot(right_point, normal) * normal
    # right_proj = right_proj / np.linalg.norm(right_proj)
    
    # # 如果x轴指向左侧，翻转x轴和y轴
    # if np.dot(x_axis, right_proj) < 0:
    #     x_axis = -x_axis

    # # 构建旋转矩阵
    # R = np.vstack((x_axis, y_axis, z_axis))
    
    # # 4. 将点变换到平面坐标系
    # centered_point = position_3d - origin
    # plane_point = R @ centered_point
    
    return position_3d[:2]

def point_2d_to_3d_by_position_matrix(point, position_matrix, camera_params):
    x, y = point
    fx, fy = camera_params["intrin"]["fx"], camera_params["intrin"]["fy"]
    cx, cy = camera_params["intrin"]["cx"], camera_params["intrin"]["cy"]
    distortion_coeffs = camera_params["intrin"]["distortion_coeffs"]

    # 1. 去畸变和归一化
    x_0 = (x - cx) / fx
    y_0 = (y - cy) / fy

    # 迭代求解反畸变
    x = x_0
    y = y_0
    if len(distortion_coeffs) == 5:
        for _ in range(10):  # 10次迭代
            r2 = x * x + y * y
            icdist = 1.0 / (
                1.0
                + (
                    (distortion_coeffs[4] * r2 + distortion_coeffs[1]) * r2
                    + distortion_coeffs[0]
                )
                * r2
            )
            xq = x / icdist
            yq = y / icdist

            # 计算切向畸变
            delta_x = 2 * distortion_coeffs[2] * xq * yq + distortion_coeffs[3] * (
                r2 + 2 * xq * xq
            )
            delta_y = 2 * distortion_coeffs[3] * xq * yq + distortion_coeffs[2] * (
                r2 + 2 * yq * yq
            )

            x = (x_0 - delta_x) * icdist
            y = (y_0 - delta_y) * icdist

    # 2. 构建归一化射线方向
    normalized_ray = np.array([x, y, 1.0])

    pitch_comp = camera_params["pitch_compensation"]
    yaw_comp = camera_params["yaw_compensation"]
    z_comp = camera_params["z_compensation"]

    if pitch_comp != 0 or yaw_comp != 0 or z_comp != 0:
        head_transform = create_head_transform_matrix(z_comp, pitch_comp, yaw_comp)
        # combaine position matrix and extrinsic matrix
        combained_matrix = (
            position_matrix @ head_transform @ np.array(camera_params["extrin"])
        )
    else:
        combained_matrix = position_matrix @ np.array(camera_params["extrin"])
    # 3. 从position matrix中提取旋转矩阵和平移向量
    rot_mat = combained_matrix[:3, :3]
    trans_vec = combained_matrix[:3, 3]

    # 4. 计算旋转后的射线方向
    rotated_ray = rot_mat @ normalized_ray

    # 5. 计算与地平面(z=0)的交点
    # 解方程: trans_vec + scale * rotated_ray = [X, Y, 0]
    scale = -trans_vec[2] / rotated_ray[2]  # z=0平面

    # 6. 计算3D位置
    position_3d = trans_vec + scale * rotated_ray

    return position_3d 


def calculate_perspective_length(x1, y1, x2, y2, image_height):
    """计算考虑透视效应的线段长度"""
    # 基础长度
    base_length = np.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

    # 计算线段中点的y坐标
    mid_y = (y1 + y2) / 2

    # 计算透视权重（越靠近图像上方，权重越大）
    # 使用非线性函数使得上方的权重增长更快
    perspective_weight = np.exp((image_height - mid_y) / image_height * 0.5)

    return base_length * perspective_weight


def group_and_extend_lines(
    new_lines, lines_3d, shape, dist_threshold=0.5, slope_threshold=0.18
):

    # 根据距离和斜率阈值合并线段
    dist_threshold = dist_threshold  # 距离阈值
    slope_threshold = slope_threshold  # 斜率差阈值

    # 构建距离矩阵
    n = len(new_lines)
    distances = np.full((n, n), np.inf)
    for i in range(n):
        for j in range(i + 1, n):
            line1 = lines_3d[i]
            line2 = lines_3d[j]

            a = LineString(line_to_linestring(line1))
            b = LineString(line_to_linestring(line2))
            dist = a.distance(b)
            distances[i][j] = dist
            distances[j][i] = dist

    # 构建斜率矩阵
    n = len(new_lines)
    slopes = np.full((n, n), np.inf)
    for i in range(n):
        for j in range(i + 1, n):
            line1 = lines_3d[i]
            line2 = lines_3d[j]
            # 使用角度差来代替斜率差
            angle_diff = calculate_angle_difference(line1, line2)
            slopes[i][j] = angle_diff
            slopes[j][i] = angle_diff

    # 使用并查集进行分组
    parent = list(range(n))

    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        parent[find(x)] = find(y)

    for i in range(n):
        for j in range(i + 1, n):
            if distances[i][j] < dist_threshold and slopes[i][j] < slope_threshold:
                union(i, j)

    # 获取所有组
    groups = {}
    for i in range(n):
        root = find(i)
        if root not in groups:
            groups[root] = []
        groups[root].append((new_lines[i], lines_3d[i]))

    # 处理每一组线段
    final_lines = []
    original_lines = []
    original_lines_3d = []
    for group in groups.values():
        if len(group) == 1:
            # 单独的线段直接延长
            line, line_3d = group[0]
            h, w = shape[:2]
            extended_line = extend_line_to_borders(line, h, w)
            final_lines.append(extended_line)
            if isinstance(line, np.ndarray):
                line = line.tolist()
            original_lines.append(line)
            original_lines_3d.append(line_3d)
        else:
            merged_line, merged_line_3d = fit_line_by_least_squares(group)
            h, w = shape[:2]
            extended_line = extend_line_to_borders(merged_line, h, w)
            final_lines.append(extended_line)
            original_lines.append(merged_line)
            original_lines_3d.append(merged_line_3d)
    # sort original lines 3d by distance
    if original_lines_3d and original_lines_3d[0] is not None:
        line_lengths = []
        for line in original_lines_3d:
            x1, y1, x2, y2 = line
            length = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            line_lengths.append(length)
        # 根据长度排序所有列表
        sorted_indices = np.argsort(line_lengths)[::-1]  # 从长到短排序
        final_lines = [final_lines[i] for i in sorted_indices]
        original_lines = [original_lines[i] for i in sorted_indices]
        original_lines_3d = [original_lines_3d[i] for i in sorted_indices]
    return final_lines, original_lines, original_lines_3d


def post_process_straight_line(
    lines,
    shape,
    position_matrix,
    camera_params,
    depth,
    length_threshold=0.3,
    dist_threshold=0.5,
    slope_threshold=0.16,
):

    if lines is None:
        return [None], [None], [None]

    new_lines = []
    lines_3d = []
    for line in lines[0]:
        x1, y1, x2, y2 = line[0]
        point_3d_1 = point_2d_to_3d([x1, y1], position_matrix, camera_params, depth)
        point_3d_2 = point_2d_to_3d([x2, y2], position_matrix, camera_params, depth)
        length_3d = np.sqrt(np.sum((point_3d_1[:2] - point_3d_2[:2]) ** 2))
        if length_3d > length_threshold:
            new_lines.append(line[0])
            lines_3d.append(np.hstack((point_3d_1[:2], point_3d_2[:2])))
    if len(new_lines) == 0:
        return [None], [None], [None]
    elif len(new_lines) == 1:
        merged_line = new_lines[0].tolist()
        merged_lines_3d = lines_3d[0].tolist()
        h, w = shape[:2]
        extended_line = extend_line_to_borders(merged_line, h, w)
        return [extended_line], [merged_line], [merged_lines_3d]
    else:
        final_lines, original_lines, original_lines_3d = group_and_extend_lines(
            new_lines, lines_3d, shape, dist_threshold, slope_threshold
        )

        if len(final_lines) > 1:
            final_lines, original_lines, original_lines_3d = group_and_extend_lines(
                original_lines,
                original_lines_3d,
                shape,
                dist_threshold,
                slope_threshold,
            )

        return final_lines, original_lines, original_lines_3d


def extend_line_to_intersection(line, intersection_point):
    """
    Extends a line segment by considering three possible combinations with the intersection point,
    and returns the longest resulting line while maintaining the original direction.

    Args:
        line: List or tuple of [x1, y1, x2, y2] representing the original line segment
        intersection_point: Tuple of (x, y) representing the intersection point

    Returns:
        List [x1, y1, x2, y2] representing the longest possible line
    """
    x1, y1, x2, y2 = line
    ix, iy = intersection_point

    # Calculate all possible combinations
    line1 = [x1, y1, x2, y2]  # Original line
    line2 = [x1, y1, ix, iy]  # First point to intersection
    line3 = [ix, iy, x2, y2]  # Intersection to second point

    # Calculate lengths of each line
    def get_line_length(line):
        return np.sqrt((line[2] - line[0]) ** 2 + (line[3] - line[1]) ** 2)

    lengths = [get_line_length(line1), get_line_length(line2), get_line_length(line3)]

    # Find the longest line
    lines = [line1, line2, line3]
    return lines[np.argmax(lengths)]


def post_process_all_lines(line_dict):
    if len(line_dict["extended_touch_lines"]) > 1:
        # choose 2 touch lines
        touch_lines_with_slopes = []
        for idx, line in enumerate(line_dict["extended_touch_lines"]):
            if line is None:
                continue

            # Calculate slope/angle
            x1, y1, x2, y2 = line
            # Ensure consistent direction (bottom to top)
            if y1 > y2:
                x1, x2 = x2, x1
                y1, y2 = y2, y1

            dx = x2 - x1
            dy = y2 - y1
            angle = np.arctan2(dy, dx)
            touch_lines_with_slopes.append((idx, angle, line))

        # Sort by angle and split into two groups
        if touch_lines_with_slopes:
            # Sort by angle
            sorted_lines = sorted(touch_lines_with_slopes, key=lambda x: x[1])

            # Find the largest angle gap to split the lines
            max_gap = 0
            split_idx = 0
            for i in range(len(sorted_lines) - 1):
                gap = abs(sorted_lines[i + 1][1] - sorted_lines[i][1])
                if gap > max_gap:
                    max_gap = gap
                    split_idx = i + 1

            # Split into left and right groups
            left_group = sorted_lines[:split_idx]
            right_group = sorted_lines[split_idx:]
            new_touch_lines = []
            new_touch_lines_3d = []
            new_extended_touch_lines = []
            if left_group:
                # Get the longest line from left group
                left_longest = max(
                    left_group,
                    key=lambda x: np.linalg.norm(
                        np.array([x[2][2] - x[2][0], x[2][3] - x[2][1]])
                    ),
                )
                new_touch_lines.append(line_dict["touch_lines"][left_longest[0]])
                new_touch_lines_3d.append(line_dict["touch_lines_3d"][left_longest[0]])
                new_extended_touch_lines.append(
                    line_dict["extended_touch_lines"][left_longest[0]]
                )
            if right_group:
                # Get the longest line from right group
                right_longest = max(
                    right_group,
                    key=lambda x: np.linalg.norm(
                        np.array([x[2][2] - x[2][0], x[2][3] - x[2][1]])
                    ),
                )
                new_touch_lines.append(line_dict["touch_lines"][right_longest[0]])
                new_touch_lines_3d.append(line_dict["touch_lines_3d"][right_longest[0]])
                new_extended_touch_lines.append(
                    line_dict["extended_touch_lines"][right_longest[0]]
                )

            # Update the touch lines in line_dict
            line_dict["extended_touch_lines"] = new_extended_touch_lines
            line_dict["touch_lines"] = new_touch_lines
            line_dict["touch_lines_3d"] = new_touch_lines_3d

    # choose one bottom line and one half way line
    line_dict["extended_bottom_lines"] = line_dict["extended_bottom_lines"][:1]
    line_dict["bottom_lines"] = line_dict["bottom_lines"][:1]
    line_dict["bottom_lines_3d"] = line_dict["bottom_lines_3d"][:1]
    line_dict["extended_half_way_lines"] = line_dict["extended_half_way_lines"][:1]
    line_dict["half_way_lines"] = line_dict["half_way_lines"][:1]
    line_dict["half_way_lines_3d"] = line_dict["half_way_lines_3d"][:1]

    # bottom line x touch line
    line_dict["bottom_line_x_touch_line"] = []
    if line_dict["extended_bottom_lines"] and line_dict["extended_touch_lines"]:
        extended_bottom_line = line_dict["extended_bottom_lines"][0]
        if extended_bottom_line:
            for idx, extended_touch_line in enumerate(
                line_dict["extended_touch_lines"]
            ):
                if extended_touch_line:
                    intersection = find_intersection(
                        extended_bottom_line, extended_touch_line
                    )
                    if intersection and intersection[0] > 0 and intersection[1] > 0:
                        angle_diff = calculate_angle_difference(
                            line_dict["bottom_lines_3d"][0],
                            line_dict["touch_lines_3d"][idx],
                        )
                        if angle_diff < 0.5:
                            continue
                        line_dict["bottom_line_x_touch_line"].append(intersection)
                        # extend current line to the intersection
                        bottom_line = line_dict["bottom_lines"][0]
                        touch_line = line_dict["touch_lines"][idx]
                        line_dict["bottom_lines"][0] = extend_line_to_intersection(
                            bottom_line, intersection
                        )
                        line_dict["touch_lines"][idx] = extend_line_to_intersection(
                            touch_line, intersection
                        )

    # touch line x half way line
    line_dict["half_way_line_x_touch_line"] = []
    if line_dict["extended_half_way_lines"] and line_dict["extended_touch_lines"]:
        extended_half_way_line = line_dict["extended_half_way_lines"][0]
        if extended_half_way_line:
            for idx, extended_touch_line in enumerate(
                line_dict["extended_touch_lines"]
            ):
                if extended_touch_line:
                    intersection = find_intersection(
                        extended_half_way_line, extended_touch_line
                    )
                    if intersection:
                        angle_diff = calculate_angle_difference(
                            line_dict["half_way_lines_3d"][0],
                            line_dict["touch_lines_3d"][idx],
                        )
                        if angle_diff < 0.5:
                            continue
                        line_dict["half_way_line_x_touch_line"].append(intersection)
                        # extend current line to the intersection
                        half_way_line = line_dict["half_way_lines"][0]
                        touch_line = line_dict["touch_lines"][idx]
                        line_dict["half_way_lines"][0] = extend_line_to_intersection(
                            half_way_line, intersection
                        )
                        line_dict["touch_lines"][idx] = extend_line_to_intersection(
                            touch_line, intersection
                        )

    # bottom line x penalty line
    line_dict["bottom_line_x_penalty_line"] = []
    if line_dict["extended_bottom_lines"] and line_dict["extended_penalty_lines"]:
        extended_bottom_line = line_dict["extended_bottom_lines"][0]
        if extended_bottom_line:
            for idx, extended_penalty_line in enumerate(
                line_dict["extended_penalty_lines"]
            ):
                if extended_penalty_line:
                    intersection = find_intersection(
                        extended_bottom_line, extended_penalty_line
                    )
                    if intersection:
                        angle_diff = calculate_angle_difference(
                            line_dict["bottom_lines_3d"][0],
                            line_dict["penalty_lines_3d"][idx],
                        )
                        if angle_diff < 0.5:
                            continue
                        bottom_line = line_dict["bottom_lines"][0]
                        penalty_line = line_dict["penalty_lines"][idx]
                        if (
                            Point(intersection).distance(
                                LineString(line_to_linestring(penalty_line))
                            )
                            > 50
                            or Point(intersection).distance(
                                LineString(line_to_linestring(bottom_line))
                            )
                            > 150
                        ):
                            continue

                        line_dict["bottom_line_x_penalty_line"].append(intersection)
                        # extend current line to the intersection
                        line_dict["bottom_lines"][0] = extend_line_to_intersection(
                            bottom_line, intersection
                        )
                        line_dict["penalty_lines"][idx] = extend_line_to_intersection(
                            penalty_line, intersection
                        )

    # bottom line x goal line
    line_dict["bottom_line_x_goal_line"] = []
    if line_dict["extended_bottom_lines"] and line_dict["extended_goal_lines"]:
        extended_bottom_line = line_dict["extended_bottom_lines"][0]
        if extended_bottom_line:
            for idx, extended_goal_line in enumerate(line_dict["extended_goal_lines"]):
                if extended_goal_line:
                    intersection = find_intersection(
                        extended_bottom_line, extended_goal_line
                    )
                    if intersection:
                        angle_diff = calculate_angle_difference(
                            line_dict["bottom_lines_3d"][0],
                            line_dict["goal_lines_3d"][idx],
                        )
                        if angle_diff < 0.5:
                            continue
                        bottom_line = line_dict["bottom_lines"][0]
                        goal_line = line_dict["goal_lines"][idx]
                        if (
                            Point(intersection).distance(
                                LineString(line_to_linestring(goal_line))
                            )
                            > 150
                            and Point(intersection).distance(
                                LineString(line_to_linestring(bottom_line))
                            )
                            > 150
                        ):
                            continue

                        line_dict["bottom_line_x_goal_line"].append(intersection)
                        # extend current line to the intersection
                        line_dict["bottom_lines"][0] = extend_line_to_intersection(
                            bottom_line, intersection
                        )
                        line_dict["goal_lines"][idx] = extend_line_to_intersection(
                            goal_line, intersection
                        )

    # penalty line x penalty line
    line_dict["penalty_line_x_penalty_line"] = []
    if line_dict["extended_penalty_lines"]:
        for i, extended_first_line in enumerate(line_dict["extended_penalty_lines"]):
            if extended_first_line and len(line_dict["extended_penalty_lines"]) > i:
                for idx, extended_penalty_line in enumerate(
                    line_dict["extended_penalty_lines"][i + 1 :]
                ):
                    if extended_penalty_line:
                        # calculate angel of 2 lines
                        angle_diff = calculate_angle_difference(
                            line_dict["penalty_lines_3d"][i],
                            line_dict["penalty_lines_3d"][idx + i + 1],
                        )
                        if angle_diff < 0.8:
                            continue
                        a = LineString(
                            line_to_linestring(line_dict["penalty_lines_3d"][i])
                        )
                        b = LineString(
                            line_to_linestring(
                                line_dict["penalty_lines_3d"][idx + i + 1]
                            )
                        )
                        dist = a.distance(b)
                        if dist > 2:
                            continue
                        intersection = find_intersection(
                            extended_first_line, extended_penalty_line
                        )
                        if intersection:
                            first_line = line_dict["penalty_lines"][i]
                            penalty_line = line_dict["penalty_lines"][idx + i + 1]
                            if (
                                Point(intersection).distance(
                                    LineString(line_to_linestring(penalty_line))
                                )
                                > 150
                                or Point(intersection).distance(
                                    LineString(line_to_linestring(first_line))
                                )
                                > 150
                            ):
                                continue
                            line_dict["penalty_line_x_penalty_line"].append(
                                intersection
                            )
                            # extend current line to the intersection
                            line_dict["penalty_lines"][i] = extend_line_to_intersection(
                                first_line, intersection
                            )
                            line_dict["penalty_lines"][idx + i + 1] = (
                                extend_line_to_intersection(penalty_line, intersection)
                            )

    # goal line x goal line
    line_dict["goal_line_x_goal_line"] = []
    if line_dict["extended_goal_lines"]:
        for i, extended_first_line in enumerate(line_dict["extended_goal_lines"]):
            if extended_first_line and len(line_dict["extended_goal_lines"]) > i:
                for idx, extended_goal_line in enumerate(
                    line_dict["extended_goal_lines"][i + 1 :]
                ):
                    if extended_goal_line:
                        # calculate angel of 2 lines
                        angle_diff = calculate_angle_difference(
                            line_dict["goal_lines_3d"][i],
                            line_dict["goal_lines_3d"][idx + i + 1],
                        )
                        if angle_diff < 0.8:
                            continue
                        a = LineString(
                            line_to_linestring(line_dict["goal_lines_3d"][i])
                        )
                        b = LineString(
                            line_to_linestring(
                                line_dict["goal_lines_3d"][idx + i + 1]
                            )
                        )
                        dist = a.distance(b)
                        if dist > 1:
                            continue
                        intersection = find_intersection(
                            extended_first_line, extended_goal_line
                        )
                        if intersection:
                            first_line = line_dict["goal_lines"][i]
                            goal_line = line_dict["goal_lines"][idx + i + 1]
                            if (
                                Point(intersection).distance(
                                    LineString(line_to_linestring(goal_line))
                                )
                                > 150
                                or Point(intersection).distance(
                                    LineString(line_to_linestring(first_line))
                                )
                                > 150
                            ):
                                continue
                            line_dict["goal_line_x_goal_line"].append(intersection)
                            # extend current line to the intersection
                            line_dict["goal_lines"][i] = extend_line_to_intersection(
                                first_line, intersection
                            )
                            line_dict["goal_lines"][idx + i + 1] = (
                                extend_line_to_intersection(goal_line, intersection)
                            )

    return line_dict

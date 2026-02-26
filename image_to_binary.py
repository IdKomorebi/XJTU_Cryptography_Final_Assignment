"""
图片到32位二进制映射系统
将图片通过SIFT特征提取映射为32位二进制字符串
"""

import cv2
import numpy as np
import os
import csv
from pathlib import Path
import shutil


def download_imagenet_images(num_classes=26, images_per_class=100, output_dir="RawImg"):
    """
    从ImageNet数据集下载图片
    注意：实际下载ImageNet需要API密钥和特定工具，这里提供一个框架
    如果无法下载，可以手动准备图片或使用其他数据集
    
    Args:
        num_classes: 类别数量（26类）
        images_per_class: 每类图片数量（100张）
        output_dir: 输出目录
    """
    print("注意：ImageNet数据下载需要API访问权限")
    print("如果无法自动下载，请手动将2600张图片（0000.jpg到2599.jpg）放入RawImg文件夹")
    
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 这里可以添加实际的ImageNet下载代码
    # 例如使用torchvision或其他工具
    # 暂时跳过，用户需要手动准备图片


def extract_sift_features(image_path, threshold=10.0):
    """
    提取图片的SIFT特征点
    
    Args:
        image_path: 图片路径
        threshold: 特征点大小阈值，小于此值的特征点会被筛选掉
    
    Returns:
        keypoints: 特征点列表
        descriptors: 特征描述符
    """
    # 读取图片
    img = cv2.imread(image_path)
    if img is None:
        print(f"无法读取图片: {image_path}")
        return [], None
    
    # 转换为灰度图
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 创建SIFT检测器
    sift = cv2.SIFT_create()
    
    # 检测特征点和描述符
    keypoints, descriptors = sift.detectAndCompute(gray, None)
    
    # 筛选掉小的特征点（根据特征点大小）
    filtered_keypoints = []
    filtered_descriptors = []
    
    if descriptors is not None:
        for i, kp in enumerate(keypoints):
            if kp.size >= threshold:  # 特征点大小阈值
                filtered_keypoints.append(kp)
                filtered_descriptors.append(descriptors[i])
    
    return filtered_keypoints, np.array(filtered_descriptors) if filtered_descriptors else None


def divide_image_into_blocks(image, block_size=(4, 4)):
    """
    将图片分成4x4共16块
    
    Args:
        image: 输入图片（numpy数组）
        block_size: 分块大小（行数，列数）
    
    Returns:
        blocks: 图片块列表
        block_coords: 每个块的坐标信息
    """
    h, w = image.shape[:2]
    rows, cols = block_size
    
    block_h = h // rows
    block_w = w // cols
    
    blocks = []
    block_coords = []
    
    for i in range(rows):
        for j in range(cols):
            y1 = i * block_h
            y2 = (i + 1) * block_h if i < rows - 1 else h
            x1 = j * block_w
            x2 = (j + 1) * block_w if j < cols - 1 else w
            
            block = image[y1:y2, x1:x2]
            blocks.append(block)
            block_coords.append((x1, y1, x2, y2))
    
    return blocks, block_coords


def get_vector_quadrant(vector):
    """
    根据特征向量的方向确定象限

    Args:
        vector: 特征向量（可以是描述符的主方向或其他向量）或角度值

    Returns:
        象限编码：第一象限=00, 第二象限=01, 第三象限=10, 第四象限=11
        如果在横轴或纵轴上，返回"--"
    """
    # 处理 None
    if vector is None:
        return "00"  # 默认值

    # 处理标量（int, float, numpy scalar）
    if isinstance(vector, (int, float, np.number)):
        direction = float(vector)
    # 处理 numpy 数组或列表
    elif isinstance(vector, (np.ndarray, list)):
        if len(vector) == 0:
            return "00"
        # 如果是一维数组且长度较小，可能是描述符
        if isinstance(vector, np.ndarray) and len(vector.shape) == 1 and len(vector) > 1:
            # 计算描述符的主成分方向
            mean_vec = np.mean(vector)
            direction = np.arctan2(np.sum(vector[1::2]), np.sum(vector[::2]))
        else:
            # 否则假设是角度数组，取平均
            direction = np.mean(vector)
    else:
        # 其他类型，尝试转换为浮点数
        try:
            direction = float(vector)
        except:
            return "00"

    # 将角度转换为象限
    # 第一象限: 0到90度 -> 00
    # 第二象限: 90到180度 -> 01
    # 第三象限: 180到270度 -> 10
    # 第四象限: 270到360度 -> 11
    # 如果在横轴或纵轴上（0, 90, 180, 270度）-> "--"

    angle_deg = np.degrees(direction) % 360
    tolerance = 1e-6  # 判断是否在轴上的容差（度）

    # 检查是否在轴上（0, 90, 180, 270度）
    if abs(angle_deg) < tolerance or abs(angle_deg - 90) < tolerance or \
       abs(angle_deg - 180) < tolerance or abs(angle_deg - 270) < tolerance or \
       abs(angle_deg - 360) < tolerance:
        return "--"

    if 0 < angle_deg < 90:
        return "00"
    elif 90 < angle_deg < 180:
        return "01"
    elif 180 < angle_deg < 270:
        return "10"
    else:  # 270 < angle_deg < 360
        return "11"


def image_to_binary(image_path, threshold=6.0):
    """
    将图片映射为32位二进制字符串
    
    Args:
        image_path: 图片路径
        threshold: SIFT特征点大小阈值
    
    Returns:
        binary_string: 32位二进制字符串
        all_keypoints: 所有块的特征点信息（用于可视化）
        block_coords: 块的坐标信息
    """
    # 读取图片
    img = cv2.imread(image_path)
    if img is None:
        print(f"无法读取图片: {image_path}")
        return None, None, None
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 分成4x4共16块
    blocks, block_coords = divide_image_into_blocks(gray, (4, 4))
    
    binary_bits = []
    all_keypoints = []
    
    # 创建SIFT检测器
    sift = cv2.SIFT_create()
    
    # 对每一块提取SIFT特征
    for idx, block in enumerate(blocks):
        # 提取该块的SIFT特征
        keypoints, descriptors = sift.detectAndCompute(block, None)
        
        # 筛选特征点
        filtered_kps = []
        filtered_descs = []
        
        if descriptors is not None:
            for i, kp in enumerate(keypoints):
                if kp.size >= threshold:
                    filtered_kps.append(kp)
                    filtered_descs.append(descriptors[i])
        
        # 计算该块的特征向量方向
        if len(filtered_kps) > 0:
            # 使用所有特征点的平均方向
            angles = [kp.angle for kp in filtered_kps]
            mean_angle = np.mean(angles)
            
            # 或者使用描述符的主方向
            if len(filtered_descs) > 0:
                desc_array = np.array(filtered_descs)
                # 计算描述符的主方向（简化方法）
                # 使用关键点的角度更直接
                quadrant = get_vector_quadrant(mean_angle)
            else:
                quadrant = get_vector_quadrant(mean_angle)
        else:
            # 如果没有特征点，使用默认值
            quadrant = "00"
        
        binary_bits.append(quadrant)
        all_keypoints.append((filtered_kps, block_coords[idx]))
    
    # 组合成32位二进制字符串
    binary_string = ''.join(binary_bits)
    
    return binary_string, all_keypoints, block_coords


def visualize_features(image_path, keypoints_info, block_coords, output_path):
    """
    可视化特征点：画点、圆（表示大小）和方向线
    
    Args:
        image_path: 原始图片路径
        keypoints_info: 所有块的特征点信息，每个元素是(keypoints, (x1, y1, x2, y2))
        block_coords: 块的坐标信息列表（未使用，保留用于兼容性）
        output_path: 输出图片路径
    """
    # 读取原始图片
    img = cv2.imread(image_path)
    if img is None:
        print(f"无法读取图片: {image_path}")
        return
    
    # 创建副本用于绘制
    vis_img = img.copy()
    
    # 遍历每个块的特征点
    for (keypoints, (bx1, by1, bx2, by2)) in keypoints_info:
        for kp in keypoints:
            # 将块内坐标转换为全局坐标
            x = int(kp.pt[0] + bx1)
            y = int(kp.pt[1] + by1)
            size = int(kp.size)
            angle = kp.angle
            
            # 画特征点（中心点）
            cv2.circle(vis_img, (x, y), 2, (0, 255, 0), -1)
            
            # 画圆表示特征点大小（半径）
            cv2.circle(vis_img, (x, y), size, (255, 0, 0), 2)
            
            # 画方向线
            angle_rad = np.radians(angle)
            end_x = int(x + size * np.cos(angle_rad))
            end_y = int(y + size * np.sin(angle_rad))
            cv2.line(vis_img, (x, y), (end_x, end_y), (0, 0, 255), 2)
    
    # 保存可视化图片
    cv2.imwrite(output_path, vis_img)


def process_images(input_dir="RawImg", output_dir="ProcessedImg", rename_dir="RenameImg", csv_file="image_binary_mapping.csv", threshold=6.0):
    """
    处理所有图片：提取特征、生成二进制映射、可视化、保存CSV
    
    Args:
        input_dir: 输入图片目录
        output_dir: 处理后图片输出目录
        rename_dir: 重命名原图输出目录
        csv_file: CSV文件名
        threshold: SIFT特征点大小阈值
    """
    # 创建输出目录（如果已存在则清空，避免重复）
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    if os.path.exists(rename_dir):
        shutil.rmtree(rename_dir)
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(rename_dir, exist_ok=True)
    
    # 准备CSV文件
    csv_data = []
    
    # 获取所有图片文件
    image_files = []
    if os.path.exists(input_dir):
        # 支持多种图片格式
        extensions = ['.jpg', '.jpeg', '.png', '.bmp']
        for ext in extensions:
            image_files.extend(Path(input_dir).glob(f'*{ext}'))
            image_files.extend(Path(input_dir).glob(f'*{ext.upper()}'))
    
    # 按文件名排序
    image_files = sorted(image_files, key=lambda x: x.name)
    
    print(f"找到 {len(image_files)} 张图片")
    
    # 如果图片数量不足，提示用户
    if len(image_files) == 0:
        print(f"警告：在 {input_dir} 目录下未找到图片文件")
        print("请确保图片文件存在，或运行下载函数准备数据")
        return
    
    # 处理每张图片，遍历时重命名为0000~0519格式
    for idx, img_path in enumerate(image_files):
        # 生成新的文件名（0000-0519格式，4位数字）
        output_name = f"{idx:04d}.jpg"
        print(f"处理图片 {idx+1}/{len(image_files)}: {img_path.name} -> {output_name}")
        
        # 复制原图到RenameImg文件夹并重命名
        rename_path = os.path.join(rename_dir, output_name)
        shutil.copy2(str(img_path), rename_path)
        
        # 提取二进制映射
        binary_string, keypoints_info, block_coords = image_to_binary(str(img_path), threshold)
        
        if binary_string is None:
            print(f"跳过图片: {img_path.name}")
            continue
        
        output_path = os.path.join(output_dir, output_name)
        
        # 可视化特征点
        visualize_features(str(img_path), keypoints_info, block_coords, output_path)
        
        # 记录到CSV（使用重命名后的文件名）
        csv_data.append({
            'image_name': output_name,
            'binary_code': binary_string
        })
    
    # 保存CSV文件
    if csv_data:
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['image_name', 'binary_code'])
            writer.writeheader()
            writer.writerows(csv_data)
        
        print(f"\n处理完成！")
        print(f"- 处理了 {len(csv_data)} 张图片")
        print(f"- 重命名原图保存在: {rename_dir}")
        print(f"- 处理后图片保存在: {output_dir}")
        print(f"- 映射关系保存在: {csv_file}")
    else:
        print("没有成功处理任何图片")


if __name__ == "__main__":
    """
    主函数
    """
    print("=" * 50)
    print("图片到32位二进制映射系统")
    print("=" * 50)
    
    # 设置参数
    input_dir = "RawImg"
    output_dir = "ProcessedImg"
    rename_dir = "RenameImg"
    csv_file = "image_binary_mapping.csv"
    threshold = 6.0  # SIFT特征点大小阈值
    
    # 检查输入目录是否存在
    if not os.path.exists(input_dir):
        print(f"\n输入目录 {input_dir} 不存在")
        print("尝试创建目录...")
        os.makedirs(input_dir, exist_ok=True)
        print(f"请将520张图片放入 {input_dir} 文件夹")
        print("程序会自动将图片重命名为0000.jpg到0519.jpg")
    else:
        # 处理所有图片
        process_images(input_dir, output_dir, rename_dir, csv_file, threshold)

import open3d as o3d
import copy
import os 
import cv2
import numpy as np
import math

### (fuction)將rgb,depth照片轉為點雲,並且分配顏色和法向量估計 ###
def depth_image_to_point_cloud(rgb,depth):
    height=512
    width=512
    fov=np.pi/2
    f=0.5*512/(np.tan(fov/2)) #caculate focus length
    #turn piexl coordinate to world  cooridnate    
    point=[]         
    color=[]
    for i in range(width):
        for j in range(height):
            z=depth[i][j][0]/25.5
            col=rgb[i][j]/255
            if (z*(i-256)/f) >(-0.5):
                point.append([z*(j-256)/f,z*(i-256)/f,z])  
                color.append([col[0],col[1],col[2]])
    pcl = o3d.geometry.PointCloud()
    pcl.points = o3d.utility.Vector3dVector(point)
    pcl.colors = o3d.utility.Vector3dVector(color)
    pcl.estimate_normals()
    return  pcl


### (fuction)將所有照片ground truth資料匯入 ###
def get_grd_point_set():
    path = './reconstuct_data/camera_path.txt'
    f = open(path, 'r')
    flag=1
    k=[]
    count=0
    for line in f.readlines():
        if(flag==1):
            k.append([])
        if(flag<=2):
            line=line.strip("\n")
            a=float(line)
            (k[count]).append(a)
            flag=1+flag
        elif(flag==3):
            flag=1
            line=line.strip("\n")
            a=float(line)
            (k[count]).append(a)
            count=count+1
    f.close()
    x=k[0][0]
    y=k[0][1]
    z=k[0][2]
    for i in range(len(k)):
        a=(k[i][0]-x)
        b=(k[i][1]-y)
        c=(k[i][2]-z)
        k[i][0]=a
        k[i][1]=b
        k[i][2]=-c
    return k


### (fuction)將ground truth與estimate差做平均並且print出來 ###
def output_trajectory_mean_data(estimate_path_points,grd_point_use):
    k=0
    for i in range(len(estimate_path_points)):
        x=estimate_path_points[i][0]-grd_point_use[i][0]
        y=estimate_path_points[i][1]-grd_point_use[i][1]
        z=estimate_path_points[i][2]-grd_point_use[i][2]
        temp=math.sqrt(x*x+y*y+z*z)
        k=k+temp
    k=k/len(estimate_path_points)
    print("Mean distance between estimated camera poses and groundtruth camera poses :",k*100,"(m)")


### 蒐集每一張照片座標資料 並且做成點雲輸出 ###
# (fuction)蒐集estimate點資料
def assemble_estimate_path(estimate_path_points,estimate_path_lines,trans):
    point=[0,0,0,1]
    point=trans@point
    point=point[:-1]
    point_ptr=len(estimate_path_points)-1
    estimate_path_points.append(point)
    if (point_ptr>=0):
        temp=[int(point_ptr),int(point_ptr+1)]
        estimate_path_lines.append(temp)
# (fuction)將estimate點資料連線並且做成點雲
def estimate_path(estimate_path_points,estimate_path_lines):
    colors = [[1, 0, 0] for i in range(len(estimate_path_lines))]
    line_set = o3d.geometry.LineSet()
    line_set.points = o3d.utility.Vector3dVector(estimate_path_points)
    # print(estimate_path_points)
    line_set.lines = o3d.utility.Vector2iVector(estimate_path_lines)
    line_set.colors = o3d.utility.Vector3dVector(colors)
    return line_set 


###  將點雲做前處理之後,透過fpfh做特徵點配對，去找到initial_matrix  ###
# (fuction)將點雲降維並且找到fpfh特徵點
def preprocess_point_cloud(pcd, voxel_size):
    pcd_down = pcd.voxel_down_sample(voxel_size)
    radius_normal = voxel_size * 2
    pcd_down.estimate_normals(
        o3d.geometry.KDTreeSearchParamHybrid(radius=radius_normal, max_nn=30))
    radius_feature = voxel_size * 5
    pcd_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
        pcd_down,
        o3d.geometry.KDTreeSearchParamHybrid(radius=radius_feature, max_nn=100))
    return pcd_down, pcd_fpfh
#   (fuction)用降維點雲與fpfh特徵點 做特徵匹配找到初始矩陣
def execute_global_registration(source_down, target_down, source_fpfh,
                                target_fpfh, voxel_size):
    distance_threshold = voxel_size * 1.5
    result = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
        source_down, target_down, source_fpfh, target_fpfh, True,
        distance_threshold,
        o3d.pipelines.registration.TransformationEstimationPointToPoint(False),
        3, [
            o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(
                0.9),
            o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(
                distance_threshold)
        ], o3d.pipelines.registration.RANSACConvergenceCriteria(100000, 0.999))
    return result


### ICP funtion ###
def local_icp_algorithm(source,target):
    voxel_size = 0.05  # means 5cm for this dataset
    source_down, source_fpfh = preprocess_point_cloud(source, voxel_size)
    target_down, target_fpfh = preprocess_point_cloud(target, voxel_size)
    #找初始矩陣
    result_ransac = execute_global_registration(source_down, target_down,source_fpfh, target_fpfh,voxel_size)
    #做icp再次疊合
    distance_threshold = voxel_size * 0.4
    result_icp = o3d.pipelines.registration.registration_icp(
        source_down, target_down, distance_threshold, result_ransac.transformation,
        o3d.pipelines.registration.TransformationEstimationPointToPlane())

    return source_down.transform(result_icp.transformation),result_icp.transformation




#### main code ####
print("###start reconstructing###")

### 先初始化存放點雲和存照片的變數 ###
final=[]
pcd_final=o3d.geometry.PointCloud()
target=o3d.geometry.PointCloud()
source=o3d.geometry.PointCloud()
line_set=o3d.geometry.PointCloud()
all_img=[]
#得到所有照片的grd資料
grd_point_use=[]
grd_path_use=[]
grd_line_set = o3d.geometry.LineSet()
#用來estimate_path
estimate_path_lines=[]
estimate_path_points=[]
## 將rgb,depth資料讀入並且存成list ##
DIR = './reconstuct_data' #要統計的資料夾
NUMBER_IMG=int(len([name for name in os.listdir(DIR) if os.path.isfile(os.path.join(DIR, name))])/2)
if(NUMBER_IMG!=0):
    grd_point_set=get_grd_point_set()
num_img=1
use_img=0
while(NUMBER_IMG>0):
    if(use_img==0):
        img0=cv2.imread('./reconstuct_data/'+'rgb_'+str(num_img)+'.png',1)
        img1=cv2.imread('./reconstuct_data/'+'img1_depth'+str(num_img)+'.png',1)
        temp=(img0,img1)
        all_img.append(temp)
        grd_point_use.append(grd_point_set[num_img-1]) #抓取所需的ground truth點資料
    ## 不用跑太多張照片,兩張建一次 ##
    #     use_img=use_img+1      
    # elif(use_img==1):
    #     use_img=0
    # else:
    #     use_img=use_img+1
    NUMBER_IMG=NUMBER_IMG-1
    num_img=num_img+1   
count=len(all_img)
print("Number of img is ",count)
## 做出grd_path點雲 ##
for i in range(len(grd_point_use)-1):
    grd_path_use.append([i,i+1])
grd_colors = [[0, 0, 0] for i in range(len(grd_point_use))]
grd_line_set.points = o3d.utility.Vector3dVector(grd_point_use)
grd_line_set.colors = o3d.utility.Vector3dVector(grd_colors)
grd_line_set.lines = o3d.utility.Vector2iVector(grd_path_use)

### 重建3D模型 ###
## 若NUMBER_IMG大於兩張,需要做ICP ##
if(count>=2):
    #將照片轉為點雲並把要作為基準的第一張照片放到final
    count=count-1
    IMG_NUM=0
    target=depth_image_to_point_cloud(all_img[IMG_NUM][0],all_img[IMG_NUM][1])
    IMG_NUM=IMG_NUM+1
    final.append(target)
    SOUR_to_TAR_trsform=np.eye(4)
    assemble_estimate_path(estimate_path_points,estimate_path_lines,SOUR_to_TAR_trsform)
    #把轉換過得source放入final且作為下一次的target
    total=count
    while(count!=0):
        count=count-1
        source=depth_image_to_point_cloud(all_img[IMG_NUM][0],all_img[IMG_NUM][1])
        IMG_NUM=IMG_NUM+1
        source, SOUR_to_TAR_trsform =local_icp_algorithm(source,target)
        assemble_estimate_path(estimate_path_points,estimate_path_lines,SOUR_to_TAR_trsform)
        final.append(source)
        target=source
        print("finish : ",int(100-count/total*100),"%")
    print("###reconstructing is done###")
    output_trajectory_mean_data(estimate_path_points,grd_point_use) #輸出路徑平均誤差
    print("total size :",total) #用了幾張照片
    ## 做出estimate_path點雲 ##
    estimate_line_set=estimate_path(estimate_path_points,estimate_path_lines,)
    ## 將所有點雲放到final並且顯示 ##
    final.append(estimate_line_set)
    final.append(grd_line_set)
    #存pcd資料
    # for point_id in range(len(final)):
    #     pcd_final += final[point_id]
    # pcd_final_down = pcd_final.voxel_down_sample(voxel_size=0.05)
    # o3d.io.write_point_cloud("multiway_registration.pcd", pcd_final_down)
    #顯示結果
    o3d.visualization.draw_geometries(final)
 ### 若NUMBER_IMG 一張,不需要做ICP ###    
elif(count==1):
    target=depth_image_to_point_cloud(all_img[0][0],all_img[0][1])
    final.append(target)
    print("###reconstructing is done###")
    o3d.visualization.draw_geometries(final)
else:
    print("There is not data.")
    print("###reconstructing is done###")


import numpy as np
import pandas as pd

from scipy.cluster.vq import vq
from os.path import exists
from copy import deepcopy
from time import time

from openalea.container import array_dict
# from openalea.image.serial.all import imread
from timagetk.components import imread
from timagetk.components import SpatialImage

from openalea.mesh.property_topomesh_io import read_ply_property_topomesh
from openalea.mesh.property_topomesh_io import save_ply_property_topomesh
from openalea.tissue_nukem_3d.nuclei_image_topomesh import nuclei_image_topomesh, nuclei_detection
from openalea.oalab.colormap.colormap_def import load_colormaps

import sys, platform
if platform.uname()[1] == "RDP-M7520-JL":
    sys.path.append('/data/Meristems/Carlos/SamMaps/scripts/TissueLab/')
elif platform.uname()[1] == "RDP-T3600-AL":
    sys.path.append('/home/marie/SamMaps/scripts/TissueLab/')
else:
    raise ValueError("Unknown system...")

from equalization import z_slice_contrast_stretch
from equalization import z_slice_equalize_adapthist
from slice_view import slice_view
from slice_view import slice_n_hist


def evaluate_nuclei_detection(nuclei_topomesh, ground_truth_topomesh, max_matching_distance=3.0, outlying_distance=5.0, max_distance=100.):
    """
    Requires the Hungarian library : https://github.com/hrldcpr/hungarian
    """

    from hungarian import lap

    segmentation_ground_truth_matching = vq(nuclei_topomesh.wisp_property('barycenter',0).values(),ground_truth_topomesh.wisp_property('barycenter',0).values())
    ground_truth_segmentation_complete_matching = np.array([vq(nuclei_topomesh.wisp_property('barycenter',0).values(),np.array([p]))[1] for p in ground_truth_topomesh.wisp_property('barycenter',0).values()])

    segmentation_outliers = array_dict(segmentation_ground_truth_matching[1]>outlying_distance+1,nuclei_topomesh.wisp_property('barycenter',0).keys())

    cost_matrix = deepcopy(ground_truth_segmentation_complete_matching)
    if cost_matrix.shape[0]<cost_matrix.shape[1]:
        cost_matrix = np.concatenate([cost_matrix,np.ones((cost_matrix.shape[1]-cost_matrix.shape[0],cost_matrix.shape[1]))*max_distance])
    elif cost_matrix.shape[1]<cost_matrix.shape[0]:
        cost_matrix = np.concatenate([cost_matrix,np.ones((cost_matrix.shape[0],cost_matrix.shape[0]-cost_matrix.shape[1]))*max_distance],axis=1)

    cost_matrix[cost_matrix > outlying_distance] = max_distance

    initial_cost_matrix = deepcopy(cost_matrix)

    start_time = time()
    print "--> Hungarian assignment..."
    assignment = lap(cost_matrix)
    end_time = time()
    print "<-- Hungarian assignment     [",end_time-start_time,"s]"

    ground_truth_assignment = np.arange(ground_truth_topomesh.nb_wisps(0))
    segmentation_assignment = assignment[0][:ground_truth_topomesh.nb_wisps(0)]
    assignment_distances = initial_cost_matrix[(ground_truth_assignment,segmentation_assignment)]
    #print "Assignment : ",assignment_distances.mean()

    evaluation = {}

    evaluation['True Positive'] = (assignment_distances < max_matching_distance).sum()
    evaluation['False Negative'] = (assignment_distances >= max_matching_distance).sum()
    evaluation['False Positive'] = nuclei_topomesh.nb_wisps(0) - segmentation_outliers.values().sum() - evaluation['True Positive']

    evaluation['Precision'] = evaluation['True Positive']/float(evaluation['True Positive']+evaluation['False Positive']) if evaluation['True Positive']+evaluation['False Positive']>0 else 100.
    evaluation['Recall'] = evaluation['True Positive']/float(evaluation['True Positive']+evaluation['False Negative'])
    evaluation['Jaccard'] = evaluation['True Positive']/float(evaluation['True Positive']+evaluation['False Positive']+evaluation['False Negative'])
    evaluation['Dice'] = 2.*evaluation['True Positive']/float(2.*evaluation['True Positive']+evaluation['False Positive']+evaluation['False Negative'])

    print "Precision ",np.round(100.*evaluation['Precision'],2),"%, Recall ",np.round(100.*evaluation['Recall'],2),"%"

    return evaluation


# Files's directories
#-----------------------
dirname = "/home/marie/"

# image_dirname = "/Users/gcerutti/Developpement/openalea/openalea_meshing_data/share/data/nuclei_ground_truth_images/"
# image_dirname = "/Users/gcerutti/Desktop/WorkVP/SamMaps/nuclei_images"
image_dirname = dirname+"Carlos/nuclei_images"

# filename = 'DR5N_6.1_151124_sam01_z0.50_t00'
# filename = 'qDII-PIN1-CLV3-PI-LD_E35_171110_sam04_t05'
filename = 'qDII-PIN1-CLV3-PI-LD_E35_171110_sam04_t00'

microscope_orientation = -1

# reference_name = "tdT"
reference_name = "TagBFP"

image_filename = image_dirname+"/"+filename+"/"+filename+"_"+reference_name+".inr.gz"

# Original image
#------------------------------
img = imread(image_filename)
size = np.array(img.shape)
voxelsize = np.array(img.voxelsize)

# Mask
#------------------------------
## mask image obtein by maximum intensity projection :
# mask_filename = image_dirname+"/"+filename+"/"+filename+"_projection_mask.inr.gz"
## 3D mask image obtein by piling a mask for each slice :
mask_filename = image_dirname+"/"+filename+"/"+filename+"_mask.inr.gz"
if exists(mask_filename):
    mask_img = imread(mask_filename)
else:
    mask_img = np.ones_like(img)

img[mask_img == 0] = 0

# world.add(mask_img,"mask",voxelsize=microscope_orientation*np.array(mask_img.voxelsize),colormap='grey',alphamap='constant',bg_id=255)
# world.add(img,"reference_image",colormap="invert_grey",voxelsize=microscope_orientation*voxelsize)

# Corrected image of detected nuclei = ground truth
#---------------------------------------------------
corrected_filename = image_dirname+"/"+filename+"/"+filename+"_nuclei_detection_topomesh_corrected.ply"
# corrected_filename = image_dirname+"/"+filename+"/"+filename+"_nuclei_detection_topomesh_corrected_AdaptHistEq.ply"
corrected_topomesh = read_ply_property_topomesh(corrected_filename)
corrected_positions = corrected_topomesh.wisp_property('barycenter',0)

## Mask application :
corrected_coords = corrected_positions.values()/(microscope_orientation*voxelsize)
corrected_coords = np.maximum(0,np.minimum(size-1,corrected_coords)).astype(np.uint16)
corrected_coords = tuple(np.transpose(corrected_coords))

corrected_mask_value = mask_img[corrected_coords]
corrected_cells_to_remove = corrected_positions.keys()[corrected_mask_value==0]
for c in corrected_cells_to_remove:
    corrected_topomesh.remove_wisp(0,c)
for property_name in corrected_topomesh.wisp_property_names(0):
    corrected_topomesh.update_wisp_property(property_name,0,array_dict(corrected_topomesh.wisp_property(property_name,0).values(list(corrected_topomesh.wisps(0))),keys=list(corrected_topomesh.wisps(0))))

# world.add(corrected_topomesh,"corrected_nuclei")
# world["corrected_nuclei"]["property_name_0"] = 'layer'
# world["corrected_nuclei_vertices"]["polydata_colormap"] = load_colormaps()['Greens']

# - Filter L1-corrected nuclei (ground truth):
L1_corrected_topomesh = deepcopy(corrected_topomesh)
L1_corrected_cells = np.array(list(L1_corrected_topomesh.wisps(0)))[L1_corrected_topomesh.wisp_property('layer',0).values()==1]
non_L1_corrected_cells = [c for c in L1_corrected_topomesh.wisps(0) if not c in L1_corrected_cells]
for c in non_L1_corrected_cells:
    L1_corrected_topomesh.remove_wisp(0,c)
for property_name in L1_corrected_topomesh.wisp_property_names(0):
    L1_corrected_topomesh.update_wisp_property(property_name,0,array_dict(L1_corrected_topomesh.wisp_property(property_name,0).values(list(L1_corrected_topomesh.wisps(0))),keys=list(L1_corrected_topomesh.wisps(0))))

# world.add(L1_corrected_topomesh,"L1_corrected_nuclei"+suffix)
# world["L1_corrected_nuclei"+suffix]["property_name_0"] = 'layer'
# world["L1_corrected_nuclei"+suffix+"_vertices"]["polydata_colormap"] = load_colormaps()['Greens']


# EVALUATION
#---------------------------------------------------

## Parameters
radius_min = 0.8
radius_max = 1.2
threshold = 2000
max_matching_distance=2.
outlying_distance=4

rescale_type = ['Original', 'AdaptHistEq', 'ContrastStretch']
evaluations = {}
L1_evaluations={}
for rescaling in rescale_type:
    evaluations[rescaling] = []
    L1_evaluations[rescaling] = []
    suffix = "_" + rescaling
    topomesh_file = image_dirname+"/"+filename+"/"+filename+"_{}_nuclei_detection_topomesh.ply".format(rescaling)
    if exists(topomesh_file):
        detected_topomesh = read_ply_property_topomesh(topomesh_file)
    else:
        if rescaling == 'AdaptHistEq':
            # Need to relaod the orignial image, we don't want to apply histogram equalization technique on masked images
            img = imread(image_filename)
            try:
                vxs = img.voxelsize
            except:
                vxs = img.resolution
            img = z_slice_equalize_adapthist(img)
            img[mask_img == 0] = 0
            img = SpatialImage(img, voxelsize=vxs)
            # world.add(img,"reference_image"+suffix,colormap="invert_grey",voxelsize=microscope_orientation*voxelsize)
        if rescaling == 'ContrastStretch':
            # Need to relaod the orignial image, we don't want to apply histogram equalization technique on masked images
            img = imread(image_filename)
            try:
                vxs = img.voxelsize
            except:
                vxs = img.resolution
            img = z_slice_contrast_stretch(img)
            img[mask_img == 0] = 0
            img = SpatialImage(img, voxelsize=vxs)
            # world.add(img,"reference_image"+suffix,colormap="invert_grey",voxelsize=microscope_orientation*voxelsize)

        # - Performs nuclei detection:
        detected_topomesh = nuclei_image_topomesh(dict([(reference_name,img)]), reference_name=reference_name, signal_names=[], compute_ratios=[], microscope_orientation=microscope_orientation, radius_range=(radius_min,radius_max), threshold=threshold)
        # detected_positions = detected_topomesh.wisp_property('barycenter',0)
        save_ply_property_topomesh(detected_topomesh, topomesh_file, properties_to_save=dict([(0,[reference_name]+['layer']),(1,[]),(2,[]),(3,[])]), color_faces=False)

    world.add(detected_topomesh, "detected_nuclei"+suffix)
    world["detected_nuclei"+suffix]["property_name_0"] = 'layer'
    world["detected_nuclei"+suffix+"_vertices"]["polydata_colormap"] = load_colormaps()['Reds']

    # - Filter L1-detected nuclei:
    L1_detected_topomesh = deepcopy(detected_topomesh)
    L1_detected_cells = np.array(list(L1_detected_topomesh.wisps(0)))[L1_detected_topomesh.wisp_property('layer',0).values()==1]
    non_L1_detected_cells = [c for c in L1_detected_topomesh.wisps(0) if not c in L1_detected_cells]
    for c in non_L1_detected_cells:
        L1_detected_topomesh.remove_wisp(0,c)
    for property_name in L1_detected_topomesh.wisp_property_names(0):
        L1_detected_topomesh.update_wisp_property(property_name,0,array_dict(L1_detected_topomesh.wisp_property(property_name,0).values(list(L1_detected_topomesh.wisps(0))),keys=list(L1_detected_topomesh.wisps(0))))
    # world.add(L1_detected_topomesh,"L1_detected_nuclei"+suffix)
    # world["L1_detected_nuclei"+suffix]["property_name_0"] = 'layer'
    # world["L1_detected_nuclei"+suffix+"_vertices"]["polydata_colormap"] = load_colormaps()['Reds']

    # - Evaluate nuclei detection for all cells:
    evaluation = evaluate_nuclei_detection(detected_topomesh, corrected_topomesh, max_matching_distance=max_matching_distance, outlying_distance=outlying_distance, max_distance=np.linalg.norm(size*voxelsize))
    evaluations[rescaling] = evaluation
    eval_fname = image_dirname+"/"+filename+"/"+filename+"_nuclei_detection_eval.csv"
    evaluation_df = pd.DataFrame().from_dict(evaluations)
    evaluation_df.to_csv(eval_fname)

    # -- Evaluate nuclei detection for L1 filtered nuclei:
    L1_evaluation = evaluate_nuclei_detection(L1_detected_topomesh, L1_corrected_topomesh, max_matching_distance=max_matching_distance, outlying_distance=outlying_distance, max_distance=np.linalg.norm(size*voxelsize))
    L1_evaluations[rescaling] = L1_evaluation
    L1_eval_fname = image_dirname+"/"+filename+"/"+filename+"_L1_nuclei_detection_eval.csv"
    evaluation_df = pd.DataFrame().from_dict(L1_evaluations)
    evaluation_df.to_csv(L1_eval_fname)



evaluation_data = {}
for field in ['filename','radius_min','radius_max','threshold']:
    evaluation_data[field] = []
evaluation_fields = ['Precision','Recall','Jaccard']
for layer in ['','L1_']:
    for field in evaluation_fields:
        evaluation_data[layer+field] = []

for radius_min in np.linspace(0.3,1.0,8):
# for radius_min in [0.8]:
    min_max = np.maximum(radius_min+0.1,0.8)
    for radius_max in np.linspace(min_max,min_max+0.7,8):
    # for radius_max in [1.4]:
        # for threshold in np.linspace(500,5000,10):
        for threshold in [2000,3000,4000]:

            evaluation_data['filename'] += [filename]
            evaluation_data['radius_min'] += [radius_min]
            evaluation_data['radius_max'] += [radius_max]
            evaluation_data['threshold'] += [threshold]

            detected_topomesh = nuclei_image_topomesh(dict([(reference_name,img)]), reference_name=reference_name, signal_names=[], compute_ratios=[], microscope_orientation=microscope_orientation, radius_range=(radius_min,radius_max), threshold=threshold)
            detected_positions = detected_topomesh.wisp_property('barycenter',0)

            world.add(detected_topomesh,"detected_nuclei")
            world["detected_nuclei"]["property_name_0"] = 'layer'
            world["detected_nuclei_vertices"]["polydata_colormap"] = load_colormaps()['Reds']

            evaluation = evaluate_nuclei_detection(detected_topomesh, corrected_topomesh, max_matching_distance=2.0, outlying_distance=4.0, max_distance=np.linalg.norm(size*voxelsize))

            for field in evaluation_fields:
                evaluation_data[field] += [evaluation[field]]

            L1_detected_topomesh = deepcopy(detected_topomesh)
            L1_detected_cells = np.array(list(L1_detected_topomesh.wisps(0)))[L1_detected_topomesh.wisp_property('layer',0).values()==1]
            non_L1_detected_cells = [c for c in L1_detected_topomesh.wisps(0) if not c in L1_detected_cells]
            for c in non_L1_detected_cells:
                L1_detected_topomesh.remove_wisp(0,c)
            for property_name in L1_detected_topomesh.wisp_property_names(0):
                L1_detected_topomesh.update_wisp_property(property_name,0,array_dict(L1_detected_topomesh.wisp_property(property_name,0).values(list(L1_detected_topomesh.wisps(0))),keys=list(L1_detected_topomesh.wisps(0))))

            L1_evaluation = evaluate_nuclei_detection(L1_detected_topomesh, L1_corrected_topomesh, max_matching_distance=2.0, outlying_distance=4.0, max_distance=np.linalg.norm(size*voxelsize))

            for field in evaluation_fields:
                evaluation_data['L1_'+field] += [L1_evaluation[field]]

n_points = np.max(map(len,evaluation_data.values()))
for k in evaluation_df.keys():
    if len(evaluation_data[k]) == n_points:
        evaluation_data[k] = evaluation_data[k][:-1]
evaluation_df = pd.DataFrame().from_dict(evaluation_data)
evaluation_df.to_csv(image_dirname+"/"+filename+"/"+filename+"_nuclei_detection_evaluation.csv")
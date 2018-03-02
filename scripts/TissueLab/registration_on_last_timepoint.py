# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from os import mkdir
from os.path import exists, splitext, split

from timagetk.algorithms import apply_trsf
from timagetk.components import imread, imsave
from timagetk.plugins import registration
from timagetk.wrapping import bal_trsf

# from timagetk.wrapping.bal_trsf import BalTransformation
import sys, platform
if platform.uname()[1] == "RDP-M7520-JL":
    SamMaps_dir = '/data/Meristems/Carlos/SamMaps/'
    dirname = "/data/Meristems/Carlos/PIN_maps/"
elif platform.uname()[1] == "calculus":
    SamMaps_dir = '/projects/SamMaps/scripts/SamMaps_git/'
    dirname = "/projects/SamMaps/"
else:
    raise ValueError("Unknown custom path to 'SamMaps' for this system...")
sys.path.append(SamMaps_dir+'/scripts/TissueLab/')

from nomenclature import splitext_zip
from nomenclature import get_nomenclature_name
from nomenclature import get_nomenclature_channel_fname
from nomenclature import get_nomenclature_segmentation_name
from nomenclature import get_res_img_fname
from nomenclature import get_res_trsf_fname
from equalization import z_slice_equalize_adapthist

# XP = 'E37'
XP = sys.argv[1]
# SAM = '5'
SAM = sys.argv[2]
# trsf_type = 'deformable'
trsf_type = sys.argv[3]

# Examples
# --------
# python SamMaps/scripts/TissueLab/rigid_registration_on_last_timepoint.py 'E35' '4' 'rigid'
# python SamMaps/scripts/TissueLab/rigid_registration_on_last_timepoint.py 'E37' '5' 'vectorfield'

nomenclature_file = SamMaps_dir + "nomenclature.csv"

# PARAMETERS:
# -----------
# -1- CZI input infos:
base_fname = "qDII-CLV3-PIN1-PI-{}-LD-SAM{}".format(XP, SAM)
time_steps = [0, 5, 10, 14]
czi_time_series = ['{}-T{}.czi'.format(base_fname, t) for t in time_steps]
# -3- OUTPUT directory:
image_dirname = dirname + "nuclei_images/"
# -4- Define CZI channel names, the microscope orientation, nuclei and membrane channel names and extra channels that should also be registered:
channel_names = ['DIIV', 'PIN1', 'PI', 'TagBFP', 'CLV3']
microscope_orientation = -1  # inverted microscope!
membrane_ch_name = 'PI'
membrane_ch_name += '_raw'

czi_base_fname = base_fname + "-T{}.czi"

# By default we register all other channels:
extra_channels = list(set(channel_names) - set([membrane_ch_name]))
# By default do not recompute deformation when an associated file exist:
force = False


from timagetk.plugins import sequence_registration

print "\n# - Building list of images for which to apply registration process:"
list_img_fname, list_img = [], []
for n, t in enumerate(time_steps):
    # -- Get the INR file names:
    path_suffix, img_fname = get_nomenclature_channel_fname(czi_base_fname.format(t), nomenclature_file, membrane_ch_name)
    print "  - Time-point {}, reading image {}...".format(n, img_fname)
    img_fname = image_dirname + path_suffix + img_fname
    list_img_fname.append(img_fname)
    im = imread(img_fname)
    if membrane_ch_name.find('raw') != -1:
        im = z_slice_equalize_adapthist(im)
    else:
        pass
    list_img.append(im)


print "\n# - Computing sequence {} registration:".format(trsf_type.upper())
list_comp_tsrf, list_res_img = sequence_registration(list_img, method='sequence_{}_registration'.format(trsf_type), try_plugin=False)


force = True
ref_im = list_img[-1]  # reference image is the last time-point
time2index = {t: n for n, t in enumerate(time_steps)}
composed_trsf = zip(list_comp_tsrf, time_steps[:-1])
for trsf, t in composed_trsf:  # 't' here refer to 't_float'
    # - Get the reference file name & path:
    ref_img_path, ref_img_fname = split(list_img_fname[-1])
    # - Get the float file name & path:
    float_im = list_img[time2index[t]]
    float_img_path, float_img_fname = split(list_img_fname[time2index[t]])
    float_img_path += "/"
    # - Get the result image file name & path (output path), and create it if necessary:
    res_img_fname = get_res_img_fname(float_img_fname, time_steps[-1], t, trsf_type)
    res_path = float_img_path + '{}_registrations/'.format(trsf_type)
    if not exists(res_path):
        mkdir(res_path)
    # - Get result trsf filename and write trsf:
    res_trsf_fname = get_res_trsf_fname(float_img_fname, time_steps[-1], t, trsf_type)

    if not exists(res_path + res_trsf_fname) or force:
        if t == time_steps[-2]:
            # -- No need to "adjust" for time_steps[-2]/time_steps[-1] registration since it is NOT a composition:
            print "\n# - Saving {} t{}/t{} registration:".format(trsf_type.upper(), time2index[t], time2index[time_steps[-1]])
            res_trsf = trsf
            res_im = list_res_img[-1]
        else:
            # -- One last round of vectorfield using composed transformation as init_trsf:
            print "\n# - Final {} registration adjustment for t{}/t{} composed transformation:".format(trsf_type.upper(), time2index[t], time2index[time_steps[-1]])
            py_hl = 1  # defines highest level of the blockmatching-pyramid
            py_ll = 0  # defines lowest level of the blockmatching-pyramid
            print '  - t_{}h floating fname: {}'.format(t, float_img_fname)
            print '  - t_{}h reference fname: {}'.format(time_steps[-1], ref_img_fname)
            print '  - {} t_{}h/t_{}h composed-trsf as initialisation'.format(trsf_type, t, time_steps[-1])
            print ""
            res_trsf, res_im = registration(float_im, ref_im, method='{}_registration'.format(trsf_type), init_trsf=trsf, pyramid_highest_level=py_hl, pyramid_lowest_level=py_ll, try_plugin=False)
            print ""

        # - Save result image and tranformation:
        print "Writing image file: {}".format(res_img_fname)
        imsave(res_path + res_img_fname, res_im)
        print "Writing trsf file: {}".format(res_trsf_fname)
        res_trsf.write(res_path + res_trsf_fname)
    else:
        print "Existing image file: {}".format(res_img_fname)
        print "Loading existing {} transformation file: {}".format(trsf_type.upper(), res_trsf_fname)
        res_trsf = bal_trsf.BalTransformation()
        res_trsf.read(res_path + res_trsf_fname)

    # -- Apply estimated transformation to other channels of the floating CZI:
    if extra_channels:
        print "\nApplying estimated {} transformation on '{}' to other channels: {}".format(trsf_type.upper(), membrane_ch_name, ', '.join(extra_channels))
        for x_ch_name in extra_channels:
            # --- Get the extra channel filenames:
            x_ch_path_suffix, x_ch_fname = get_nomenclature_channel_fname(czi_base_fname.format(t), nomenclature_file, x_ch_name)
            # --- Defines output filename:
            res_x_ch_fname = get_res_img_fname(x_ch_fname, time_steps[-1], t, trsf_type)
            if not exists(res_path + res_x_ch_fname) or True:
                print "  - {}\n  --> {}".format(x_ch_fname, res_x_ch_fname)
                # --- Read the extra channel image file:
                x_ch_img = imread(image_dirname + x_ch_path_suffix + x_ch_fname)
                # --- Apply and save registered image:
                res_x_ch_img = apply_trsf(x_ch_img, res_trsf)
                imsave(res_path + res_x_ch_fname, res_x_ch_img)
            else:
                print "  - existing file: {}".format(res_x_ch_fname)
    else:
        print "No supplementary channels to register."

    # -- Apply estimated transformation to segmented image:
    if trsf_type == 'rigid':
        seg_path_suffix, seg_img_fname = get_nomenclature_segmentation_name(czi_base_fname.format(t), nomenclature_file, membrane_ch_name)
        if exists(image_dirname + seg_path_suffix + seg_img_fname):
            print "\nApplying estimated {} transformation on '{}' to segmented image:".format(trsf_type.upper(), membrane_ch_name)
            res_seg_img_fname = get_res_img_fname(seg_img_fname, t_ref, t_float, trsf_type)
            if not exists(res_path + seg_img_fname) or force:
                print "  - {}\n  --> {}".format(seg_img_fname, res_seg_img_fname)
                # --- Read the segmented image file:
                seg_im = imread(image_dirname + seg_path_suffix + seg_img_fname)
                res_seg_im = apply_trsf(seg_im, res_trsf, param_str_2=' -nearest')
                # --- Apply and save registered segmented image:
                imsave(res_path + res_seg_img_fname, res_seg_im)
            else:
                print "  - existing file: {}".format(res_seg_img_fname)
        else:
            print "Could not find segmented image:\n  '{}'".format(image_dirname + seg_path_suffix + seg_img_fname)

# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from os import sep
from os import mkdir
from os.path import splitext
from os.path import join
from os.path import split
from os.path import exists

from timagetk.algorithms import apply_trsf
from timagetk.algorithms import compose_trsf
from timagetk.io import imsave
from timagetk.io.io_trsf import save_trsf
from timagetk.io.io_trsf import read_trsf
from timagetk.plugins import registration
from timagetk.plugins.sequence_registration import compose_to_last

import sys, platform
if platform.uname()[1] == "RDP-M7520-JL":
    SamMaps_dir = '/data/Meristems/Carlos/SamMaps/'
elif platform.uname()[1] == "calculus":
    SamMaps_dir = '/projects/SamMaps/scripts/SamMaps_git/'
else:
    raise ValueError("Unknown custom path to 'SamMaps' for this system...")
sys.path.append(SamMaps_dir+'/scripts/lib/')

from nomenclature import splitext_zip
from nomenclature import get_res_img_fname
from nomenclature import get_res_trsf_fname
from equalization import z_slice_contrast_stretch
from segmentation_pipeline import read_image

# - DEFAULT variables:
POSS_TRSF = ['rigid', 'affine', 'deformable']
# Microscope orientation:
DEF_ORIENT = -1  # '-1' == inverted microscope!


# PARAMETERS:
# -----------
import argparse
parser = argparse.ArgumentParser(description='Consecutive backward registration from last time-point.')
# positional arguments:
parser.add_argument('images', type=str, nargs='+',
                    help="list of images filename to register.")
                    # optional arguments:
parser.add_argument('--trsf_type', type=str, default='rigid',
                    help="type of registration to compute, default is 'rigid', valid options are {}".format(POSS_TRSF))
parser.add_argument('--time_steps', type=int, nargs='+',
                    help="list of time steps, should be sorted as the list of images to register!")
parser.add_argument('--extra_im', type=str, nargs='+', default=None,
                    help="list of extra intensity images to which the registration should also be applied to, should be sorted as the list of images to register!")
parser.add_argument('--seg_im', type=str, nargs='+', default=None,
                    help="list of segmented images to which the registration should also be applied to, should be sorted as the list of images to register!")
parser.add_argument('--microscope_orientation', type=int, default=DEF_ORIENT,
                    help="orientation of the microscope (i.e. set '-1' when using an inverted microscope), '{}' by default".format(DEF_ORIENT))
parser.add_argument('--output_folder', type=str, default='',
                    help="Use this to specify an output folder, else use the root path of the first image.")
parser.add_argument('--time_unit', type=str, default='h',
                    help="Time unist of the time-steps, in hours (h) by default.")
parser.add_argument('--no_consecutive_reg_img', action='store_false',
                    help="if given, images obtained from consecutive registration will NOT be writen, by default write them. Also apply to optional `extra_im` & `seg_im` given.")
parser.add_argument('--force', action='store_true',
                    help="if given, force computation of registration matrix even if they already exists, else skip it, 'False' by default")
args = parser.parse_args()

################################################################################
# - Parameters & variables definition:
################################################################################
print "\nParsed parameters & informations:"
# - Variables definition from argument parsing:
imgs2reg = args.images
trsf_type = args.trsf_type
try:
    assert trsf_type in POSS_TRSF
except AssertionError:
    raise ValueError("Unknown tranformation type '{}', valid options are: {}".format(trsf_type, POSS_TRSF))

# - Variables definition from optional arguments parsing:
try:
    time_steps = args.time_steps
    print " - Got '{}' as list time steps.".format(time_steps)
except:
    time_steps = range(len(imgs2reg))
try:
    assert len(time_steps) == len(imgs2reg)
except AssertionError:
    raise ValueError("Not the same number of images ({}) and time-steps ({}).".format(len(imgs2reg), len(time_steps)))

# -- 'extra_im' option:
extra_im = args.extra_im
if extra_im is not None:
    try:
        assert len(extra_im) == len(imgs2reg)
    except AssertionError:
        raise ValueError("Not the same number of intensity images ({}) and extra intensity images ({}).".format(len(imgs2reg), len(extra_im)))
    else:
        print " - Got a list of EXTRA intensity image to which to apply registration!"

# -- 'seg_im' option:
seg_im = args.seg_im
if seg_im is not None:
    try:
        assert len(seg_im) == len(imgs2reg)
    except AssertionError:
        raise ValueError("Not the same number of intensity images ({}) and segmented images ({}).".format(len(imgs2reg), len(seg_im)))
    else:
        print " - Got a list of SEGMENTED image to which to apply registration!"

# -- 'time_unit' option:
time_unit = args.time_unit

# -- 'output_folder' option:
out_folder = args.output_folder

# -- 'no_consecutive_reg_img' option:
write_cons_img =  not args.no_consecutive_reg_img
if write_cons_img:
    print " - WARNING: images obtained from consecutive registrations will NOT be saved!"
else:
    print " - Saving images obtained from consecutive registrations."

# -- 'force' option:
force =  args.force
if force:
    print " - WARNING: any existing files will be overwritten!"
else:
    print " - Existing files will be kept."

# -- 'microscope_orientation' option:
microscope_orientation = args.microscope_orientation
if microscope_orientation == -1:
    print " - INVERTED microscope specification!"
elif microscope_orientation == 1:
    print " - UPRIGHT microscope specification!"
else:
    raise ValueError("Unknown microscope specification, use '1' for upright, '-1' for inverted!")


# - Blockmatching parameters:
################################################################################
py_hl = 3  # defines highest level of the blockmatching-pyramid
if trsf_type == 'rigid':
    py_ll = 1  # defines lowest level of the blockmatching-pyramid
else:
    py_ll = 0  # defines lowest level of the blockmatching-pyramid

################################################################################
# - Checkpoints:
################################################################################
try:
    assert len(imgs2reg) >= 2
except AssertionError:
    raise ValueError("At least two images are required to performs blockmatching registration!")

# - Make sure we do have a sequence to register:
################################################################################
# not_sequence = True if time2index[t_ref] - time2index[t_float_list[0]] > 1 else False
not_sequence = True if len(time_steps) == 2 else False
if not_sequence:
    print " - WARNING: only two time-points have been found!"

# - Make sure the intensity images are sorted chronologically:
################################################################################
t_index = np.argsort(time_steps)
last_index = max(t_index)
# - Create a TIME-INDEXED dict of intensity image to use for registration:
indexed_img_fnames = {t: imgs2reg[i] for i, t in enumerate(t_index)}

# --- Make sure the destination folder exists:
if out_folder == '':
    out_folder, _ = split(indexed_img_fnames[min(indexed_img_fnames.keys())])
    print " - Auto-selected output folder: '{}'".format(out_folder)
else:
    print " - Given output folder: '{}'".format(out_folder)
    try:
        assert exists(out_folder)
    except AssertionError:
        print "   --> Creating it..."
        mkdir(out_folder)
    else:
        print "   --> Exists!"
# --- Make a sub-folder by registration method ussed:
out_folder += '/{}_registrations/'.format(trsf_type)
print " - Defining output sub-folder: '{}'".format(out_folder)
if not exists(out_folder):
    print "   --> Creating it..."
    mkdir(out_folder)
else:
    print "   --> Exists!"


print "\nChecking the list of intensity images to use for the registration process:"
for ti, img_fname in indexed_img_fnames.items():
    try:
        assert exists(img_fname)
    except AssertionError:
        raise ValueError("Missing file: '{}'".format(img_fname))
    else:
        print "  - Time-point {} ({}{}), adding image: '{}'...".format(ti, time_steps[ti], time_unit, img_fname)

if extra_im is not None:
    # - Create a TIME-INDEXED dict of EXTRA intensity image (to which trsf should be applied to):
    indexed_ximg_fnames = {t: extra_im[i] for i, t in enumerate(t_index)}
    print "\nChecking the list of EXTRA intensity images for which to apply the registration:"
    for ti, ximg_fname in indexed_ximg_fnames.items():
        try:
            assert exists(ximg_fname)
        except AssertionError:
            raise ValueError("Missing file: '{}'".format(ximg_fname))
        else:
            print "  - Time-point {} ({}{}), adding EXTRA image: '{}'...".format(ti, time_steps[ti], time_unit, ximg_fname)

if seg_im is not None:
    # - Create a TIME-INDEXED dict of SEGMENTED image (to which trsf should be applied to):
    indexed_simg_fnames = {t: seg_im[i] for i, t in enumerate(t_index)}
    print "\nChecking the list of SEGMENTED images for which to apply the registration:"
    for ti, simg_fname in indexed_simg_fnames.items():
        try:
            assert exists(simg_fname)
        except AssertionError:
            raise ValueError("Missing file: '{}'".format(simg_fname))
        else:
            print "  - Time-point {} ({}{}), adding SEGMENTED image: '{}'...".format(ti, time_steps[ti], time_unit, simg_fname)


################################################################################
# - Consecutive blockmatching registration:
# Trsf are saved, registered might be saved, extra image will be saved if registered are.
################################################################################
sorted_time_steps = [time_steps[i] for i in t_index]
time2index = {t: n for n, t in enumerate(time_steps)}

out_trsf_fnames = []  # list of transformation matrix filenames
for t_float, t_ref in zip(sorted_time_steps[:-1], sorted_time_steps[1:]):
    i_float = time2index[t_float]
    i_ref = time2index[t_ref]
    print "\n\n# -- Blockmatching registration t{}->t{}!".format(i_float, i_ref)
    # - Get the intensity image filenames corresponding to `t_ref` & `t_float`:
    ref_img_path, ref_img_fname = split(indexed_img_fnames[i_ref])
    float_img_path, float_img_fname = split(indexed_img_fnames[i_float])
    # - Defines the transformation matrix filename (output):
    out_trsf_fname = get_res_trsf_fname(float_img_fname, t_ref, t_float, trsf_type)
    # -- Add it to the list of transformation matrix filenames:
    out_trsf_fnames.append(out_trsf_fname)
    # - Read the reference and floating images:
    print "\n - Reading floating image (t{},{}{}): '{}'...".format(i_float, t_float, time_unit, float_img_fname)
    float_img = read_image(join(float_img_path, float_img_fname))
    print "\n - Reading reference image (t{},{}{}): '{}'...".format(i_ref, t_ref, time_unit, ref_img_fname)
    ref_img = read_image(join(ref_img_path, ref_img_fname))
    if not exists(join(out_folder, out_trsf_fname)) or force:
        print "\nComputing {} blockmatching registration t{}->t{}!".format(trsf_type.upper(), i_float, i_ref)
        # - Blockmatching registration:
        out_trsf, _ = registration(float_img, ref_img, method=trsf_type, pyramid_lowest_level=py_ll)
        # -- Save the transformation matrix:
        print "--> Saving {} transformation file: '{}'".format(trsf_type.upper(), out_trsf_fname)
        save_trsf(out_trsf, out_folder + out_trsf_fname)
    elif write_cons_img or extra_im is not None or seg_im is not None:
        print "\nFound existing tranformation t{}->t{}!".format(i_float, i_ref)
        print "--> Reading {} transformation file: '{}'".format(trsf_type.upper(), out_trsf_fname)
        out_trsf = read_trsf(out_folder + out_trsf_fname)
    else:
        print "\nFound existing tranformation t{}->t{}!".format(i_float, i_ref)
        print "--> Nothing left to do here..."
    if write_cons_img:
        print "\n{} registration of the float intensity image:".format(trsf_type.upper())
        # - Defines the registered image filename (output):
        out_img_fname = get_res_img_fname(float_img_fname, t_ref, t_float, trsf_type)
        if not exists(join(out_folder, out_img_fname)) or force:
            # -- Apply the transformation to the intensity image:
            print "--> Apply tranformation to the float intensity image..."
            out_img = apply_trsf(float_img, trsf=out_trsf, template_img=ref_img)
            # -- Save the registered image:
            print "--> Saving t{} registered intensity image: '{}'".format(i_float, out_img_fname)
            imsave(out_folder + out_img_fname, out_img)
            del out_img
        else:
            print "--> Found existing t{} registered intensity image: '{}'".format(i_float, out_img_fname)
    if extra_im is not None:
        print "\n{} registration of the EXTRA intensity image:".format(trsf_type.upper())
        # -- Defines the registered extra intensity image filename (output):
        ximg_path, ximg_fname = split(indexed_ximg_fnames[i_float])
        out_ximg_fname = get_res_img_fname(ximg_fname, t_ref, t_float, trsf_type)
        if not exists(join(out_folder, out_ximg_fname)) or force:
            # - Also apply transformation to extra image:
            # -- Read this extra intensity image file:
            print "--> Reading t{} EXTRA intensity image file: '{}'".format(i_float, out_ximg_fname)
            ximg = read_image(join(ximg_path, ximg_fname))
            # -- Apply the transformation to the extra intensity image:
            print "--> Apply tranformation to the EXTRA intensity image..."
            out_ximg = apply_trsf(ximg, trsf=out_trsf, template_img=ref_img)
            # -- Save the registered extra intensity image:
            print "--> Saving t{} registered EXTRA intensity image: '{}'".format(i_float, out_ximg_fname)
            imsave(out_folder + out_ximg_fname, out_ximg)
            del out_ximg
        else:
            print "--> Found existing t{} registered EXTRA intensity image: '{}'".format(i_float, out_ximg_fname)
    if seg_im is not None:
        print "\n{} registration of the segmented image:".format(trsf_type.upper())
        # -- Defines the registered segmented image filename (output):
        simg_path, simg_fname = split(indexed_simg_fnames[i_float])
        out_simg_fname = get_res_img_fname(simg_fname, t_ref, t_float, trsf_type)
        if not exists(join(out_folder, out_simg_fname)) or force:
            # - Also apply transformation to segmented image:
            # -- Read this segmented image file:
            print "--> Reading t{} segmented image file: '{}'".format(i_float, out_simg_fname)
            simg = read_image(join(simg_path, simg_fname))
            # -- Apply the transformation to the segmented image:
            print "--> Apply tranformation to the SEGMENTED image..."
            out_simg = apply_trsf(simg, trsf=out_trsf, template_img=ref_img, param_str_2='-nearest')
            # -- Save the registered segmented image:
            print "--> Saving t{} registered SEGMENTED image: '{}'".format(i_float, out_ximg_fname)
            imsave(out_folder + out_simg_fname, out_simg)
            del out_simg
        else:
            print "--> Found existing t{} registered segmented image: '{}'".format(i_float, out_simg_fname)
    try:
        del out_trsf
    except NameError:
        pass

################################################################################
# - Consecutive transformation composition:
################################################################################
t_ref = sorted_time_steps[-1]
# - Build the list of result transformation filenames:
seq_trsf_fnames, seq_img_fnames, seq_ximg_fnames, seq_simg_fnames = [], [], [], []
for t_float in sorted_time_steps[:-1]:
    i_float = time2index[t_float]
    # - Get the intensity image filenames corresponding to `t_float`:
    _, float_img_fname = split(indexed_img_fnames[i_float])
    # - Defines the sequence registered image filename & add it to a list:
    out_seq_img_fname = get_res_img_fname(float_img_fname, t_ref, t_float, trsf_type)
    seq_img_fnames.append(out_seq_img_fname)
    # - Defines the sequence transformation filename & add it to the list of filenames:
    out_seq_trsf_fname = get_res_trsf_fname(float_img_fname, t_ref, t_float, trsf_type)
    seq_trsf_fnames.append(out_seq_trsf_fname)
    if extra_im is not None:
        # - Defines the sequence registered EXTRA image filename & add it to a list:
        ximg_path, ximg_fname = split(indexed_ximg_fnames[i_float])
        out_seq_ximg_fname = get_res_img_fname(ximg_fname, t_ref, t_float, trsf_type)
        seq_ximg_fnames.append(out_seq_ximg_fname)
    if seg_im is not None:
        # - Defines the sequence registered EXTRA image filename & add it to a list:
        simg_path, simg_fname = split(indexed_simg_fnames[i_float])
        out_seq_simg_fname = get_res_img_fname(simg_fname, t_ref, t_float, trsf_type)
        seq_simg_fnames.append(out_seq_simg_fname)

print "\n\n# - Composing each consecutive transformations to the last one:"
# - Check if the SEQUENCE transformation files exists:
if np.all([exists(f) for f in seq_trsf_fnames]) and not force:
    print "--> Found all SEQUENCE transformation files!"
    list_comp_trsf = None
else:
    # -- Loading reference image (last time_point):
    print " - Loading reference image t{} ({}{}): '{}'".format(last_index, sorted_time_steps[last_index], time_unit, indexed_img_fnames[last_index])
    ref_img = read_image(indexed_img_fnames[last_index])
    # -- Loading all consecutive_trsf:
    print " - Loading CONSECUTIVE transformations..."
    consecutive_trsf = [read_trsf(join(out_folder, trsf_fname)) for trsf_fname in out_trsf_fnames]
    # -- Compose the consecutive transformations (to the last time_point):
    print " - Composing tranformations to last time-point..."
    list_comp_trsf = compose_to_last(consecutive_trsf, ref_img)
    del consecutive_trsf  # not needed anymore, save some memory!
    # -- Save SEQUENCE transformations:
    print " - Saving SEQUENCE {} transformation files:".format(trsf_type.upper())
    for i_float, (seq_trsf, seq_trsf_fname) in enumerate(zip(list_comp_trsf[:-1], seq_trsf_fnames[:-1])):
        print "    - t{}->t{}: '{}'".format(i_float, last_index, seq_trsf_fname)
        save_trsf(seq_trsf, join(out_folder, seq_trsf_fname))


################################################################################
# - Apply sequence transformation to intensity, extra intensity and segmented images:
################################################################################
print "\n\n# - Applying SEQUENCE transformations to intensity images:"
# - Check if the SEQUENCE registered image files exists:
if np.all([exists(f) for f in seq_img_fnames]) and not force:
    print "--> Found all SEQUENCE registered intensity image files!"
else:
    # -- Load list of sequence tranformation, if needed:
    if list_comp_trsf is None:
        print " - Loading SEQUENCE transformations..."
        list_comp_trsf = [read_trsf(seq_trsf_fname) for seq_trsf_fname in seq_trsf_fnames]
    # -- Apply sequence tranformation to intensity images:
    for i_float, out_seq_img_fname in enumerate(seq_img_fnames):
        print " - Loading t{} floating intensity image...".format(i_float)
        float_img = read_image(indexed_img_fnames[i_float])
        print " - Applying registration to floating intensity image..."
        out_seq_img = apply_trsf(float_img, trsf=list_comp_trsf[i_float], template_img=ref_img)
        print " - Saving SEQUENCE {} intensity image file: '{}'".format(trsf_type.upper(), out_seq_img_fname)
        imsave(join(out_folder, out_seq_img_fname), out_seq_img)

if extra_im is not None:
    print "\n\n# - Applying SEQUENCE transformations to EXTRA intensity images:"
    # - Check if the SEQUENCE registered EXTRA image files exists:
    if np.all([exists(f) for f in seq_ximg_fnames]) and not force:
        print "--> Found all SEQUENCE registered EXTRA intensity image files!"
    else:
        # -- Load list of sequence tranformation, if needed:
        if list_comp_trsf is None:
            print " - Loading SEQUENCE transformations..."
            list_comp_trsf = [read_trsf(seq_trsf_fname) for seq_trsf_fname in seq_trsf_fnames]
        # -- Apply sequence tranformation to EXTRA intensity images:
        for i_float, out_seq_ximg_fname in enumerate(seq_ximg_fnames):
            print " - Loading t{} EXTRA intensity image...".format(i_float)
            float_ximg = read_image(indexed_ximg_fnames[i_float])
            print " - Applying registration to EXTRA intensity image..."
            out_seq_ximg = apply_trsf(float_ximg, trsf=list_comp_trsf[i_float], template_img=ref_img)
            print " - Saving SEQUENCE {} EXTRA intensity image file: '{}'".format(trsf_type.upper(), out_seq_ximg_fname)
            imsave(join(out_folder, out_seq_ximg_fname), out_seq_img)

if seg_im is not None:
    print "\n\n# - Applying SEQUENCE transformations to segmented images:"
    # - Check if the SEQUENCE registered SEGMENTED image files exists:
    if np.all([exists(f) for f in seq_simg_fnames]) and not force:
        print "--> Found all SEQUENCE registered SEGMENTED image files!"
    else:
        # -- Load list of sequence tranformation, if needed:
        if list_comp_trsf is None:
            print " - Loading SEQUENCE transformations..."
            list_comp_trsf = [read_trsf(seq_trsf_fname) for seq_trsf_fname in seq_trsf_fnames]
        # -- Apply sequence tranformation to SEGMENTED images:
        for i_float, out_seq_simg_fname in enumerate(seq_simg_fnames):
            print " - Loading t{} segmented image...".format(i_float)
            float_simg = read_image(indexed_simg_fnames[i_float])
            print " - Applying registration to segmented image..."
            out_seq_simg = apply_trsf(float_simg, trsf=list_comp_trsf[i_float], template_img=ref_img, param_str_2='-nearest')
            print " - Saving SEQUENCE {} SEGMENTED image file: '{}'".format(trsf_type.upper(), out_seq_simg_fname)
            imsave(join(out_folder, out_seq_simg_fname), out_seq_img)

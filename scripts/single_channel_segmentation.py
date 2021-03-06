# -*- python -*-
# -*- coding: utf-8 -*-
#
#       Copyright 2018 CNRS - ENS Lyon - INRIA
#
#       File author(s): Jonathan LEGRAND <jonathan.legrand@ens-lyon.fr>
################################################################################

import argparse
from os.path import exists
from os.path import join
from os.path import split

from timagetk.io import imsave

import sys, platform
if platform.uname()[1] == "RDP-M7520-JL":
    SamMaps_dir = '/data/Meristems/Carlos/SamMaps/'
    dirname = "/data/Meristems/Carlos/PIN_maps/"
elif platform.uname()[1] == "calculus":
    SamMaps_dir = '/projects/SamMaps/scripts/SamMaps_git/'
    dirname = "/projects/SamMaps/"
else:
    raise ValueError("Unknown custom path to 'SamMaps' for this system...")
sys.path.append(SamMaps_dir+'/scripts/lib/')

from nomenclature import exists_file

from segmentation_pipeline import seg_pipe
from segmentation_pipeline import read_image
from segmentation_pipeline import segmentation_fname

# - DEFAULT variables:
# Microscope orientation:
DEF_ORIENT = -1  # '-1' == inverted microscope!
# Minimal volume threshold for cells, used to avoid too small cell from seed over-detection
DEF_MIN_VOL = 20.
# Background value: (not handled by parser)
back_id = 1
# Default smoothing factor for Gaussian smoothing (linear_filtering):
DEF_STD_DEV = 1.0

# PARAMETERS:
# -----------
parser = argparse.ArgumentParser(description='Segmentation of single channel files.')
# positional arguments:
parser.add_argument('scf', type=str,
                    help="filename of the -single channel- intensity image to segment.")
parser.add_argument('h_min', type=int,
                    help="value to use for minimal h-transform extraction.")
# optional arguments:
parser.add_argument('--microscope_orientation', type=int, default=DEF_ORIENT,
                    help="orientation of the microscope (i.e. set '-1' when using an inverted microscope), '{}' by default".format(DEF_ORIENT))
parser.add_argument('--std_dev', type=float, default=DEF_STD_DEV,
                    help="standard deviation used for Gaussian smoothing, '{}' by default".format(DEF_STD_DEV))
parser.add_argument('--min_cell_volume', type=float, default=DEF_MIN_VOL,
                    help="minimal volume accepted for a cell, '{}' by default".format(DEF_MIN_VOL))
parser.add_argument('--substract_inr', type=str, default="",
                    help="if specified, substract this INR from the 'inr' before segmentation, None by default")
parser.add_argument('--output_fname', type=str, default="",
                    help="if specified, the filename of the labbeled image, by default automatic naming contains some infos about the procedure")
parser.add_argument('--output_path', type=str, default="",
                    help="if specified, change the segmentation file path (MUST EXISTS!)")

parser.add_argument('--iso', action='store_true',
                    help="if given, performs resampling to isometric voxelsize before segmentation, 'False' by default")
parser.add_argument('--equalize', action='store_true',
                    help="if given, performs adaptative equalization of the intensity image to segment, 'False' by default")
parser.add_argument('--stretch', action='store_true',
                    help="if given, performs contrast strectching of the intensity image to segment, 'False' by default")
parser.add_argument('--force', action='store_true',
                    help="if given, force computation of labelled image even if it already exists, 'False' by default")

args = parser.parse_args()

# - Variables definition from argument parsing:
scf_name = args.scf
exists_file(scf_name)
h_min = args.h_min
# - Variables definition from optional arguments:
substract_inr = args.substract_inr
if substract_inr != "":
    exists_file(substract_inr)
    print "Will performs image substraction before segmentation:\n - ref_im = {}\n - sub_im = {}".format(scf_name, substract_inr)

min_cell_volume = args.min_cell_volume
try:
    assert min_cell_volume >= 0.
except:
    raise ValueError("Negative minimal volume!")

std_dev = args.std_dev
iso = args.iso
equalize = args.equalize
stretch = args.stretch
output_fname =  args.output_fname
output_path =  args.output_path

force =  args.force
if force:
    print "WARNING: any existing segmentation image will be overwritten!"
else:
    print "Existing segmentation will be kept!"

if output_fname:
    seg_img_fname = output_fname
else:
    seg_img_fname = segmentation_fname(scf_name, h_min, iso, equalize, stretch)

if output_path:
    assert exists(output_path)
    seg_img_fname = join(output_path, split(seg_img_fname)[1])

if exists(seg_img_fname) and not force:
    print "Found existing segmentation file: {}".format(seg_img_fname)
    print "ABORT!"
else:
    im2seg = read_image(scf_name)
    if substract_inr != "":
        im2sub = read_image(substract_inr)
    else:
        im2sub = None
    seg_im = seg_pipe(im2seg, h_min, im2sub, iso, equalize, stretch, std_dev, min_cell_volume, back_id)
    print "\n - Saving segmentation under '{}'".format(seg_img_fname)
    imsave(seg_img_fname, seg_im)

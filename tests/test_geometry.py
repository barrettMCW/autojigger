"""pytest module"""

import nibabel as nib
import numpy as np
import pyvista as pv

import autojigger.autojigger as aj

test_nifti = "n/brain_mask_115.nii.gz"
organ_profile = "brain"
profile = aj.load_profile("src/autojigger/profiles.json", organ_profile)
mold = aj.prep_mold(test_nifti, profile)

def test_mold_geom():
    global profile

    nifti_bounds = aj.get_organ_bounds(test_nifti)

    mold_bounds = mold.bounds
    print(mold_bounds)
    print(nifti_bounds)
    # assert length, width, height of mold are at least as large as NIfTI
    assert mold_bounds[1] - mold_bounds[0] >= nifti_bounds[0]
    assert mold_bounds[3] - mold_bounds[2] >= nifti_bounds[1]
    assert mold_bounds[5] - mold_bounds[4] >= nifti_bounds[2]


def test_jig_dimensions():
    pass
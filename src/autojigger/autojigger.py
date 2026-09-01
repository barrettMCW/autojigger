import argparse
import json
import logging
import math
import os
import time
from typing import Any

import nibabel as nib
import numpy as np
import pymeshfix as mf
import pyvista as pv
import vtk
import yaml

# Uses VTK to process NIfTI because lazy evaluation pipeline is much faster,
# then uses PyVista to simplify jig generation and use manifold operations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def log_time_taken(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        logger.info(
            f"Function {func.__name__} took {end_time - start_time:.2f} seconds to complete."
        )
        return result

    return wrapper


def load_profile(profile_path: str, profile_key: str) -> dict[str, Any]:
    wd = os.path.dirname(os.path.abspath(__file__))
    file_path = profile_path if profile_path else f"{wd}/profiles.json"

    if file_path.endswith(".json"):
        with open(file_path) as f:
            profiles = json.load(f)
    elif file_path.endswith(".yaml") or file_path.endswith(".yml"):
        with open(file_path) as f:
            profiles = yaml.safe_load(f)

    if profile_key not in profiles:
        raise KeyError(f"Profile '{profile_key}' not found in the file.")
    profile = profiles[profile_key]
    if "organ_profile" in profile or "knife_profile" in profile:
        return {
            **profile.get("organ_profile", {}),
            "knife_height": 20,
            "pre_knife_factor": 1.5,
            "post_knife_factor": 3,
            **profile.get("knife_profile", {}),
        }
    return profile


def create_vtk_obj(obj_class, connect_port=None):
    obj_instance = obj_class()
    if connect_port is not None:
        obj_instance.SetInputConnection(connect_port)
    return obj_instance


def new_reader(nifti_path):
    reader = create_vtk_obj(vtk.vtkNIFTIImageReader, None)
    reader.SetFileName(nifti_path)
    reader.Update()
    return reader


def new_surface_extractor(connect_port, label: int = 1):
    surf = create_vtk_obj(vtk.vtkDiscreteMarchingCubes, connect_port)
    surf.SetValue(0, int(label))
    surf.Update()
    return surf


def new_smoother(connect_port, iterations: int = 10000):
    smoother = create_vtk_obj(vtk.vtkWindowedSincPolyDataFilter, connect_port)
    smoother.SetNumberOfIterations(iterations)
    smoother.SetPassBand(0.01)
    smoother.NormalizeCoordinatesOn()
    smoother.Update()
    return smoother


def new_decimator(connect_port, target_reduction: float = 0.97):
    decimate = create_vtk_obj(vtk.vtkDecimatePro, connect_port)
    decimate.SetTargetReduction(target_reduction)
    decimate.Update()
    return decimate


def new_scaler(connect_port, scale: tuple[int, int, int]):
    set_scaler = vtk.vtkTransform()
    set_scaler.Scale(scale)
    scaler = create_vtk_obj(vtk.vtkTransformPolyDataFilter, connect_port)
    scaler.SetTransform(set_scaler)
    scaler.Update()
    return scaler


def new_translator(connect_port, translation):
    translation_transform = vtk.vtkTransform()
    translation_transform.Translate(translation)
    translation_filter = create_vtk_obj(vtk.vtkTransformPolyDataFilter, connect_port)
    translation_filter.SetTransform(translation_transform)
    translation_filter.Update()
    return translation_filter


def new_rotator(connect_port, rotate_z):
    rotate_transform = vtk.vtkTransform()
    rotate_transform.RotateZ(rotate_z)
    rotate_filter = create_vtk_obj(vtk.vtkTransformPolyDataFilter, connect_port)
    rotate_filter.SetTransform(rotate_transform)
    rotate_filter.Update()
    return rotate_filter


def new_connector(connect_port):
    connector = create_vtk_obj(vtk.vtkConnectivityFilter, connect_port)
    connector.SetExtractionModeToLargestRegion()
    connector.Update()
    return connector


def get_origin_translation(bounds: tuple) -> tuple:
    """Calculates the translation needed to center the polydata based on its boundaries

    Args:
        final_mold_bounds: Tuple containing the boundaries of the polydata.
            (xmin, xmax, ymin, ymax, zmin, zmax)

    Returns:
        Translation vector to move the object to 0,0,0.
    """
    center_x = (bounds[0] + bounds[1]) / 2
    center_y = (bounds[2] + bounds[3]) / 2
    center_z = (bounds[4] + bounds[5]) / 2
    translation = (-center_x, -center_y, -center_z)
    return translation


def get_organ_bounds_voxels(nifti: nib.nifti1.Nifti1Image, label: int) -> tuple:
    """Finds length, width, and height in voxels of the bounding box of the organ.

    Helper function for get_organ_bounds; also used to find the number of MRI slices.

    Args:
        nifti: nibabel image object of the NIfTI.
        label: Surface index of organ to get size of.

    Returns:
        Tuple of (length, width, height) in voxels of the bounding box of the organ.
    """
    nifti_data = nifti.get_fdata()
    organ_coords = np.argwhere(nifti_data == label)
    min_vals = organ_coords.min(axis=0)
    max_vals = organ_coords.max(axis=0)
    dims = (max_vals - min_vals) + 1 # add one: inclusive from min index to max index
    return dims


def get_organ_bounds_mm(nifti: nib.nifti1.Nifti1Image, label: int = 1) -> tuple:
    """Finds length, width, and height in mm of bounding box from the NIfTI.

    Args:
        nifti_path: Filepath of NIfTI to use.
        label: Surface index of organ to get size of.

    Returns:
        Tuple of (length, width, height) in mm of the bounding box of the organ.
    """
    dims_voxel = get_organ_bounds_voxels(nifti, label)
    # convert to mm
    nifti_pixdim = nifti.header["pixdim"]
    nifti_bounds = [
        dims_voxel[0] * nifti_pixdim[1],
        dims_voxel[1] * nifti_pixdim[2],
        dims_voxel[2] * nifti_pixdim[3]
    ]
    return nifti_bounds


def get_restoring_scale(mold_bounds: vtk.vtkAlgorithmOutput, organ_bounds: tuple):
    """Finds scale tuple (x, y, z) to revert smoothed mold back to original size.

    Args:
        mold_bounds: Bounds (xmin, xmax, ymin, ..., zmax) of the smoothed mold.
        mold_port: 
        organ_bounds: (length, width, height) of bounding box of organ from NIfTI.

    Returns:
        x, y, z scaling to restore mesh to original size from before smoothing.
    """
    #mold_port.GetProducer().Update()
    #mold_bounds = mold_port.GetProducer().GetOutputDataObject(0).GetBounds()
    scale = (
        organ_bounds[0] / (mold_bounds[1] - mold_bounds[0]),
        organ_bounds[1] / (mold_bounds[3] - mold_bounds[2]),
        organ_bounds[2] / (mold_bounds[5] - mold_bounds[4]),
    )
    return scale


@log_time_taken
def prep_mold(nifti_path: str, profile: dict) -> vtk.vtkPolyData:
    """Generates a transformed VTK mesh of an organ from a NIfTI.
    
    Args:
        nifti_path: Filepath to NIfTI path with organ mask to use.
        profile: Dictionary of mold configurations (see README).
    
    Returns:
        Finalized VTK mesh of the mold.
    """
    rotate_for_laterality(profile)
    reader = new_reader(nifti_path)
    surf = new_surface_extractor(reader.GetOutputPort(), profile["surface_label"])
    smoother = new_smoother(surf.GetOutputPort(), profile["mold_smoothing"])
    decimate = new_decimator(smoother.GetOutputPort(), profile["mold_decimation"])
    mold_bounds = decimate.GetOutput().GetBounds()
    nifti = nib.load(nifti_path)
    organ_bounds = get_organ_bounds_mm(nifti)
    restoring_scale = get_restoring_scale(mold_bounds, organ_bounds)
    final_scale = tuple(profile["scale"] * np.array(restoring_scale))
    scaler = new_scaler(decimate.GetOutputPort(), final_scale)
    rotator = new_rotator(scaler.GetOutputPort(), profile["rotate_z"])
    mold_poly = rotator.GetOutput()
    mold_bounds = mold_poly.GetBounds()
    translation = get_origin_translation(mold_bounds)
    translator = new_translator(rotator.GetOutputPort(), translation)
    mold_poly = translator.GetOutput()
    return mold_poly


def get_slice_thickness(nifti_path: str) -> float:
    """Gets the thickness of slices in mm from the NIfTI slices for use in the jig.

    Args:
        nifti_path: Filepath of NIfTI to use.

    Returns:
        MRI slice size in mm.
    """
    nifti = nib.load(nifti_path)
    slice_thickness = np.round(nifti.header["pixdim"][3], 3)
    if slice_thickness <= 0: 
        # But, if no slices for some reason, slice thickness is 1 
        raise ValueError("Invalid slice thickness")
    return slice_thickness


def get_jig_bounds(profile: dict, mold_bounds: tuple, slice_thickness: float) -> tuple:
    """Applies modifiers from profile to mold bounds to calculate jig bounds.

    Args:
        profile: profile configuration with x, y, and z margins.
        mold_bounds: tuple of bounds of mold mesh (xmin, xmax, ymin, ..., zmax).
        slice_thickness: size of MRI slices in mm.

    Returns:
        6-tuple of jig bounds (xmin, xmax, ymin, ..., zmax)
    """
    jig_modifiers = (
        -profile["x_wall"],
        profile["x_wall"],
        -(profile["y_wall"] + profile["post_knife_factor"] * profile["knife_height"]),
        profile["y_wall"] + profile["pre_knife_factor"] * profile["knife_height"],
        -(slice_thickness + profile["z_wall"]),
        (slice_thickness + profile["z_wall"]),
    )
    jig_bounds = (
        mold_bounds[0] + jig_modifiers[0],
        mold_bounds[1] + jig_modifiers[1],
        mold_bounds[2] + jig_modifiers[2],
        mold_bounds[3] + jig_modifiers[3],
        mold_bounds[4] + jig_modifiers[4],
        mold_bounds[5] + jig_modifiers[5],
    )
    return jig_bounds


def get_clean_mesh(vtkmesh: vtk.vtkPolyData) -> pv.PolyData:
    """Use meshfix to get and return a clean pyvista mesh, smoothing manifold errors.

    Args:
        vtkmesh: vtkPolyData to wrap and clean.

    Returns:
        Cleaned pyvista mesh.
    """
    wrapped_mesh = pv.wrap(vtkmesh)
    meshfix = mf.MeshFix(wrapped_mesh)
    meshfix.repair()
    return meshfix.mesh


def get_slicer_bounds(profile: dict, jig_bounds: tuple, mold_bounds: tuple) -> tuple:
    """Calculate slicer (knife hole) bounds from the jig bounds and the configuration profile.

    Args:
        profile: configuration profile containing x, y margins and knife width.
        jig_bounds: bounding box of the jig (xmin, xmax, ymin, ..., zmax)
        mold_bounds: bounding box of the mold.

    Returns:
        6-tuple bounding box of the slicer,
        the rectangle that is iteratively cut out of the jig.
        ymin is the starting y for the slicer (the first cut).
    """
    # Edge of MRI slice should be halfway into the knife width (slicing_z)

    slicer_z_start = mold_bounds[4] - (profile["knife_width"] / 2)
    slicer_bounds = (
        jig_bounds[0] - profile["x_wall"],  # extend past x wall (to cut through),
        jig_bounds[1] + profile["x_wall"],
        jig_bounds[2] + profile["y_wall"],  # only cut inside y wall,
        jig_bounds[3] - profile["y_wall"],
        slicer_z_start,
        slicer_z_start + profile["knife_width"],
    )
    return slicer_bounds


@log_time_taken
def prep_comp_mold(
    mold: pv.PolyData, jig_bounds: tuple, jig_offset: int, steps: int, iterations: int
) -> pv.PolyData:
    """Generates a composite mold that can be cut out of the jig once.

    The composite mold is stepped forward [steps] times, and moves out of the jig
    in the positive y direction based on the length of the jig.
    A composite mold is used rather than iteratively cutting the mold out of the jig
    because the composite mold can be smoothed, whereas stepped cuts make the inside
    of the jig jagged. This smoothing does not significantly benefit 3D print time.
    A high number of smoothing iterations (>70 or so ) can cause manifold issues.

    Args:
        mold: pyvista mesh of the mold.
        jig_bounds: Bounding box of the jig (xmin, xmax, ymin, ..., zmax).
        jig_offset: Length in mm to move the mold out of the jig before starting to cut.
        steps: Number of times to step mold forward to join together. Higher number creates
               smoother, more accurate interior of jig but can run much longer.
        iterations: Number of smoothing iterations for the final composite mold.

    Returns: pyvista mesh of the composite mold, in position to be cut out of jig.
    """
    y_min = jig_bounds[2]
    y_max = jig_bounds[3]
    step_size = (y_max - y_min) / steps

    mold.translate([0, jig_offset, 0], inplace=True)
    comp_mold = mold.copy()
    for _i in range(steps):
        mold.translate([0, step_size, 0], inplace=True)
        comp_mold = comp_mold.manifold.union(mold)

    comp_mold_smooth = comp_mold.smooth_taubin(n_iter=iterations, pass_band=0.1)
    return comp_mold_smooth


@log_time_taken
def assemble_jig(comp_mold: pv.PolyData, jig_bounds: tuple) -> pv.PolyData:
    """Cuts the composite mold out of a jig box to create a jig mold.

    Args:
        comp_mold: Mesh of the composite mold to cut out of jig.
        jig_bounds: Bounding box (xmin, xmax, ymin, ..., zmax) of the jig.
    
    Returns: pyvista mesh of the jig mold before slices.
    """
    jig = pv.Cube(bounds=jig_bounds)
    jig = jig.manifold.difference(comp_mold)
    return jig


@log_time_taken
def slice_jig(jig: pv.PolyData, slice_thickness: float, slicer_bounds: tuple, 
              num_slices: int, z_wall: int) -> pv.PolyData:
    """Slices through a jig mesh to create knife holes.

    Slices start at the z coordinate of the first MRI slice,
    and continue for the number of actual MRI slices.

    The knife width and the space before the next slice should sum up to the MRI slice thickness,
    so slicer cuts out knife width and translates up (slice_thickness).
    The filled "gaps" between cuts are thus (slice_thickness - slicing_z) tall.

    Args:
        jig: Mesh of jig to slice.
        slice_thickness: z-height of MRI slices. 
        slicer_bounds: Bounding box (xmin, xmax, ymin, ..., zmax) of the slicer.
        num_slices: Number of MRI slices.
        z_wall: Size of margin on bottom and top of jig to not be cut.
    """
    slicer = pv.Cube(bounds=slicer_bounds)
    for _i in range(num_slices + 1):
        if slicer.bounds[5] > jig.bounds[5] - z_wall:
            logger.warning("Warning: Number of slices cut off by z_wall margin")
            break
        jig = jig.manifold.difference(slicer)
        slicer.translate([0, 0, slice_thickness], inplace=True)
    return jig


def check_stl_path(stl_path: str) -> str:
    """Given STL filepaths, verifies they are writeable and end in .stl.

    Args:
        stl_path: STL filepath to check.

    Returns:
        Valid(ated) STL path.

    Raises:
        ValueError: If the filepath is in a nonexistent directory or cannot be written. 
    """
    dirname = os.path.dirname(stl_path)
    if dirname == "":
        dirname = "."
    if not (os.path.exists(dirname) and os.access(dirname, os.W_OK)):
        raise ValueError("Cannot write to path " + stl_path)
    if not stl_path.lower().endswith(".stl"):
        stl_path += ".stl"
    return stl_path


def rotate_for_laterality(profile: dict):
    """Modifies the rotation in profile given the tumor laterality.

    Default rotation assumes the tumor on the left;
    if the tumor is on the right, adds 180 degrees to the Z rotation.

    Configuration may be clearer if this is removed and rotation is kept to the 
    rotation parameter.

    Args:
        profile: profile configuration to use, with rotate_z and tumor_laterality.
    """
    if "tumor_laterality" in profile and profile["tumor_laterality"] == "R":
        profile["rotate_z"] += 180


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process NIfTI file and output STLs.")
    parser.add_argument(
        "-i",
        "--nifti_path",
        required=True,
        type=str,
        help="Path to the input NIfTI file.",
    )
    parser.add_argument(
        "-m",
        "--mold_path",
        type=str,
        default=None,
        help="Path to the output STL file for the mold (optional).",
    )
    parser.add_argument(
        "-o",
        "--jig_path",
        required=True,
        type=str,
        help="Path to the output STL file for the jig.",
    )
    parser.add_argument(
        "-p",
        "--profile",
        required=True,
        help="Profile key to use for processing. Defaults to prostate.",
    )
    parser.add_argument(
        "-j",
        "--profile_path",
        type=str,
        help="Path to json, yaml, or python file containing custom profile to use (optional)",
    )
    return parser.parse_args()


def main(args):
    # Load in from files
    nifti_path = args.nifti_path
    nifti = nib.load(nifti_path)
    mold_path = check_stl_path(args.mold_path) if args.mold_path else None
    jig_path = check_stl_path(args.jig_path)
    profile = load_profile(args.profile_path, args.profile)

    # Create organ mold with VTK
    mold_poly = prep_mold(nifti_path, profile)
    mold = get_clean_mesh(mold_poly)
    if mold_path:
        mold.save(mold_path)

    # Calculate jig and slicer sizes
    # number of voxels on Z axis in the organ is the number of slices
    num_slices = get_organ_bounds_voxels(nifti, profile["surface_label"])[2]
    slice_thickness = get_slice_thickness(nifti_path)
    if profile["min_slice_thickness"] > 0:
        # if slice thickness is too small, find smallest multiplier to meet the minimum.
        # Number of slices is then divided by that multiplier..
        multiplier = math.ceil(profile["min_slice_thickness"] / slice_thickness)
        slice_thickness *= multiplier
        num_slices = num_slices // multiplier
    jig_bounds = get_jig_bounds(profile, mold.bounds, slice_thickness)
    slicer_bounds = get_slicer_bounds(profile, jig_bounds, mold.bounds)

    # Create composite extended mold, cut it out of jig
    comp_mold = prep_comp_mold(
        mold,
        jig_bounds,
        profile["jig_offset"],
        profile["jig_steps"],
        profile["jig_smoothing"],
    )
    jig = assemble_jig(comp_mold, jig_bounds)

    # Slice jig to create knife holes, export sliced jig
    sliced_jig = slice_jig(
            jig, slice_thickness, slicer_bounds, num_slices, profile["z_wall"])
    sliced_jig.save(jig_path)


if __name__ == "__main__":
    args = parse_args()
    main(args)

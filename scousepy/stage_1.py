# Licensed under an MIT open source license - see LICENSE

"""

SCOUSE - Semi-automated multi-COmponent Universal Spectral-line fitting Engine
Copyright (c) 2016-2018 Jonathan D. Henshaw
CONTACT: henshaw@mpia.de

"""

import numpy as np
import itertools
import random
import sys

from astropy.io import fits
from astropy import units as u
from astropy.stats import median_absolute_deviation
from astropy.utils.console import ProgressBar

from .verbose_output import print_to_terminal
from .io import *

def compute_noise(scouseobject):
    """
    Estimate the typical rms noise across the map

    Parameters
    ----------
    scouseobject : Instance of the scousepy class

    Notes
    -----
    Credit: Manuel Reiner

    """

    keep = scouseobject.cube.mask.include().any(axis=0)

    finiteidxs = np.array(np.where(keep))
    flatidxs = [np.ravel_multi_index(finiteidxs[:,i], \
                scouseobject.cube.shape[1:]) for i in range(len(finiteidxs[0,:]))]
    random_indices = random.sample(list(flatidxs), k=len(flatidxs))
    locations = np.array(np.unravel_index(random_indices, \
                                                   scouseobject.cube.shape[1:]))

    if len(locations[0,:]) > 500.0:
        stop = 500.0
    else:
        stop = len(locations[0,:])

    rmsList = []
    stopcount = 0
    specidx = 0
    while stopcount < stop:

        _spectrum = scouseobject.cube[:, locations[0, specidx],
                                                    locations[1, specidx]].value
        if not np.any(np.isfinite(_spectrum)):
            continue

        _spectrum = _spectrum[np.isfinite(_spectrum)]

        rmsVal = calc_rms(_spectrum[~np.isnan(_spectrum)])
        rmsList.append(rmsVal)
        stopcount+=1
        specidx+=1

    rms = np.median(rmsList)

    return rms

def calc_rms(spectrum):
    """
    Returns the spectral rms

    Parameters
    ----------
    Spectrum : spectral cube spectrum
        An individual spectrum taken from the spectral cube

    """

    # Find all negative values
    negative_indices = (spectrum < 0.0)

    if negative_indices.sum() < 2:
        # spectrum is not continuum subtracted, maybe?
        # first baseline-subtract the spectrum conservatively
        # (note that this is a reassignment operation, it doesn't change the
        # data)
        spectrum = spectrum - np.percentile(spectrum, 25)
        negative_indices = (spectrum < 0.0)
        assert negative_indices.sum() >= 2

    spectrum_negative_values = spectrum[negative_indices]
    reflected_noise = np.concatenate((spectrum[negative_indices],
                                               abs(spectrum[negative_indices])))
    # Compute the median absolute deviation
    MAD = median_absolute_deviation(reflected_noise)
    # For pure noise you should have roughly half the spectrum negative. If
    # it isn't then you need to be a bit more conservative
    if len(spectrum_negative_values) < 0.47*len(spectrum):
        maximum_value = 3.5*MAD
    else:
        maximum_value = 4.0*MAD
    noise = spectrum[spectrum < abs(maximum_value)]
    rms = np.sqrt(np.sum(noise**2) / np.size(noise))

    if np.isnan(rms):
        raise ValueError("RMS was NaN, which is not allowed.")

    return rms

def get_x_axis(scouseobject):
    """
    Returns x_axis for spectra

    Parameters
    ----------
    scouseobject : Instance of the scousepy class

    """
    x = np.array(scouseobject.cube.world[:,0,0][0])
    if (scouseobject.ppv_vol[0] is not None) & (scouseobject.ppv_vol[1] is not None):
        trimids = ((x>scouseobject.ppv_vol[0])&(x<scouseobject.ppv_vol[1]))
    else:
        trimids = np.ones(np.shape(x), dtype=bool)
    xtrim = x[trimids]
    return x, xtrim, trimids

def get_moments(scouseobject, write_moments, dir, filename, verbose):
    """
    Create moment maps

    Parameters
    ----------
    scouseobject : Instance of the scousepy class
    write_moments : bool
        if True scouse will output the moments as fits files
    dir : string
        Output directory for moment files
    filename : string
        output file name for moment files (scousepy will add suffix relating to
        the different moments)
    verbose : bool
        verbose output

    """

    if verbose:
        progress_bar = print_to_terminal(stage='s1', step='moments')

    # If upper and lower limits are imposed on the velocity range
    if (scouseobject.ppv_vol[0] is not None) & (scouseobject.ppv_vol[1] is not None):
        momzero = scouseobject.cube.with_mask(scouseobject.cube > u.Quantity(
            scouseobject.mask_below,
            scouseobject.cube.unit)).spectral_slab(scouseobject.ppv_vol[0]*u.km/u.s,
            scouseobject.ppv_vol[1]*u.km/u.s).moment0(axis=0)
        momone = scouseobject.cube.with_mask(scouseobject.cube > u.Quantity(
            scouseobject.mask_below,
            scouseobject.cube.unit)).spectral_slab(scouseobject.ppv_vol[0]*u.km/u.s,
            scouseobject.ppv_vol[1]*u.km/u.s).moment1(axis=0)
        momtwo = scouseobject.cube.with_mask(scouseobject.cube > u.Quantity(
            scouseobject.mask_below,
            scouseobject.cube.unit)).spectral_slab(scouseobject.ppv_vol[0]*u.km/u.s,
            scouseobject.ppv_vol[1]*u.km/u.s).linewidth_sigma()

        slab = scouseobject.cube.spectral_slab(scouseobject.ppv_vol[0]*u.km/u.s,
                                               scouseobject.ppv_vol[1]*u.km/u.s)
        maskslab = scouseobject.cube.with_mask(scouseobject.cube > u.Quantity(
            scouseobject.mask_below,
            scouseobject.cube.unit)).spectral_slab(scouseobject.ppv_vol[0]*u.km/u.s,
            scouseobject.ppv_vol[1]*u.km/u.s)

        # Momnine follows CASAs naming system. I'm not sure why I did this - its
        # not really a moment but oh well
        momnine = np.empty(np.shape(momone))
        momnine.fill(np.nan)
        slabarr = np.copy(slab.unmasked_data[:].value)
        idnan = (~np.isfinite(slabarr))
        negative_inf = -1e10
        slabarr[idnan] = negative_inf
        idxmax = np.nanargmax(slabarr, axis=0)
        momnine = slab.spectral_axis[idxmax].value
        momnine[~maskslab.mask.include().any(axis=0)] = np.nan
        idnan = (np.isfinite(momtwo.value)==0)
        momnine[idnan] = np.nan
        momnine = momnine * u.km/u.s

    # If no velocity limits are imposed
    else:
        momzero = scouseobject.cube.with_mask(scouseobject.cube > u.Quantity(
            scouseobject.mask_below, scouseobject.cube.unit)).moment0(axis=0)
        momone = scouseobject.cube.with_mask(scouseobject.cube > u.Quantity(
            scouseobject.mask_below, scouseobject.cube.unit)).moment1(axis=0)
        momtwo = scouseobject.cube.with_mask(scouseobject.cube > u.Quantity(
            scouseobject.mask_below, scouseobject.cube.unit)).linewidth_sigma()
        slab = scouseobject.cube
        maskslab = scouseobject.cube.with_mask(scouseobject.cube > u.Quantity(
            scouseobject.mask_below, scouseobject.cube.unit))

        momnine = np.empty(np.shape(momone))
        momnine.fill(np.nan)
        slabarr = np.copy(slab.unmasked_data[:].value)
        idnan = (~np.isfinite(slabarr))
        negative_inf = -1e10
        slabarr[idnan] = negative_inf
        idxmax = np.nanargmax(slabarr, axis=0)
        momnine = slab.spectral_axis[idxmax].value
        momnine[~maskslab.mask.include().any(axis=0)] = np.nan
        idnan = (np.isfinite(momtwo.value)==0)
        momnine[idnan] = np.nan
        momnine = momnine * u.km/u.s

    # Write moments
    if write_moments:
        output_moments(momzero, momone, momtwo, momnine, dir, filename)

    return momzero, momone, momtwo, momnine

def get_coverage(momzero, spacing):
    """
    Returns the central locations of SAAs

    Parameters
    ----------
    momzero : ndarray
        moment zero (integrated intensity) map
    spacing : float
        spacing between the centres of SAAs

    """

    # Get the indices of the cols and rows in the momzero map where there is
    # data
    cols, rows = np.where(momzero != 0.0)

    # This sets the maximum extent of the coverage
    rangex = [np.min(rows), np.max(rows)]
    sizex = np.abs(np.min(rows)-np.max(rows))
    rangey = [np.min(cols), np.max(cols)]
    sizey = np.abs(np.min(cols)-np.max(cols))

    # Here we define the total number of positions in x and y for the coverage
    nposx = int((sizex/(spacing))+1.0)
    nposy = int((sizey/(spacing))+1.0)

    # This defines the coverage coordinates
    cov_x = np.max(rangex)-(spacing)*np.arange(nposx)
    cov_y = np.min(rangey)+(spacing)*np.arange(nposy)

    return cov_y, cov_x

def define_coverage(cube, momzero, momzero_mod, wsaa, nrefine, verbose, \
                    redefine=False):
    """
    Returns locations of SAAs and computes a spatially-averaged spectrum.

    Parameters
    ----------
    cube : spectral cube
        cube output from spectral cube
    momzero : ndarray
        moment zero (integrated intensity) map
    momzero_mod : ndarray
        modified moment zero map. Used for variable coverage where masking is
        applied
    wsaa : number
        The width of a spectral averaging area in pixels. Note this has
        been updated from the IDL implementation where it previously used a
        half-width (denoted rsaa). Can provide multiple values in a list
        as an alternative to the refine_grid option (see below).
    nrefine : number
        Number of refinement steps for the saas
    verbose : bool
        verbose output
    redefine : bool
        refine grid (default=False)

    """

    # Coverage boxes are spaced by a half-width
    spacing = wsaa/2.
    # Get the coverage coordinates
    cov_y, cov_x = get_coverage(momzero, spacing)

    # maximum number of spectra contained within a coverage box. Increase the
    # size by 1.5 just due to a silly indexing problem
    maxspecinsaa = int((wsaa*1.5)**2)
    # Generate empty arrays which will contain the coverage information
    coverage = np.full([len(cov_y)*len(cov_x),2], np.nan) # coordinates
    spec = np.full([cube.shape[0], len(cov_y), len(cov_x)], np.nan) # spectra
    ids = np.full([len(cov_y)*len(cov_x), maxspecinsaa, 2], np.nan) # the IDs
    frac = np.full([len(cov_y)*len(cov_x)], np.nan) # the fraction of sig data

    count= 0.0
    if not redefine:
        if verbose:
            progress_bar = print_to_terminal(stage='s1', step='coverage',
                                                length=len(cov_y)*len(cov_x))

    # Loop through the coords
    for cx,cy in itertools.product(cov_x, cov_y):
        coverage, spec, ids, frac = update_coverage(cube, cx, cy, spacing,
                                                    momzero, momzero_mod,
                                                    cov_x, cov_y, coverage,
                                                    spec, ids, frac,
                                                    redefine, nrefine)
        if not redefine:
            if verbose:
                progress_bar.update()

    if verbose:
        print('')

    return coverage, spec, ids, frac

def update_coverage(cube, cx, cy, spacing, momzero, momzero_mod, cov_x, cov_y,
                                  coverage, spec, ids, frac, redefine, nrefine):
    """
    Where the coverage is computed

    Parameters
    ----------
    cube : spectral cube
        cube output from spectral cube
    cx, cy : ndarray
        indices of the coverage coordinates
    spacing : float
        spacing between the centres of SAAs
    momzero : ndarray
        moment zero (integrated intensity) map
    momzero_mod : ndarray
        modified moment zero map. Used for variable coverage where masking is
        applied
    cov_x, cov_y : ndarray
        central locations of the SAAs
    coverage : ndarray
        empty array which will house the coverage info
    spec : ndarray
        empty array which will house spatially averaged spectra
    ids : ndarray
        empty array which will house the coverage ids
    frac : ndarray
        empty array defining the number of significant pixels within the SAA
    redefine : bool
        refine grid (default=False)
    nrefine : number
        Number of refinement steps for the saas

    """

    # identify the pixel limits - i.e. those pixels which are contained in
    # the coverage box
    limx = [int(cx-spacing), int(cx+spacing)]
    limy = [int(cy-spacing), int(cy+spacing)]
    limx = [lim if (lim > 0) else 0 for lim in limx ]
    limx = [lim if (lim < np.shape(momzero)[1]-1) else
                                        np.shape(momzero)[1]-1 for lim in limx ]
    limy = [lim if (lim > 0) else 0 for lim in limy ]
    limy = [lim if (lim < np.shape(momzero)[0]-1) else
                                        np.shape(momzero)[0]-1 for lim in limy ]

    # Take a cut out of the momzero map - all pixels contained within the
    # box
    momzero_cutout = momzero_mod[min(limy):max(limy),
                                 min(limx):max(limx)]
    # Do this for the cube as well
    cube_cutout = cube[:,min(limy):max(limy), min(limx):max(limx)]

    # Identify the locations of the non nan pixels contained within the
    # cut out
    #finite = np.isfinite(momzero_cutout)
    #nmask = np.count_nonzero(finite)
    nmask = np.size(momzero_cutout)

    # range for looping (used below)
    rangex = range(min(limx), max(limx)+1)
    rangey = range(min(limy), max(limy)+1)

    # These ids refer to the coverage itself
    idx = int((cov_x[0]-cx)/(spacing))
    idy = int((cy-cov_y[0])/(spacing))

    # If we have significant data in the box here we want to generate
    # the average spectrum associated with that box.
    if nmask > 0:
        # Count the total of non zero values
        tot_non_zero = np.count_nonzero(np.isfinite(momzero_cutout) &
                                                            (momzero_cutout!=0))
        # get the fration of non zero values
        fraction = tot_non_zero / nmask

        # This is a little bit empirical for the refined coverage, in
        # general we want to ignore boxes with < 50% of non zero values.
        # However, this needs tweaking a bit for the redefined coverage.
        # This works for now but may need updating to something a bit more
        # robust in the future.
        if redefine:
            lim = 0.6/nrefine
        else:
            lim = 0.35

        # If we want to keep the box...
        if fraction >= lim:
            # ...then add the fraction and box location to the empty arrays
            frac[idy+(idx*len(cov_y))] = fraction
            coverage[idy+(idx*len(cov_y)),:] = cy,cx

            # When redefining the coverage we don't want to create expensive
            # arrays the whole time - we just want to know where we are to
            # fit. This logic is explained better in scouse.py stage_1
            if not redefine:
                # add the spectrum
                spec[:, idy, idx] = cube_cutout.mean(axis=(1,2))
            count=0

            # add the IDs
            for i in rangex:
                for j in rangey:
                    ids[idy+(idx*len(cov_y)), count, 0],\
                    ids[idy+(idx*len(cov_y)), count, 1] = j, i
                    count+=1

    return coverage, spec, ids, frac

def get_wsaa(scouseobject):
    """
    returns a new SAA size

    Parameters
    ----------
    scouseobject : Instance of the scousepy class

    """
    wsaa = []
    for i in range(1, int(scouseobject.nrefine)+1):
        newwsaa = scouseobject.wsaa[0]/i
        if newwsaa > 0.5:
            wsaa.append(newwsaa)
    return wsaa

def get_random_saa(cc, samplesize, w, verbose=False):
    """
    Get a randomly selected sample of spectral averaging areas

    Parameters
    ----------
    cc : ndarray
        array containing the coverage coordinates
    samplesize : number
        number of SAAs to randomly select
    w : number
        width of the SAA
    verbose : bool
        verbose output

    """

    if verbose:
        print('')
        print("Extracting randomly sampled SAAs for training set...")

    npixpersaa = (w)**2.0
    training_set_size = npixpersaa*samplesize

    sample = np.sort(random.sample(range(0,len(cc[:,0])), samplesize))

    if verbose:
        print('Training set size = {}'.format(int(training_set_size)))
        if training_set_size < 1000.0:
            print("WARNING: Training set size {} < 1000, try increasing the "
                  "sample size (for equivalent wsaa)".format(int(training_set_size)))
        print('')

    return sample

def plot_wsaa(dict, momzero, wsaa, dir, filename):
    """
    Plot the SAA boxes

    Parameter
    ---------
    dict : dictionary
        dictionary of the SAAs
    momzero : ndarray
        moment zero (integrated intensity) map
    wsaa : number
        width of the SAAs
    dir : string
        output directory
    filename : string
        output filename

    """
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches

    fig = plt.figure(1, figsize=(10.0, 4.0))
    fig.clf()
    ax = fig.add_subplot(111)
    plt.imshow(momzero, cmap='Greys', origin='lower',
               interpolation='nearest')
    cols = ['blue', 'red', 'yellow', 'limegreen', 'cyan', 'magenta']

    for i, w in enumerate(wsaa, start=0):
        alpha = 0.1+(0.05*int(i))
        for j in range(len(dict[i].keys())):
            if dict[i][j].to_be_fit:
                ax.add_patch(patches.Rectangle(
                            (dict[i][j].coordinates[1] - w/2., \
                             dict[i][j].coordinates[0] - w/2.),\
                             w , w , facecolor=cols[i],
                             edgecolor=cols[i], lw=0.1, alpha=alpha))
                ax.add_patch(patches.Rectangle(
                            (dict[i][j].coordinates[1] - w/2., \
                             dict[i][j].coordinates[0] - w/2.),\
                             w , w , facecolor='None',
                             edgecolor=cols[i], lw=0.2, alpha=0.25))

    plt.savefig(dir+'/'+filename+'_coverage.pdf', dpi=600,bbox_inches='tight')
    plt.draw()
    plt.show()

def calculate_delta_v(scouseobject, momone, momnine):
    """
    Calculate the difference between the moment one and the velocity of the
    channel containing the peak flux

    Parameters
    ----------
    scouseobject : instance of the scousepy class
    momone : ndarray
        moment one (intensity-weighted average velocity) map
    momnine : ndarray
        map containing the velocities of channels containing the peak flux at
        each location

    """
    # Generate an empty array
    delta_v = np.empty(np.shape(momone))
    delta_v.fill(np.nan)
    delta_v = np.abs(momone.value-momnine.value)

    return delta_v

def generate_steps(scouseobject, delta_v):
    """
    Creates logarithmically spaced values

    Parameters
    ----------
    scouseobject : instance of the scousepy class
    delta_v : ndarray
        array of the delta v values computed above
    """
    median = np.nanmedian(delta_v)
    step_values = np.logspace(np.log10(median), \
                              np.log10(np.nanmax(delta_v)), \
                              scouseobject.nrefine )
    return list(step_values)

def refine_momzero(scouseobject, momzero, delta_v, minval, maxval):
    """
    Refines momzero based on upper/lower lims of delta_v

    Parameters
    ----------
    scouseobject : instance of the scousepy class
    momzero : ndarray
        moment zero (integrated intensity) map
    delta_v : ndarray
        array of the delta v values computed above
    minval : number
        lower bound of the step values determined above
    maxval : number
        upper bound of the step values determined above

    """
    mom_zero=None
    keep = ((delta_v >= minval) & (delta_v <= maxval))
    mom_zero = np.zeros(np.shape(momzero))
    mom_zero[keep] = momzero[keep]

    return mom_zero

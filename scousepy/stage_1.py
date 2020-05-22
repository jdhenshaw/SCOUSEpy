# Licensed under an MIT open source license - see LICENSE

"""

SCOUSE - Semi-automated multi-COmponent Universal Spectral-line fitting Engine
Copyright (c) 2016-2018 Jonathan D. Henshaw
CONTACT: henshaw@mpia.de

"""

import numpy as np
import sys

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

    import random

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

    rms = np.nanmedian(rmsList)

    return rms

def calc_rms(spectrum):
    """
    Returns the spectral rms

    Parameters
    ----------
    Spectrum : spectral cube spectrum
        An individual spectrum taken from the spectral cube

    """

    from astropy.stats import median_absolute_deviation

    # Find all negative values
    negative_indices = (spectrum < 0.0)
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

    return rms

def map_locations(shape):
    """
    Returns the pixel locations for all pixels in a map

    Parameters
    ----------
    shape : tuple
        (x,y) shape of the map/cube

    """
    _yy,_xx=np.meshgrid(np.arange(shape[0]),np.arange(shape[1]))
    locations=np.array([np.ravel(_xx),np.ravel(_yy)]).T

    return locations

def map_locations_unmasked(mask):
    """
    Returns the pixel locations of the unmasked data in the map

    Parameters
    ----------
    mask : ndarray
        mask mom0 data generated by the coverage

    """
    idx,idy=np.where(mask.T)
    unmaskedlocations=np.vstack((idx,idy)).T
    return unmaskedlocations

def generate_SAAs(scouseobject, coverageobject, verbose=True):
    """
    Generates the spectral averaging areas according to the parameters set in
    the coverage GUI

    Parameters
    ----------
    scouseobject : Instance of the scousepy class
    coverage object : Instance of the ScouseCoverage class

    """

    import matplotlib.patches as patches
    import matplotlib.path as path
    from .model_housing2 import saa
    from .verbose_output import print_to_terminal

    # get the locations of all pixels in the map
    maploc=map_locations((np.shape(coverageobject.moments[6])[0],np.shape(coverageobject.moments[6])[1]))

    scouseobject.lenspec=0.0
    for i, w in enumerate(coverageobject.wsaa, start=0):
        # Create individual dictionaries for each wsaa
        scouseobject.saa_dict[i] = {}
        coverage=coverageobject.coverage[i]

        if verbose:
            progress_bar = print_to_terminal(stage='s1', step='coverage',length=len(coverage[:,0]), var=w)

        for j in range(len(coverage[:,0])):
            # generate the masks
            saamask=generate_saamask(coverage[j,:],w,maploc,coverageobject.moments[6].shape)
            cubemask=generate_cubemask(scouseobject,saamask,coverageobject.moments[6])
            # mask the cube using the cubemask
            masked_saacube=scouseobject.cube.with_mask(cubemask)
            # generate the average spectrum
            saaspectrum=np.nanmean(masked_saacube.filled_data[:], axis=(1,2)).value

            if coverage[j,2]==1:
                to_be_fit=True
            else:
                to_be_fit=False

            # generate the SAA
            SAA = saa(np.array([coverage[j,0],coverage[j,1]]), saaspectrum, index=j, to_be_fit=to_be_fit, scouseobject=scouseobject)
            # Add the SAA to the dictionary
            scouseobject.saa_dict[i][j] = SAA

            # get the locations of the unmasked data
            saaspectra=np.flip(map_locations_unmasked(cubemask),axis=1)
            # add these to the SAAs
            SAA.add_indices(saaspectra, scouseobject.cube.shape[1:])
            # determine the *actual* number of spectra scouse will fit
            if SAA.to_be_fit:
                scouseobject.lenspec+=np.size(SAA.indices_flat)

            if verbose:
                progress_bar.update()


def generate_saamask(coverage, wsaa, maploc, shape):
    """
    using matplotlib to create a mask of the SAA

    Parameters
    ----------
    coverage : ndarray
        coverage coordinates
    wsaa : number
        size of the SAA
    maploc : ndarray
        an array containing the locations of all positions in the map
    shape : ndarray
        the shape of the moment map
    """
    import matplotlib.patches as patches
    import matplotlib.path as path

    # Identify the bottom left corner of the SAA.
    bl=(coverage[0]-wsaa/2., coverage[1]-wsaa/2.)
    # create a patch and obtain the path
    saapatch=patches.Rectangle(bl,wsaa,wsaa)
    # get the edge points
    verts = saapatch.get_verts()
    # create a path
    saapath = path.Path(verts,closed=True)

    # identify which locations are contained within that path.
    saaspectramask=saapath.contains_points(maploc)
    saaspectra=maploc[(saaspectramask==True)]
    return np.reshape(saaspectramask,np.flip(shape)).T

def generate_cubemask(scouseobject,saamask,momentmask):
    """
    returns a mask that can be used to mask the data cube (after trimming has
    been performed)

    Parameters
    ----------
    scouseobject : instance of the scouse class
    saamask : ndarray
        a mask indicating all pixels contained within the SAA
    momentmask : ndarray
        a mask of the moment 0 map
    """
    # final mask shape
    mask_shape=scouseobject.cube.shape[1:]
    # create arrays to hold the masks
    saamask_embedded=np.zeros(mask_shape,dtype='bool')
    momentmask_embedded=np.zeros(mask_shape,dtype='bool')
    # create the new x0 and y0 positions according to the trimming
    newx0=np.min(scouseobject.x_range)
    newy0=np.min(scouseobject.y_range)
    # now embed the previous masks inside our new mask
    momentmask_embedded[newy0:newy0+momentmask.shape[0], newx0:newx0+momentmask.shape[1]] = momentmask
    saamask_embedded[newy0:newy0+saamask.shape[0], newx0:newx0+saamask.shape[1]] = saamask
    # generate master mask
    return momentmask_embedded*saamask_embedded

def get_x_axis(scouseobject):
    """
    Returns x_axis for spectra

    Parameters
    ----------
    scouseobject : Instance of the scousepy class

    """
    x = np.array(scouseobject.cube.spectral_axis.value)

    trimids = ((x>=np.min(scouseobject.vel_range))&(x<=np.max(scouseobject.vel_range)))
    if not any(trimids):
        trimids=np.ones(np.shape(x), dtype=bool)
    xtrim = x[trimids]

    return x, xtrim, trimids

def plot_coverage(scouseobject, coverageobject, covplotfilename):
    """
    Plot the SAA boxes

    Parameter
    ---------
    scouseobject : Instance of the scousepy class
    coverage object : Instance of the ScouseCoverage class
    covplotfilename : string
        output filename

    """
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches

    fig = plt.figure(figsize=(14, 8))
    try:
        from wcsaxes import WCSAxes
        _wcaxes_imported = True
    except ImportError:
        _wcaxes_imported = False
        if coverageobject.moments[0].wcs is not None:
            warnings.warn("`WCSAxes` package required for wcs coordinate display.")

    blank_window_ax=[0.1,0.1,0.8,0.8]
    newaxis=[blank_window_ax[0]+0.03, blank_window_ax[1]+0.03, blank_window_ax[2]-0.06,blank_window_ax[3]-0.045]

    # set up the map window
    if coverageobject.moments[0].wcs is not None and _wcaxes_imported:
        ax_image = WCSAxes(fig, newaxis, wcs=coverageobject.moments[0].wcs, slices=('x','y'))
        map_window = fig.add_axes(ax_image)
        x = map_window.coords[0]
        y = map_window.coords[1]
        x.set_ticklabel(exclude_overlapping=True)
        y.set_ticklabel(rotation=90,verticalalignment='bottom', horizontalalignment='left',exclude_overlapping=True)
    else:
        map_window = fig.add_axes(newaxis)

    vmin=np.nanmin(coverageobject.moments[0].value)-0.05*np.nanmin(coverageobject.moments[0].value)
    vmax=np.nanmax(coverageobject.moments[0].value)+0.05*np.nanmax(coverageobject.moments[0].value)

    im=map_window.imshow(coverageobject.moments[0].value, cmap=plt.cm.binary_r, origin='lower',
                         interpolation='nearest', vmin=vmin,vmax=vmax)

    _colors = ['dodgerblue','indianred','springgreen','yellow','magenta','cyan']

    # Cycle through and plot the coverage
    for i in range(len(coverageobject.wsaa)):
        c=_colors[i]
        mypath=coverageobject.coverage_path[i]
        # create the patch
        saapatch = patches.PathPatch(mypath,alpha=0.4, facecolor=c, edgecolor='black')
        map_window.add_patch(saapatch)

    plt.savefig(covplotfilename, dpi=300,bbox_inches='tight')

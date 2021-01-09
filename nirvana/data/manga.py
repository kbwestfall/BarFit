"""
Module with the derived instances for MaNGA kinematics.

.. |ee|  unicode:: U+00E9
    :trim:

.. |Sersic|  replace:: S |ee| rsic

.. include common links, assuming primary doc root is up one directory
.. include:: ../include/links.rst
"""
import os
import warnings

from IPython import embed

import numpy as np
from astropy.io import fits
from glob import glob
import matplotlib.image as img

from .kinematics import Kinematics
from .fitargs import FitArgs


def channel_dictionary(hdu, ext, prefix='C'):
    """
    Construct a dictionary of the channels in a MaNGA MAPS file.

    Copied from mangadap.util.fileio.channel_dictionary

    Args:
        hdu (`astropy.io.fits.HDUList`_):
            The open fits file.
        ext (:obj:`int`, :obj:`str`):
            The name or index number of the fits extension with the
            relevant map channels and the header with the channel
            names.
        prefix (:obj:`str`, optional):
            The key that is used as a prefix for all header keywords
            associated with channel names. The header keyword is the
            combination of this prefix and the 1-indexed channel
            number.

    Returns:
        :obj:`dict`: The dictionary that provides the channel index
        associate with the channel name.
    """
    channel_dict = {}
    for k, v in hdu[ext].header.items():
        if k[:len(prefix)] == prefix:
            try:
                i = int(k[len(prefix):])-1
            except ValueError:
                continue
            channel_dict[v] = i
    return channel_dict


def read_manga_psf(cube_file, psf_ext, fwhm=False, quiet=False):
    """
    Read the image of the reconstructed datacube point-spread
    function from the MaNGA DRP CUBE file.

    .. warning::

        No check is performed to ensure that the provided extension
        is a valid PSF extension.

    Args:
        cube_file (:obj:`str`):
            The name of the DRP-produced LOGCUBE fits file with the
            reconstructed PSF.
        psf_ext (:obj:`str`):
            The name of the extension with the reconstructed PSF;
            e.g. ``'GPSF'``.
        fwhm (:obj:`bool`, optional):
            If true, will return the g band FWHM as well
        quiet (:obj:`bool`, optional):
            Suppress printed output.

    Returns:
        `numpy.ndarray`_: Array with the reconstructed PSF.

    Raises:
        FileNotFoundError:
            Raised if the provided ``cube_file`` does not exist.
        KeyError:
            Raised if the provided ``psf_ext`` is not a valid fits
            extension.
    """
    if not os.path.isfile(cube_file):
        raise FileNotFoundError('File does not exist: {0}'.format(cube_file))

    # Read the PSF
    # TODO: Switch from print to a logger
    if not quiet:
        print('Reading {0} ... '.format(cube_file))
    with fits.open(cube_file) as hdu:
        if psf_ext not in hdu:
            raise KeyError('{0} does not include an extension {1}.'.format(
                            cube_file, psf_ext))
        psf = hdu[psf_ext].data
        if fwhm: fwhm = hdu[0].header['GFWHM']
    if not quiet:
        print('Done')
    if fwhm: return psf, fwhm
    return psf


def manga_files_from_plateifu(plate, ifu, daptype='HYB10-MILESHC-MASTARHC2', dr='MPL-10',
                              redux_path=None, cube_path=None, analysis_path=None, maps_path=None,
                              check=True):
    """
    Get MaNGA files used by NIRVANA.

    .. warning::

        The method does not check that these files exist.

    Args:
        plate (:obj:`int`):
            Plate number
        ifu (:obj:`int`):
            IFU design number
        daptype (:obj:`str`, optional):
            The identifier for the method used by the DAP to analyze
            the data.
        dr (:obj:`str`, optional):
            Data release identifier that matches the directory with
            the data.
        redux_path (:obj:`str`, optional):
            The top-level directory with all DRP output. If None,
            this will be set to the ``MANGA_SPECTRO_REDUX``
            environmental variable, if it is defined.
        cube_path (:obj:`str`, optional):
            This provides the *direct* path to the datacube file,
            circumventing the use of ``dr`` and ``redux_path``.
        analysis_path (:obj:`str`, optional):
            The top-level directory with all DAP output. If None,
            this will be set to the ``MANGA_SPECTRO_ANALYSIS``
            environmental variable, if it is defined.
        maps_path (:obj:`str`, optional):
            This provides the *direct* path to the maps file,
            circumventing the use of ``dr`` and ``analysis_path``.
        check (:obj:`bool`, optional):
            Check that the directories with the expected files exist.

    Returns:
        :obj:`tuple`: Full path to three files: (1) the DAP MAPS file, (2)
        the DRP LOGCUBE file, and (3) the SDSS 3-color PNG image.

    Raises:
        ValueError:
            Raised if the directories to either the maps or cube file
            could not be determined from the input.
        NotADirectoryError:
            Raised if the directory can be defined but does not exist.
    """
    if cube_path is None:
        _redux_path = os.getenv('MANGA_SPECTRO_REDUX') if redux_path is None else redux_path
        if _redux_path is None:
            raise ValueError('Could not define top-level root for DRP output.')
        cube_path = os.path.join(os.path.abspath(_redux_path), dr, str(plate), 'stack')
    if check and not os.path.isdir(cube_path):
        raise NotADirectoryError('No such directory: {0}'.format(cube_path))

    cube_file = os.path.abspath(os.path.join(cube_path, f'manga-{plate}-{ifu}-LOGCUBE.fits.gz'))
    image_file = os.path.abspath(os.path.join(cube_path, 'images', f'{ifu}.png'))

    if maps_path is None:
        _analysis_path = os.getenv('MANGA_SPECTRO_ANALYSIS') \
                            if analysis_path is None else analysis_path
        if _analysis_path is None:
            raise ValueError('Could not define top-level root for DAP output.')
        maps_path = os.path.join(os.path.abspath(_analysis_path), dr, daptype, str(plate), str(ifu))

    if check and not os.path.isdir(maps_path):
        raise NotADirectoryError('No such directory: {0}'.format(maps_path))

    maps_file = os.path.abspath(os.path.join(maps_path,
                                             f'manga-{plate}-{ifu}-MAPS-{daptype}.fits.gz'))

    return maps_file, cube_file, image_file


def read_drpall(plate, ifu, redux_path, dr, ext='elpetro', quiet=False):
    """
    Read the NASA Sloan Atlas data from the DRPall file for the
    appropriate data release.

    Args:
        plate (:obj:`int`):
            Plate of galaxy.
        ifu (:obj:`int`):
            IFU of galaxy.
        redux_path (:obj:`str`, optional):
            The top-level directory with all DRP output. If None,
            this will be set to the ``MANGA_SPECTRO_REDUX``
        dr (:obj:`str`, optional):
            Data release identifier that matches the directory with
            the data.
        ext (:obj:`str`):
            Whether to use the `elpetro` or `sersic` derived values
            in the NSA catalog.
        quiet (:obj:`bool`, optional):
            Suppress printed output.

    Returns:
        :obj:`tuple`: tuple of inclination, position angle, and |Sersic| n
        values. Angles are in degrees.

    Raises:
        FileNotFoundError:
            Raised if the DRPall file can't be found in the specified
            place.
    """
    # Read the drpall file
    if not quiet:
        print('Reading {0} ... '.format(cube_file))
    drpall_file = glob(f'{cubepath}/{dr}/drpall*.fits')[0]
    plateifu = f'{plate}-{ifu}'

    if not drpall_file:
        raise FileNotFoundError('Could not find drpall file')

    with fits.open(drpall_file) as hdu:
        data = hdu[1].data[hdu[1].data['plateifu'] == plateifu]
        inc = np.degrees(np.arccos(data[f'nsa_{ext}_ba']))
        pa = data[f'nsa_{ext}_phi']
        n = data['nsa_sersic_n']

    if not quiet:
        print('Done')
    return inc, pa, n


class MaNGAKinematics(Kinematics):
    """
    Base class for MaNGA derived classes the provides common functionality.

    This class *should not* be instantiated by itself.
    """

    @classmethod
    def from_plateifu(cls, plate, ifu, daptype='HYB10-MILESHC-MASTARHC2', dr='MPL-10',
                      redux_path=None, cube_path=None, analysis_path=None, maps_path=None,
                      ignore_psf=False, **kwargs):
        """
        Instantiate the object using the plate and IFU number.

        This uses :func:`manga_files_from_plateifu` to construct the
        names of the MAPS and LOGCUBE files that should be located on
        disk.  See that function for the description of the arguments.

        Args:
            ignore_psf (:obj:`bool`, optional):
                Ignore the point-spread function when collecting the
                data. I.e., this instantiates the object setting
                ``cube_file=None``.
            **kwargs:
                Additional arguments that are passed directly to the
                nominal instantiation method.
        """
        maps_file, cube_file, image_file \
                = manga_files_from_plateifu(plate, ifu, daptype=daptype, dr=dr,
                                            redux_path=redux_path, cube_path=cube_path,
                                            analysis_path=analysis_path, maps_path=maps_path)
        if ignore_psf:
            cube_file = None
        elif not os.path.isfile(cube_file):
            warnings.warn(f'Datacube file {cube_file} does not exist!')
            cube_file = None

        if not os.path.isfile(image_file):
            warnings.warn(f'Image file {image_file} does not exist!')
            image_file = None

        return cls(maps_file, cube_file=cube_file, image_file=image_file, **kwargs)


# TODO:
#   - What's the minimum MPL that this will work with
#   - Have this use Marvin to read the data
#   - Use the bits directly instead of just testing > 0
class MaNGAGasKinematics(MaNGAKinematics):
    """
    Class to read and hold ionized-gas kinematics from MaNGA.

    Args:
        maps_file (:obj:`str`):
            Name of the file with the DAP-produced maps.
        cube_file (:obj:`str`, optional):
            The name of the DRP-produced LOGCUBE file with the
            reconstructed PSF. If None, the PSF image will not be
            used in constructing the base
            :class:`~nirvana.data.kinematics.Kinematics` object.
        image_file (:obj:`str`, optional):
            Name of the PNG file containing the image of the galaxy.
        psf_ext (:obj:`str`, optional):
            The name of the extension with the reconstructed PSF.
        line (:obj:`str`, optional):
            The name of the emission-line to use for the kinematics.
        quiet (:obj:`bool`, optional):
            Suppress printed output.
    """
    def __init__(self, maps_file, cube_file=None, image_file=None, psf_ext='RPSF', line='Ha-6564',
                 quiet=False):

        if not os.path.isfile(maps_file):
            raise FileNotFoundError('File does not exist: {0}'.format(maps_file))

        # Get the PSF, if possible
        psf, fwhm = (None,None) if cube_file is None else read_manga_psf(cube_file, psf_ext, fwhm=True)
        image = None if image_file is None else img.imread(image_file)

        # Establish whether or not the gas kinematics were determined
        # on a spaxel-by-spaxel basis, which determines which extension
        # to use for the on-sky coordinates for each unique
        # measurement. The binned coordinates are only used if the data
        # is from the `VOR` bin case (which is probably never going to
        # be used with this package, but anyway...)
        bintype = maps_file.split('.')[0].split('-')[-3]
        coo_ext = 'BIN_LWSKYCOO' if 'VOR' in bintype else 'SPX_SKYCOO'

        # Read the kinematic maps
        # TODO: Switch from print to a logger
        if not quiet:
            print('Reading {0} ... '.format(maps_file))
        with fits.open(maps_file) as hdu:
            eml = channel_dictionary(hdu, 'EMLINE_GVEL')
            if line not in eml:
                raise KeyError('{0} does not contain channel {1}.'.format(maps_file, line))
            x = hdu[coo_ext].data[0]
            y = hdu[coo_ext].data[1]
            binid = hdu['BINID'].data[3]
            grid_x = hdu['SPX_SKYCOO'].data[0]
            grid_y = hdu['SPX_SKYCOO'].data[1]
            sb = hdu['EMLINE_GFLUX'].data[eml[line]]
            sb_ivar = hdu['EMLINE_GFLUX_IVAR'].data[eml[line]]
            sb_mask = hdu['EMLINE_GFLUX_MASK'].data[eml[line]] > 0
            sb_anr = hdu['EMLINE_GANR'].data[eml[line]]
            vel = hdu['EMLINE_GVEL'].data[eml[line]]
            vel_ivar = hdu['EMLINE_GVEL_IVAR'].data[eml[line]]
            vel_mask = hdu['EMLINE_GVEL_MASK'].data[eml[line]] > 0
            sig = hdu['EMLINE_GSIGMA'].data[eml[line]]
            sig_ivar = hdu['EMLINE_GSIGMA_IVAR'].data[eml[line]]
            sig_mask = hdu['EMLINE_GSIGMA_MASK'].data[eml[line]] > 0
            sig_corr = hdu['EMLINE_INSTSIGMA'].data[eml[line]]
            reff = hdu[0].header['REFF']
        if not quiet:
            print('Done')

        super().__init__(vel, vel_ivar=vel_ivar, vel_mask=vel_mask, x=x, y=y, 
                         sb=sb, sb_ivar=sb_ivar, sb_mask=sb_mask, sb_anr=sb_anr,
                         sig=sig, sig_ivar=sig_ivar, sig_mask=sig_mask, 
                         sig_corr=sig_corr, psf=psf, binid=binid, grid_x=grid_x, 
                         grid_y=grid_y, reff=reff , fwhm=fwhm, image=image)


class MaNGAStellarKinematics(MaNGAKinematics):
    """
    Class to read and hold stellar kinematics from MaNGA.

    Args:
        maps_file (:obj:`str`):
            Name of the file with the DAP-produced maps.
        cube_file (:obj:`str`, optional):
            The name of the DRP-produced LOGCUBE file with the
            reconstructed PSF. If None, the PSF image will not be
            used in constructing the base
            :class:`~nirvana.data.kinematics.Kinematics` object.
        image_file (:obj:`str`, optional):
            Name of the PNG file containing the image of the galaxy.
        psf_ext (:obj:`str`, optional):
            The name of the extension with the reconstructed PSF.
        quiet (:obj:`bool`, optional):
            Suppress printed output.
    """
    def __init__(self, maps_file, cube_file=None, image_file=None, psf_ext='GPSF', quiet=False):

        if not os.path.isfile(maps_file):
            raise FileNotFoundError('File does not exist: {0}'.format(maps_file))

        # Get the PSF, if possible
        psf, fwhm = (None,None) if cube_file is None else read_manga_psf(cube_file, psf_ext, fwhm=True)
        image = img.imread(image_file) if image_file else None

        # Establish whether or not the stellar kinematics were
        # determined on a spaxel-by-spaxel basis, which determines
        # which extensions to use for the on-sky coordinates and mean
        # flux for each unique measurement.
        # TODO: Actually, the BIN_* extensions are always right for the
        # stellar kinematics. I.e., in the SPX case, the BIN_* and
        # SPX_* extensions are identical.  Leaving it for now...
        bintype = maps_file.split('.')[0].split('-')[-3]
        coo_ext = 'SPX_SKYCOO' if bintype == 'SPX' else 'BIN_LWSKYCOO'
        flux_ext = 'SPX_MFLUX' if bintype == 'SPX' else 'BIN_MFLUX'

        # Read the kinematic maps
        if not quiet:
            print('Reading {0} ... '.format(maps_file))
        with fits.open(maps_file) as hdu:
            x = hdu[coo_ext].data[0]
            y = hdu[coo_ext].data[1]
            binid = hdu['BINID'].data[1]
            grid_x = hdu['SPX_SKYCOO'].data[0]
            grid_y = hdu['SPX_SKYCOO'].data[1]
            sb = hdu[flux_ext].data
            sb_ivar = hdu['{0}_IVAR'.format(flux_ext)].data
            sb_mask = np.logical_not((sb > 0) & (sb_ivar > 0))
            vel = hdu['STELLAR_VEL'].data
            vel_ivar = hdu['STELLAR_VEL_IVAR'].data
            vel_mask = hdu['STELLAR_VEL_MASK'].data > 0
            sig = hdu['STELLAR_SIGMA'].data
            sig_ivar = hdu['STELLAR_SIGMA_IVAR'].data
            sig_mask = hdu['STELLAR_SIGMA_MASK'].data > 0
            sig_corr = hdu['STELLAR_SIGMACORR'].data[0]
            reff = hdu[0].header['REFF']
        if not quiet:
            print('Done')

        super().__init__(vel, vel_ivar=vel_ivar, vel_mask=vel_mask, x=x, y=y,
                         sb=sb, sb_ivar=sb_ivar, sb_mask=sb_mask, sig=sig, 
                         sig_ivar=sig_ivar, sig_mask=sig_mask, 
                         sig_corr=sig_corr, psf=psf, binid=binid, grid_x=grid_x, 
                         grid_y=grid_y, reff=reff, fwhm=fwhm, image=image)




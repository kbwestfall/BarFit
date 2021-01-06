
from IPython import embed

import numpy as np

from scipy import optimize

from .oned import HyperbolicTangent
from .geometry import projected_polar
from .beam import smear
from .util import cov_err


def rotcurveeval(x,y,vmax,inc,pa,h,vsys=0,xc=0,yc=0,reff=1):
    '''
    Evaluate a simple tanh rotation curve with asymtote vmax, inclination inc
    in degrees, position angle pa in degrees, rotation scale h, systematic
    velocity vsys, and x and y offsets xc and yc. Returns array in same shape
    as input x andy.
    '''

    _inc, _pa = np.radians([inc,pa])
    r,th = projected_polar(x-xc, y-yc, _pa, _inc)
    if reff is not None: r /= reff

    # TODO: Why is there a negative here (i.e., -vmax)? ... After
    # playing around, I assume this is here because it worked for
    # 8078-12703 because it flips the PA to be ~180 instead of near 0?
    model = -vmax * np.tanh(r/h) * np.cos(th) * np.sin(_inc) + vsys
    return model


class AxisymmetricDisk:
    """
    Simple model for an axisymmetric disk.

    Base parameters are xc, yc, pa, inc, vsys.

    Full parameters include number of *projected* rotation curve
    parameters.
    """
    def __init__(self, rc=None, dc=None):
        # Rotation curve
        self.rc = HyperbolicTangent() if rc is None else rc
        # Velocity dispersion curve (can be None)
        self.dc = dc

        # Number of "base" parameters
        self.nbp = 5
        # Total number parameters
        self.np = self.nbp + self.rc.np
        if self.dc is not None:
            self.np += self.dc.np
        # Initialize the parameters
        self.par = self.guess_par()
        self.par_err = None
        # Flag which parameters are freely fit
        self.free = np.ones(self.np, dtype=bool)
        self.nfree = np.sum(self.free)

        # Workspace
        self.x = None
        self.y = None
        self.beam_fft = None
        self.kin = None
        self.sb = None
        self.vel_gpm = None
        self.sig_gpm = None

    def guess_par(self):
        gp = np.concatenate(([0., 0., 45., 30., 0.], self.rc.guess_par()))
        return gp if self.dc is None else np.append(gp, self.dc.guess_par())

    def base_par(self):
        """
        Return the base parameters.  Returns None if parameters are not defined yet.
        """
        return None if self.par is None else self.par[:self.nbp]

    def par_bounds(self):
        minx = np.amin(self.x)
        maxx = np.amax(self.x)
        miny = np.amin(self.y)
        maxy = np.amax(self.y)
        maxr = np.sqrt(max(abs(minx), maxx)**2 + max(abs(miny), maxy)**2)
        # Minimum and maximum allowed values for xc, yc, pa, inc, vsys, vrot, hrot
        lb = np.concatenate(([minx, miny, -350., 0., -300.], self.rc.lb))
        ub = np.concatenate(([maxx, maxy, 350., 89., 300.], self.rc.ub))
        return (lb, ub) if self.dc is None \
                    else (np.append(lb, self.dc.lb), np.append(ub, self.dc.ub))

    def _set_par(self, par):
        """
        Set the parameters by accounting for any fixed parameters.
        """
        if par.ndim != 1:
            raise ValueError('Parameter array must be a 1D vector.')
        if par.size == self.np:
            self.par = par.copy()
            return
        if par.size != self.nfree:
            raise ValueError('Must provide {0} or {1} parameters.'.format(self.np, self.nfree))
        self.par[self.free] = par.copy()

    def _init_coo(self, x, y, beam, is_fft):
        if x is not None:
            self.x = x
        if y is not None:
            self.y = y
        if beam is not None:
            self.beam_fft = beam if is_fft else np.fft.fftn(np.fft.ifftshift(beam))

        if self.x.shape != self.y.shape:
            raise ValueError('Input coordinates must have the same shape.')
        if self.beam_fft is not None:
            if self.x.ndim != 2:
                raise ValueError('To perform convolution, must provide 2d coordinate arrays.')
            if self.beam_fft.shape != self.x.shape:
                raise ValueError('Currently, convolution requires the beam map to have the same '
                                 'shape as the coordinate maps.')

    def _init_par(self, p0, fix):
        if p0 is None:
            p0 = self.guess_par()
        _p0 = np.atleast_1d(p0)
        if _p0.size != self.np:
            raise ValueError('Incorrect number of model parameters.')
        self.par = _p0
        self.par_err = None
        _free = np.ones(self.np, dtype=bool) if fix is None else np.logical_not(fix)
        if _free.size != self.np:
            raise ValueError('Incorrect number of model parameter fitting flags.')
        self.free = _free
        self.nfree = np.sum(self.free)

    def model(self, par=None, x=None, y=None, beam=None, is_fft=False, cnvfftw=None,
              ignore_beam=False):
        """
        Evaluate the model.
        """
        if x is not None or y is not None or beam is not None:
            self._init_coo(x, y, beam, is_fft)
        if self.x is None or self.y is None:
            raise ValueError('No coordinate grid defined.')
        if par is not None:
            self._set_par(par)

        r, theta = projected_polar(self.x - self.par[0], self.y - self.par[1],
                                   *np.radians(self.par[2:4]))

        # NOTE: The velocity-field construction does not include the
        # sin(inclination) term because this is absorbed into the
        # rotation curve amplitude.
        ps = self.nbp
        pe = ps + self.rc.np
        vel = self.rc.sample(r, par=self.par[ps:pe])*np.cos(theta) + self.par[4]
        if self.dc is None:
            # Only fitting the velocity field
            return vel if self.beam_fft is None or ignore_beam \
                        else smear(vel, self.beam_fft, beam_fft=True, sb=self.sb,
                                   cnvfftw=cnvfftw)[1]

        # Fitting both the velocity and velocity-dispersion field
        ps = pe
        pe = ps + self.dc.np
        sig = self.dc.sample(r, par=self.par[ps:pe])
        return (vel, sig) if self.beam_fft is None or ignore_beam \
                        else smear(vel, self.beam_fft, beam_fft=True, sb=self.sb, sig=sig,
                                   cnvfftw=cnvfftw)[1:]

    def _resid(self, par):
        self._set_par(par)
        if self.dc is None:
            return self.kin.vel[self.vel_gpm] - self.kin.bin(self.model())[self.vel_gpm]
        vel, sig = self.model()
        return np.append(self.kin.vel[self.vel_gpm] - self.kin.bin(vel)[self.vel_gpm],
                         self.kin.sig_phys2[self.sig_gpm] - self.kin.bin(sig)[self.sig_gpm]**2)

    def _chisqr(self, par): 
        if self.dc is None:
            return self._resid(par) * np.sqrt(self.kin.vel_ivar[self.vel_gpm])
        ivar = np.append(self.kin.vel_ivar[self.vel_gpm], self.kin.sig_phys2_ivar[self.sig_gpm])
        return self._resid(par) * np.sqrt(ivar)

    def _fit_prep(self, kin, p0, fix, sb_wgt):
        self._init_par(p0, fix)
        self.kin = kin
        self.x = self.kin.grid_x
        self.y = self.kin.grid_y
        self.sb = self.kin.remap('sb').filled(0.0) if sb_wgt else None
        self.beam_fft = self.kin.beam_fft
        self.vel_gpm = np.logical_not(self.kin.vel_mask)
        self.sig_gpm = np.logical_not(self.kin.sig_mask)
        use_resid = self.kin.vel_ivar is None \
                    or (self.dc is not None and self.kin.sig_ivar is None)
        return self._resid if use_resid else self._chisqr

    def lsq_fit(self, kin, sb_wgt=False, p0=None, fix=None, verbose=0):
        """
        Use least_squares to fit kinematics.
        """
        fom = self._fit_prep(kin, p0, fix, sb_wgt)
        lb, ub = self.par_bounds()
        diff_step = np.full(self.np, 0.1, dtype=float)
        result = optimize.least_squares(fom, self.par[self.free], method='trf',
                                        bounds=(lb[self.free], ub[self.free]), 
                                        diff_step=diff_step[self.free], verbose=verbose)
        self._set_par(result.x)

        try:
            cov = cov_err(result.jac)
            self.par_err = np.zeros(self.np, dtype=float)
            self.par_err[self.free] = np.sqrt(np.diag(cov))
        except: 
            self.par_err = None

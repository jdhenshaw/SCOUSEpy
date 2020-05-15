# Licensed under an MIT open source license - see LICENSE

"""

SCOUSE - Semi-automated multi-COmponent Universal Spectral-line fitting Engine
Copyright (c) 2016-2018 Jonathan D. Henshaw
CONTACT: henshaw@mpia.de

"""
import numpy as np

class Decomposer(object):
    """
    spectral decomposition methods

    """
    def __init__(self, spectral_axis):

        self.spectral_axis=spectral_axis
        self.spectrum=None
        self.rms=None
        self.fittype=None
        self.guesses=None
        self.guesses_updated=None
        self.psktemplate=None
        self.pskspectrum=None
        self.modeldict=None
        self.validfit=False
        self.tol=None
        self.res=None
        self.method=None

    def fit_spectrum_from_parent(self,template,spectrum,rms,guesses,tol,res,fittype='gaussian'):
        """
        pass:

        template
        spectrum
        rms

        methods:

        update the template
        fit the spectrum
        check the spectrum
        """
        self.method='parent'
        self.spectrum=spectrum
        self.psktemplate=template
        self.rms=rms
        self.fittype=fittype
        self.guesses=guesses
        self.tol=tol
        self.res=res

        self.update_template()
        self.fit_a_spectrum()
        self.get_model_information()
        self.check_against_parent()

    def fit_a_spectrum(self):
        """
        Fits a spectrum

        """
        import warnings
        from astropy import log
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            old_log = log.level
            log.setLevel('ERROR')
            self.pskspectrum.specfit(interactive=False,
                                clear_all_connections=True,
                                xmin=np.min(self.spectral_axis),
                                xmax=np.max(self.spectral_axis),
                                fittype = self.fittype,
                                guesses = self.guesses,
                                verbose=False,
                                use_lmfit=True)
            log.setLevel(old_log)


    def create_a_template(self,unit=None,xarrkwargs=None):
        """
        generates an instance of pyspeckit's Spectrum class

        Parameters
        ----------
        x : array
            spectral axis
        y : array
            the spectrum
        rms : number
            estimate of the rms
        unit : str
            unit of the spectral axis
        xarrkwargs : dictionary
            key word arguments describing the spectral axis
        """
        import warnings
        from pyspeckit import Spectrum
        from astropy import log

        spectrum=np.zeros_like(self.spectral_axis,dtype='float')
        error_spectrum=np.ones_like(self.spectral_axis,dtype='float')

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            old_log = log.level
            log.setLevel('ERROR')
            self.psktemplate = Spectrum(data=spectrum,
                                        error=error_spectrum,
                                        xarr=self.spectral_axis,
                                        doplot=False,
                                        unit=unit,
                                        xarrkwargs=xarrkwargs,
                                        verbose=False,
                                        )

            log.setLevel(old_log)

    def update_template(self):
        """
        updates a template spectrum with the spectrum values

        """
        import astropy.units as u
        import copy
        # create a copy of the template
        self.pskspectrum=copy.copy(self.psktemplate)
        # update important values
        self.pskspectrum.specfit.Spectrum = self.pskspectrum
        self.pskspectrum.data = u.Quantity(self.spectrum).value
        self.pskspectrum.error = u.Quantity(np.ones_like(self.spectrum)*self.rms).value

    def get_model_information(self):
        """
        Framework for model solution dictionary
        """
        self.modeldict={}

        self.modeldict['fittype']=self.pskspectrum.specfit.fittype
        self.modeldict['parnames']=self.pskspectrum.specfit.fitter.parnames
        self.modeldict['ncomps']=int(self.pskspectrum.specfit.npeaks)
        self.modeldict['params']=self.pskspectrum.specfit.modelpars
        self.modeldict['errors']=self.pskspectrum.specfit.modelerrs
        self.modeldict['rms']=self.pskspectrum.error[0]
        self.modeldict['residstd']= np.std(self.pskspectrum.specfit.residuals)
        self.modeldict['chisq']=self.pskspectrum.specfit.chi2
        self.modeldict['dof']=self.pskspectrum.specfit.dof
        self.modeldict['redchisq']=self.pskspectrum.specfit.chi2/self.pskspectrum.specfit.dof
        self.modeldict['AIC']=self.get_aic()
        if None in self.pskspectrum.specfit.modelerrs:
            self.modeldict['fitconverge'] = False
            self.pskspectrum.specfit.modelerrs = np.zeros(len(self.pskspectrum.specfit.modelerrs))
        else:
            self.modeldict['fitconverge'] = True
        self.modeldict['method']=self.method

    def get_aic(self):
        """
        Computes the AIC value
        """
        from astropy.stats import akaike_info_criterion as aic
        logl = self.pskspectrum.specfit.fitter.logp(self.pskspectrum.xarr, self.pskspectrum.data, self.pskspectrum.error)
        return aic(logl, int(self.pskspectrum.specfit.npeaks)+(int(self.pskspectrum.specfit.npeaks)*3.), len(self.pskspectrum.xarr))

    def check_against_parent(self):
        """

        """
        self.guesses_updated=np.asarray(self.modeldict['params'])
        condition_passed = np.zeros(3, dtype='bool')
        condition_passed = self.check_rms(condition_passed)

        if condition_passed[0]:
            condition_passed=self.check_dispersion(condition_passed)
            if (condition_passed[0]) and (condition_passed[1]):
                condition_passed=self.check_velocity(condition_passed)
                if np.all(condition_passed):
                    if int((np.size(self.guesses_updated)/np.size(self.modeldict['parnames']))==1):
                        self.validfit = True
                    else:
                        self.check_distinct()

    def check_rms(self,condition_passed):
        """
        Check the rms of the best-fitting model components

        Parameters
        ----------
        condition_passed : list
            boolean list indicating which quality control steps have been satisfied

        """
        # Find where in the parameter array the "amplitude" is located. Make this
        # general to allow for other models
        namelist = ['tex', 'amp', 'amplitude', 'peak', 'tant', 'tmb']
        foundname = [pname in namelist for pname in self.modeldict['parnames']]
        foundname = np.array(foundname)
        idx=np.where(foundname==True)[0]
        idx=np.asscalar(idx[0])

        nparams=np.size(self.modeldict['parnames'])

        # Now check all components to see if they are above the rms threshold
        for i in range(self.modeldict['ncomps']):
            if (self.modeldict['params'][int(i*nparams)+idx] < self.rms*self.tol[0]):
                self.guesses_updated[int((i*nparams)):int((i*nparams)+nparams)] = 0.0

        violating_comps = (self.guesses_updated==0.0)
        if np.any(violating_comps):
            condition_passed[0]=False
        else:
            condition_passed[0]=True

        self.guesses_updated = self.guesses_updated[(self.guesses_updated != 0.0)]

        return condition_passed

    def check_dispersion(self,condition_passed):
        """
        Check the fwhm of the best-fitting model components

        Parameters
        ----------
        condition_passed : list
            boolean list indicating which quality control steps have been satisfied

        """

        fwhmconv = 2.*np.sqrt(2.*np.log(2.))

        # Find where the velocity dispersion is located in the parameter array
        namelist = ['dispersion', 'width', 'fwhm']
        foundname = [pname in namelist for pname in self.modeldict['parnames']]
        foundname = np.array(foundname)
        idx=np.where(foundname==True)[0]
        idx=np.asscalar(idx[0])

        nparams=np.size(self.modeldict['parnames'])
        ncomponents=np.size(self.guesses_updated)/nparams

        for i in range(int(ncomponents)):

            # Find the closest matching component in the parent SAA model
            diff = self.find_closest_match(i, nparams)
            idmin = np.where(diff == np.min(diff))[0]
            idmin = idmin[0]

            # Work out the relative change in velocity dispersion
            relchange = self.guesses_updated[int((i*nparams)+idx)]/self.guesses[int((idmin*nparams)+idx)]
            if relchange < 1.:
                relchange = 1./relchange

            # Does this satisfy the criteria
            if (self.guesses_updated[int((i*nparams)+idx)]*fwhmconv < self.res*self.tol[1]) or \
               (relchange > self.tol[2]):
                # set to zero
                self.guesses_updated[int((i*nparams)):int((i*nparams)+nparams)] = 0.0

        violating_comps = (self.guesses_updated==0.0)
        if np.any(violating_comps):
            condition_passed[1]=False
        else:
            condition_passed[1]=True

        self.guesses_updated = self.guesses_updated[(self.guesses_updated != 0.0)]

        return condition_passed

    def check_velocity(self,condition_passed):
        """
        Check the centroid velocity of the best-fitting model components

        Parameters
        ----------
        condition_passed : list
            boolean list indicating which quality control steps have been satisfied

        """

        # Find where the peak is located in the parameter array
        namelist = ['velocity', 'shift', 'centroid', 'center']
        foundname = [pname in namelist for pname in self.modeldict['parnames']]
        foundname = np.array(foundname)
        idxv=np.where(foundname==True)[0]
        idxv=np.asscalar(idxv[0])

        # Find where the velocity dispersion is located in the parameter array
        namelist = ['dispersion', 'width', 'fwhm']
        foundname = [pname in namelist for pname in self.modeldict['parnames']]
        foundname = np.array(foundname)
        idxd=np.where(foundname==True)[0]
        idxd=np.asscalar(idxd[0])

        nparams=np.size(self.modeldict['parnames'])
        ncomponents=np.size(self.guesses_updated)/nparams

        for i in range(int(ncomponents)):

            # Find the closest matching component in the parent SAA model
            diff = self.find_closest_match(i, nparams)
            idmin = np.where(diff == np.min(diff))[0]
            idmin = idmin[0]

            # Limits for tolerance
            lower_lim = self.guesses[int((idmin*nparams)+idxv)]-(self.tol[3]*self.guesses[int((idmin*nparams)+idxd)])
            upper_lim = self.guesses[int((idmin*nparams)+idxv)]+(self.tol[3]*self.guesses[int((idmin*nparams)+idxd)])

            # Does this satisfy the criteria
            if (self.guesses_updated[(i*nparams)+idxv] < lower_lim) or \
               (self.guesses_updated[(i*nparams)+idxv] > upper_lim):
                # set to zero
                self.guesses_updated[int((i*nparams)):int((i*nparams)+nparams)] = 0.0

        violating_comps = (self.guesses_updated==0.0)
        if np.any(violating_comps):
            condition_passed[2]=False
        else:
            condition_passed[2]=True

        self.guesses_updated = self.guesses_updated[(self.guesses_updated != 0.0)]

        return condition_passed

    def check_distinct(self):
        """
        Check to see if component pairs can be distinguished in velocity

        """

        # Find where the peak is located in the parameter array
        namelist = ['tex', 'amp', 'amplitude', 'peak', 'tant', 'tmb']
        foundname = [pname in namelist for pname in self.modeldict['parnames']]
        foundname = np.array(foundname)
        idxp=np.where(foundname==True)[0]
        idxp=np.asscalar(idxp[0])

        # Find where the peak is located in the parameter array
        namelist = ['velocity', 'shift', 'centroid', 'center']
        foundname = [pname in namelist for pname in self.modeldict['parnames']]
        foundname = np.array(foundname)
        idxv=np.where(foundname==True)[0]
        idxv=np.asscalar(idxv[0])

        # Find where the velocity dispersion is located in the parameter array
        namelist = ['dispersion', 'width', 'fwhm']
        foundname = [pname in namelist for pname in self.modeldict['parnames']]
        foundname = np.array(foundname)
        idxd=np.where(foundname==True)[0]
        idxd=np.asscalar(idxd[0])

        fwhmconv = 2.*np.sqrt(2.*np.log(2.))

        nparams=np.size(self.modeldict['parnames'])
        ncomponents=np.size(self.guesses_updated)/nparams

        intlist  = [self.guesses_updated[int((i*nparams)+idxp)] for i in range(int(ncomponents))]
        velolist = [self.guesses_updated[int((i*nparams)+idxv)] for i in range(int(ncomponents))]
        displist = [self.guesses_updated[int((i*nparams)+idxd)] for i in range(int(ncomponents))]

        diff = np.zeros(int(ncomponents))
        validvs = np.ones(int(ncomponents))

        for i in range(int(ncomponents)):

            if validvs[i] != 0.0:

                # Calculate the velocity difference between all components
                for j in range(int(ncomponents)):
                    diff[j] = abs(velolist[i]-velolist[j])
                diff[(diff==0.0)] = np.nan

                # Find the minimum difference (i.e. the adjacent component)
                idmin = np.where(diff==np.nanmin(diff))[0]
                idmin = idmin[0]
                adjacent_intensity = intlist[idmin]
                adjacent_velocity = velolist[idmin]
                adjacent_dispersion = displist[idmin]

                # Get the separation between each component and its neighbour
                sep = np.abs(velolist[i] - adjacent_velocity)
                # Calculate the allowed separation between components
                min_allowed_sep = np.min(np.array([displist[i], adjacent_dispersion]))*fwhmconv*self.tol[4]

                if sep > min_allowed_sep:
                    if validvs[idmin] !=0.0:
                        validvs[i] = 1.0
                        validvs[idmin] = 1.0
                    else:
                        validvs[i] = 1.0
                        validvs[idmin] = 0.0

                        intlist[idmin] = 0.0
                        velolist[idmin] = 0.0
                        displist[idmin] = 0.0
                else:
                    # If the components do not satisfy the criteria then average
                    # them and use the new quantities as input guesses
                    validvs[i] = 1.0
                    validvs[idmin] = 0.0

                    intlist[i] = np.mean([intlist[i], adjacent_intensity])
                    velolist[i] = np.mean([velolist[i], adjacent_velocity])
                    displist[i] = np.mean([displist[i], adjacent_dispersion])

                    intlist[idmin] = 0.0
                    velolist[idmin] = 0.0
                    displist[idmin] = 0.0

        for i in range(int(ncomponents)):
            self.guesses_updated[(i*nparams)+idxp] = intlist[i]
            self.guesses_updated[(i*nparams)+idxv] = velolist[i]
            self.guesses_updated[(i*nparams)+idxd] = displist[i]

        violating_comps = (self.guesses_updated==0.0)
        if np.any(violating_comps):
            self.validfit=False
        else:
            self.validfit=True

        self.guesses_updated = self.guesses_updated[(self.guesses_updated != 0.0)]

    def find_closest_match(self,i,nparams):
        """
        Find the closest matching component in the parent SAA model to the current
        component in bf.

        Parameters
        ----------
        i : number
            index for params
        nparams : number
            number of parameters in the pyspeckit model

        """

        diff = np.zeros(int(np.size(self.guesses)/nparams))
        for j in range(int(np.size(self.guesses)/nparams)):
            pdiff = 0.0
            for k in range(nparams):
                pdiff+=(self.guesses_updated[int((i*nparams)+k)] - self.guesses[int((j*nparams)+k)])**2.
            diff[j] = np.sqrt(pdiff)

        return diff

#
#  Copyright (C) 2010, 2015, 2016, 2017, 2018, 2019, 2020, 2021
#  Smithsonian Astrophysical Observatory
#
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License along
#  with this program; if not, write to the Free Software Foundation, Inc.,
#  51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import logging
import os
import sys
import warnings

import numpy

import sherpa.ui.utils
from sherpa.astro.instrument import create_arf, create_delta_rmf, \
    create_non_delta_rmf, has_pha_response
from sherpa.ui.utils import _check_type
from sherpa.utils import SherpaInt, SherpaFloat, sao_arange, \
    send_to_pager
from sherpa.utils.err import ArgumentErr, ArgumentTypeErr, DataErr, \
    IdentifierErr, ImportErr, IOErr, ModelErr
from sherpa.data import Data1D, Data1DAsymmetricErrs
import sherpa.astro.all
import sherpa.astro.plot
from sherpa.astro.ui import serialize
from sherpa.sim import NormalParameterSampleFromScaleMatrix
from sherpa.stats import Cash, CStat, WStat
from sherpa.models.basic import TableModel
from sherpa.astro import fake
from sherpa.astro.data import DataPHA

warning = logging.getLogger(__name__).warning
info = logging.getLogger(__name__).info


string_types = (str, )


__all__ = ('Session',)


class Session(sherpa.ui.utils.Session):

    ###########################################################################
    # Standard methods
    ###########################################################################

    def __init__(self):

        self.clean()
        sherpa.ui.utils.Session.__init__(self)

    ###########################################################################
    # High-level utilities
    ###########################################################################

    def _fix_background_id(self, id, bkg_id):
        """Validate the background id.

        The identifier has the same restrictions as the dataset
        identifier.

        Parameters
        ----------
        id : int or str or None
            The dataset identifier. This is only used if bkg_id is
            None and must refer to a DataPHA dataset.
        bkg_id : int or str or None
            The identifier to check. If None then the default backround
            identifier will be used, taken from the id dataset.

        Returns
        -------
        bkg_id : int or str
            The background identifier to use (it will only differ from
            the input parameter was set to None).

        Raises
        ------
        sherpa.utils.err.ArgumentTypeErr
            If the identifier was not a string or an integer.
        sherpa.utils.err.IdentifierErr
            If the identifier was invalid.

        See Also
        --------
        _fix_id

        Notes
        -----
        Since there is currently no way to set the default background
        id of the DataPHA class (e.g. in unpack_pha) we do not use the
        _default_id setting here.

        """

        if bkg_id is None:
            # The assumption here is that if we are asking about a
            # background identifier then there must already be a
            # loaded PHA dataset.
            data = self._get_pha_data(id)
            return data.default_background_id

            # return self._default_id

        # We rely on the validation made by _fix_id
        return self._fix_id(bkg_id)

    def __setstate__(self, state):
        if '_background_sources' not in state:
            self.__dict__['_background_sources'] = state.pop(
                '_background_models')

        sherpa.ui.utils.Session.__setstate__(self, state)

    def clean(self):
        """Clear out the current Sherpa session.

        The `clean` function removes all data sets and model
        assignments, and restores the default settings for the
        optimisation and fit statistic.

        See Also
        --------
        save : Save the current Sherpa session to a file.
        restore : Load in a Sherpa session from a file.
        save_all : Save the Sherpa session as an ASCII file.

        Examples
        --------

        >>> clean()

        """
        self._pileup_models = {}
        self._background_models = {}
        self._background_sources = {}

        self._dataphaplot = sherpa.astro.plot.DataPHAPlot()
        self._astrosourceplot = sherpa.astro.plot.SourcePlot()
        self._astrocompsrcplot = sherpa.astro.plot.ComponentSourcePlot()
        self._astrocompmdlplot = sherpa.astro.plot.ComponentModelPlot()
        self._modelhisto = sherpa.astro.plot.ModelHistogram()
        self._bkgmodelhisto = sherpa.astro.plot.BkgModelHistogram()

        # self._bkgdataplot = sherpa.astro.plot.DataPHAPlot()
        self._bkgdataplot = sherpa.astro.plot.BkgDataPlot()
        self._bkgmodelplot = sherpa.astro.plot.BkgModelPHAHistogram()
        self._bkgfitplot = sherpa.astro.plot.BkgFitPlot()
        self._bkgchisqrplot = sherpa.astro.plot.BkgChisqrPlot()
        self._bkgdelchiplot = sherpa.astro.plot.BkgDelchiPlot()
        self._bkgresidplot = sherpa.astro.plot.BkgResidPlot()
        self._bkgratioplot = sherpa.astro.plot.BkgRatioPlot()
        self._bkgsourceplot = sherpa.astro.plot.BkgSourcePlot()
        self._arfplot = sherpa.astro.plot.ARFPlot()
        self._orderplot = sherpa.astro.plot.OrderPlot()
        self._energyfluxplot = sherpa.astro.plot.EnergyFluxHistogram()
        self._photonfluxplot = sherpa.astro.plot.PhotonFluxHistogram()

        # This is a new dictionary of XSPEC module settings.  It
        # is meant only to be populated by the save function, so
        # that the user's XSPEC settings can be saved in the pickle
        # file.  Then, restore can peel out settings from the
        # restored _xspec_state variable, and set abundance,
        # cross-section, etc. in the XSPEC module.
        #
        # TODO: it should probably not be reset by clean since there's
        #       no way to clear the XSPEC state (we could try and
        #       unset all the changes but it's not guaranteed we can
        #       do so).
        #
        self._xspec_state = None

        sherpa.ui.utils.Session.clean(self)

        self._pyblocxs = sherpa.astro.sim.MCMC()

        self._plot_types['order'] = [self._orderplot]
        self._plot_types['energy'] = [self._energyfluxplot]
        self._plot_types['photon'] = [self._photonfluxplot]
        self._plot_types['compsource'].append(self._astrocompsrcplot)
        self._plot_types['compmodel'].append(self._astrocompmdlplot)

        self._plot_types['data'].append(self._dataphaplot)
        self._plot_types['source'].append(self._astrosourceplot)
        self._plot_types['model'].append(self._modelhisto)
        self._plot_types['arf'] = [self._arfplot]
        self._plot_types['bkg'] = [self._bkgdataplot]
        self._plot_types['bkgmodel'] = [self._bkgmodelhisto]
        self._plot_types['bkgfit'] = [self._bkgfitplot]
        self._plot_types['bkgsource'] = [self._bkgsourceplot]
        self._plot_types['bkgratio'] = [self._bkgratioplot]
        self._plot_types['bkgresid'] = [self._bkgresidplot]
        self._plot_types['bkgdelchi'] = [self._bkgdelchiplot]
        self._plot_types['bkgchisqr'] = [self._bkgchisqrplot]

        self._plot_type_names['order'] = 'order'
        # self._plot_type_names['energy'] = 'energy'  - how to do energy/flux plots?
        # self._plot_type_names['photon'] = 'photon'
        self._plot_type_names['astrocompsource'] = 'source_component'
        self._plot_type_names['astrocompmodel'] = 'model_componentl'

        self._plot_type_names['astrodata'] = 'data'
        self._plot_type_names['astrosource'] = 'source'  # is this meaningful anymore
        self._plot_type_names['astromodel'] = 'model'  # is this meaningful anymore
        self._plot_type_names['arf'] = 'arf'
        self._plot_type_names['bkg'] = 'bkg'
        self._plot_type_names['bkgmodel'] = 'bkg_model'
        self._plot_type_names['bkgfit'] = 'bkg_fit'
        self._plot_type_names['bkgsource'] = 'bkg_source'
        self._plot_type_names['bkgratio'] = 'bkg_ratio'
        self._plot_type_names['bkgresid'] = 'bkg_resid'
        self._plot_type_names['bkgdelchi'] = 'bkg_delchi'
        self._plot_type_names['bkgchisqr'] = 'bkg_chisqr'

    # Add ability to save attributes sepcific to the astro package.
    # Save XSPEC module settings that need to be restored.
    def save(self, filename='sherpa.save', clobber=False):
        """Save the current Sherpa session to a file.

        Parameters
        ----------
        filename : str, optional
           The name of the file to write the results to. The default
           is 'sherpa.save'.
        clobber : bool, optional
           This flag controls whether an existing file can be
           overwritten (``True``) or if it raises an exception (``False``,
           the default setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        clean : Clear all stored session data.
        restore : Load in a Sherpa session from a file.
        save_all : Save the Sherpa session as an ASCII file.

        Notes
        -----
        The current Sherpa session is saved using the Python `pickle`
        module. The output is a binary file, which may not be portable
        between versions of Sherpa, but is platform independent, and
        contains all the data. This means that files created by `save`
        can be sent to collaborators to share results.

        Examples
        --------

        Save the current session to the file 'sherpa.save'.

        >>> save()

        Save the current session to the file 'bestfit.sherpa',
        overwriting any existing version of the file.

        >>> save('bestfit.sherpa', clobber=True)

        """
        if hasattr(sherpa.astro, "xspec"):
            self._xspec_state = sherpa.astro.xspec.get_xsstate()
        else:
            self._xspec_state = None
        sherpa.ui.utils.Session.save(self, filename, clobber)

    def restore(self, filename='sherpa.save'):
        """Load in a Sherpa session from a file.

        Parameters
        ----------
        filename : str, optional
           The name of the file to read the results from. The default
           is 'sherpa.save'.

        Raises
        ------
        IOError
           If `filename` does not exist.

        See Also
        --------
        clean : Clear all stored session data.
        save : Save the current Sherpa session to a file.

        Notes
        -----
        The input to `restore` must have been created with the `save`
        command. This is a binary file, which may not be portable
        between versions of Sherpa, but is platform independent. A
        warning message may be created if a file saved by an older
        (or newer) version of Sherpa is loaded. An example of such
        a message is::

          WARNING: Could not determine whether the model is discrete.
          This probably means that you have restored a session saved with a previous version of Sherpa.
          Falling back to assuming that the model is continuous.

        Examples
        --------

        Load in the Sherpa session from 'sherpa.save'.

        >>> restore()

        Load in the session from the given file:

        >>> restore('/data/m31/setup.sherpa')

        """
        sherpa.ui.utils.Session.restore(self, filename)
        if hasattr(sherpa.astro, "xspec"):
            if self._xspec_state is not None:
                sherpa.astro.xspec.set_xsstate(self._xspec_state)
                self._xspec_state = None

    def _get_show_data(self, id=None):
        data_str = ''
        ids = self.list_data_ids()
        if id is not None:
            ids = [self._fix_id(id)]
        for id in ids:
            data = self.get_data(id)

            data_str += 'Data Set: %s\n' % id
            data_str += 'Filter: %s\n' % data.get_filter_expr()
            if isinstance(data, sherpa.astro.data.DataPHA):

                nbkg = len(data.background_ids)
                for bkg_id in data.background_ids:
                    # Apply grouping/filtering if set
                    scale = data.get_background_scale(bkg_id)
                    if scale is None:
                        continue

                    data_str += 'Bkg Scale'
                    if nbkg > 1 or bkg_id != 1:
                        data_str += ' {}'.format(bkg_id)

                    data_str += ': '
                    if numpy.isscalar(scale):
                        data_str += '{:g}'.format(float(scale))
                    else:
                        # would like to use sherpa.utils/print_fields style output
                        # but not available and I don't feel like it's
                        # worth it
                        data_str += '{}[{}]'.format(scale.dtype, scale.size)

                    data_str += '\n'

                data_str += 'Noticed Channels: %s\n' % data.get_noticed_expr()

            data_str += data.__str__() + '\n\n'

            if isinstance(data, sherpa.astro.data.DataPHA):
                for resp_id in data.response_ids:
                    # ARF or RMF could be None
                    arf, rmf = data.get_response(resp_id)
                    if rmf is not None:
                        data_str += 'RMF Data Set: %s:%s\n' % (id, resp_id)
                        data_str += rmf.__str__() + '\n\n'
                    if arf is not None:
                        data_str += 'ARF Data Set: %s:%s\n' % (id, resp_id)
                        data_str += arf.__str__() + '\n\n'

                data_str += self._get_show_bkg(id)

        return data_str

    def _get_show_bkg(self, id=None, bkg_id=None):
        data_str = ''
        ids = self.list_data_ids()
        if id is not None:
            ids = [self._fix_id(id)]

        for id in ids:
            data = self.get_data(id)

            if not isinstance(data, sherpa.astro.data.DataPHA):
                continue

            bkg_ids = data.background_ids
            if bkg_id is not None:
                bkg_ids = [data._fix_background_id(bkg_id)]

            for bkg_id in bkg_ids:
                bkg = self.get_bkg(id, bkg_id)
                data_str += 'Background Data Set: %s:%s\n' % (id, bkg_id)
                data_str += 'Filter: %s\n' % bkg.get_filter_expr()
                data_str += 'Noticed Channels: %s\n' % bkg.get_noticed_expr()
                data_str += bkg.__str__() + '\n\n'

                for bk_rp_id in bkg.response_ids:
                    # ARF or RMF could be None
                    arf, rmf = bkg.get_response(bk_rp_id)
                    if rmf is not None:
                        data_str += ('Background RMF Data Set: %s:%s\n' %
                                     (id, bkg_id))
                        data_str += rmf.__str__() + '\n\n'
                    if arf is not None:
                        data_str += ('Background ARF Data Set: %s:%s\n' %
                                     (id, bkg_id))
                        data_str += arf.__str__() + '\n\n'

        return data_str

    def _get_show_bkg_model(self, id=None, bkg_id=None):
        model_str = ''
        ids = self.list_data_ids()
        if id is not None:
            ids = [self._fix_id(id)]
        for id in ids:
            if bkg_id is not None:
                bkg_ids = [bkg_id]
            else:
                bkg_ids = list(self._background_models.get(id, {}).keys())
                bkg_ids.extend(self._background_sources.get(id, {}).keys())
                bkg_ids = list(set(bkg_ids))

            for bkg_id in bkg_ids:
                model_str += 'Background Model: %s:%s\n' % (id, bkg_id)
                model_str += self.get_bkg_model(id, bkg_id).__str__() + '\n\n'

        return model_str

    def _get_show_bkg_source(self, id=None, bkg_id=None):
        model_str = ''
        ids = self.list_data_ids()
        if id is not None:
            ids = [self._fix_id(id)]
        for id in ids:
            if bkg_id is not None:
                bkg_ids = [bkg_id]
            else:
                bkg_ids = self._background_sources.get(id, {}).keys()

            for bkg_id in bkg_ids:
                model_str += 'Background Source: %s:%s\n' % (id, bkg_id)
                model_str += self.get_bkg_source(id, bkg_id).__str__() + '\n\n'

        return model_str

    def show_bkg(self, id=None, bkg_id=None, outfile=None, clobber=False):
        """Show the details of the PHA background data sets.

        This displays information about the background, or
        backgrounds, for the loaded data sets. This includes: any
        filters, the grouping settings, mission-specific header
        keywords, and the details of any associated instrument
        responses files (ARF, RMF).

        Parameters
        ----------
        id : int or str, optional
           The data set. If not given then all background data sets
           are displayed.
        bkg_id : int or str, optional
           The background component to display. The default is all
           components.
        outfile : str, optional
           If not given the results are displayed to the screen,
           otherwise it is taken to be the name of the file to
           write the results to.
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If `outfile` already exists and `clobber` is ``False``.

        See Also
        --------
        list_model_ids : List of all the data sets with a source expression.
        load_bkg : Load the background from a file and add it to a PHA data set.
        show_all : Report the current state of the Sherpa session.

        """
        txt = self._get_show_bkg(id, bkg_id)
        send_to_pager(txt, outfile, clobber)

    def show_bkg_source(self, id=None, bkg_id=None, outfile=None, clobber=False):
        """Display the background model expression for a data set.

        This displays the background model for a data set, that is,
        the expression set by `set_bkg_model` or `set_bkg_source`, as
        well as the parameter values for the model. The
        `show_bkg_model` function displays the model that is fit to
        the data; that is, it includes any instrument responses.

        Parameters
        ----------
        id : int or str, optional
           The data set. If not given then all background expressions
           are displayed.
        bkg_id : int or str, optional
           The background component to display. The default is all
           components.
        outfile : str, optional
           If not given the results are displayed to the screen,
           otherwise it is taken to be the name of the file to
           write the results to.
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If `outfile` already exists and `clobber` is ``False``.

        See Also
        --------
        list_model_ids : List of all the data sets with a source expression.
        set_bkg_model : Set the background model expression for a data set.
        show_all : Report the current state of the Sherpa session.
        show_model : Display the model expression used to fit a data set.
        show_bkg_model : Display the background model expression used to fit a data set.

        """
        txt = self._get_show_bkg_source(id, bkg_id)
        send_to_pager(txt, outfile, clobber)

    def show_bkg_model(self, id=None, bkg_id=None, outfile=None, clobber=False):
        """Display the background model expression used to fit a data set.

        This displays the model used to the the background data set,
        that is, the expression set by `set_bkg_model` or
        `set_bkg_source` combined with any instrumental responses,
        together with the parameter values for the model. The
        `show_bkg_source` function displays just the background model,
        without the instrument components (if any).

        Parameters
        ----------
        id : int or str, optional
           The data set. If not given then all background expressions are
           displayed.
        bkg_id : int or str, optional
           The background component to display. The default is all
           components.
        outfile : str, optional
           If not given the results are displayed to the screen,
           otherwise it is taken to be the name of the file to
           write the results to.
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If `outfile` already exists and `clobber` is ``False``.

        See Also
        --------
        list_model_ids : List of all the data sets with a source expression.
        set_bkg_model : Set the background model expression for a data set.
        show_all : Report the current state of the Sherpa session.
        show_model : Display the model expression used to fit a data set.
        show_bkg_source : Display the background model expression for a data set.

        """
        txt = self._get_show_bkg_model(id, bkg_id)
        send_to_pager(txt, outfile, clobber)

    ###########################################################################
    # Data
    ###########################################################################

    # DOC-NOTE: also in sherpa.utils
    def dataspace1d(self, start, stop, step=1, numbins=None,
                    id=None, bkg_id=None, dstype=sherpa.data.Data1DInt):
        """Create the independent axis for a 1D data set.

        Create an "empty" one-dimensional data set by defining the
        grid on which the points are defined (the independent axis).
        The values are set to 0.

        Parameters
        ----------
        start : number
           The minimum value of the axis.
        stop : number
           The maximum value of the axis.
        step : number, optional
           The separation between each grid point. This is not used if
           ``numbins`` is set.
        numbins : int, optional
           The number of grid points. This over-rides the ``step``
           setting.
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        bkg_id : int or str, optional
           If set, the grid is for the background component of the
           data set.
        dstype : data class to use, optional
           What type of data is to be used. Supported values include
           `Data1DInt` (the default), `Data1D`, and `DataPHA`.

        See Also
        --------
        dataspace2d : Create the independent axis for a 2D data set.
        get_dep : Return the dependent axis of a data set.
        get_indep : Return the independent axes of a data set.
        set_dep : Set the dependent axis of a data set.

        Notes
        -----
        The meaning of the ``stop`` parameter depends on whether it is a
        binned or unbinned data set (as set by the ``dstype``
        parameter).

        Examples
        --------

        Create a binned data set, starting at 1 and with a
        bin-width of 1.

        >>> dataspace1d(1, 5, 1)
        >>> print(get_indep())
        (array([ 1.,  2.,  3.,  4.]), array([ 2.,  3.,  4.,  5.]))

        This time for an un-binned data set:

        >>> dataspace1d(1, 5, 1, dstype=Data1D)
        >>> print(get_indep())
        (array([ 1.,  2.,  3.,  4.,  5.]),)

        Specify the number of bins rather than the grid spacing:

        >>> dataspace1d(1, 5, numbins=5, id=2)
        >>> (xlo, xhi) = get_indep(2)
        >>> xlo
        array([ 1. ,  1.8,  2.6,  3.4,  4.2])
        >>> xhi
        array([ 1.8,  2.6,  3.4,  4.2,  5. ])

        >>> dataspace1d(1, 5, numbins=5, id=3, dstype=Data1D)
        >>> (x, ) = get_indep(3)
        >>> x
        array([ 1.,  2.,  3.,  4.,  5.])

        Create a grid for a PHA data set called 'jet', and
        for its background component:

        >>> dataspace1d(0.01, 11, 0.01, id='jet', dstype=DataPHA)
        >>> dataspace1d(0.01, 11, 0.01, id='jet', bkg_id=1,
        ...             dstype=DataPHA)

        """
        # support non-integrated grids with inclusive boundaries
        # We do NOT want to use an isinstance check since Data1DInt is
        # derived from Data1D.
        if dstype in (sherpa.data.Data1D, sherpa.astro.data.DataPHA):
            stop += step

        xlo, xhi, y = sherpa.utils.dataspace1d(start, stop, step=step,
                                               numbins=numbins)
        args = [xlo, xhi, y]
        kwargs = {}

        if dstype is sherpa.astro.data.DataPHA:
            channel = numpy.arange(1, len(xlo) + 1, dtype=float)
            args = [channel, y]
            # kwargs['bin_lo'] = xlo
            # kwargs['bin_hi'] = xhi
        elif dstype is not sherpa.data.Data1DInt:
            args = [xlo, y]

        if bkg_id is not None:
            self._get_pha_data(id).set_background(dstype('bkg_dataspace1d',
                                                         *args, **kwargs),
                                                  bkg_id)
        else:
            self.set_data(id, dstype('dataspace1d', *args, **kwargs))

    # DOC-NOTE: also in sherpa.utils
    def dataspace2d(self, dims, id=None, dstype=sherpa.astro.data.DataIMG):
        """Create the independent axis for a 2D data set.

        Create an "empty" two-dimensional data set by defining the
        grid on which the points are defined (the independent axis).
        The values are set to 0.

        Parameters
        ----------
        dims : sequence of 2 number
           The dimensions of the grid in ``(width,height)`` order.
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        dstype : data class to use, optional
           What type of data is to be used. Supported values include
           `DataIMG` (the default), `Data2D`, and `Data2DInt`.

        See Also
        --------
        dataspace1d : Create the independent axis for a 1D data set.
        get_dep : Return the dependent axis of a data set.
        get_indep : Return the independent axes of a data set.
        set_dep : Set the dependent axis of a data set.

        Examples
        --------

        Create a 200 pixel by 150 pixel grid (number of columns by
        number of rows) and display it (each pixel has a value of 0):

        >>> dataspace2d([200, 150])
        >>> image_data()

        Create a data space called "fakeimg":

        >>> dataspace2d([nx, ny], id="fakeimg")

        """
        x0, x1, y, shape = sherpa.utils.dataspace2d(dims)

        dataset = None
        if issubclass(dstype, (sherpa.astro.data.DataIMGInt,
                               sherpa.data.Data2DInt)):
            dataset = dstype('dataspace2d', x0 - 0.5, x1 - 0.5, x0 + 0.5, x1 + 0.5,
                             y, shape)
        else:
            dataset = dstype('dataspace2d', x0, x1, y, shape)

        self.set_data(id, dataset)

    # DOC-NOTE: also in sherpa.utils
    # DOC-TODO: how to describe Crates and/or AstroPy?
    def unpack_arrays(self, *args):
        """Create a sherpa data object from arrays of data.

        The object returned by `unpack_arrays` can be used in a
        `set_data` call.

        Parameters
        ----------
        args : array_like
           Arrays of data. The order, and number, is determined by
           the `dstype` parameter, and listed in the `load_arrays`
           routine.
        dstype
           The data set type. The default is `Data1D` and values
           include: `Data1D`, `Data1DInt`, `Data2D`, `Data2DInt`,
           `DataPHA`, and `DataIMG`. The class is expected to
           be derived from `sherpa.data.BaseData`.

        Returns
        -------
        instance
           The data set object matching the requested `dstype`
           parameter.

        See Also
        --------
        get_data : Return the data set by identifier.
        load_arrays : Create a data set from array values.
        set_data : Set a data set.
        unpack_data : Create a sherpa data object from a file.

        Examples
        --------

        Create a 1D (unbinned) data set from the values in
        the x and y arrays. Use the returned object to create
        a data set labelled "oned":

        >>> x = [1, 3, 7, 12]
        >>> y = [2.3, 3.2, -5.4, 12.1]
        >>> dat = unpack_arrays(x, y)
        >>> set_data("oned", dat)

        Include statistical errors on the data:

        >>> edat = unpack_arrays(x, y, dy)

        Create a "binned" 1D data set, giving the low,
        and high edges of the independent axis (xlo
        and xhi respectively) and the dependent values
        for this grid (y):

        >>> hdat = unpack_arrays(xlo, xhi, y, Data1DInt)

        Create a 3 column by 4 row image:

        >>> ivals = np.arange(12)
        >>> y, x = np.mgrid[0:3, 0:4]
        >>> x = x.flatten()
        >>> y = y.flatten()
        >>> idat = unpack_arrays(x, y, ivals, (3, 4), DataIMG)

        """
        dataset = None
        try:
            dataset = sherpa.astro.io.read_arrays(*args)
        except NotImplementedError:
            # if the astro backend is not set, fall back on io module version.
            dataset = sherpa.io.read_arrays(*args)
        return dataset

    # DOC-NOTE: also in sherpa.utils
    # DOC-TODO: rework the Data type notes section (also needed for
    # unpack_arrays)
    def load_arrays(self, id, *args):
        """Create a data set from array values.

        Parameters
        ----------
        id : int or str
           The identifier for the data set to use.
        *args
           Two or more arrays, followed by the type of data set to
           create.

        Warnings
        --------
        Sherpa currently does not support numpy masked arrays. Use the
        set_filter function and note that it follows a different convention by
        default (a positive value or True for a "bad" channel, 0 or False for
        a good channel).

        See Also
        --------
        copy_data : Copy a data set to a new identifier.
        delete_data : Delete a data set by identifier.
        get_data : Return the data set by identifier.
        load_data : Create a data set from a file.
        set_data : Set a data set.
        unpack_arrays : Create a sherpa data object from arrays of data.

        Notes
        -----
        The data type identifier, which defaults to `Data1D`,
        determines the number, and order, of the required inputs.

        +------------+-----------------+--------------------+
        | Identifier | Required Fields |   Optional Fields  |
        +============+=================+====================+
        | Data1D     | x, y            | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+
        | Data1DInt  | xlo, xhi, y     | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+
        | Data2D     | x0, x1, y       | shape,             |
        |            |                 | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+
        | Data2DInt  | x0lo, x1lo,     | shape,             |
        |            | x0hi, x1hi, y   | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+
        | DataPHA    | channel, counts | statistical error, |
        |            |                 | systematic error,  |
        |            |                 | bin_lo, bin_hi,    |
        |            |                 | grouping, quality  |
        +------------+-----------------+--------------------+
        | DataIMG    | x0, x1, y       | shape,             |
        |            |                 | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+

        The ``shape`` argument should be a tuple giving the size of
        the data ``(ny,nx)``, and for the ``DataIMG`` case the arrays
        are 1D, not 2D.

        Examples
        --------

        Create a 1D data set with three points:

        >>> load_arrays(1, [10, 12, 15], [4.2, 12.1, 8.4])

        Create a 1D data set, with the identifier 'prof', from the
        arrays ``x`` (independent axis), ``y`` (dependent axis), and
        ``dy`` (statistical error on the dependent axis):

        >>> load_arrays('prof', x, y, dy)

        Explicitly define the type of the data set:

        >>> load_arrays('prof', x, y, dy, Data1D)

        Data set 1 is a histogram, where the bins cover the range
        1-3, 3-5, and 5-7 with values 4, 5, and 9 respectively.

        >>> load_arrays(1, [1, 3, 5], [3, 5, 7], [4, 5, 9], Data1DInt)

        Create an image data set:

        >>> ivals = np.arange(12)
        >>> y, x = np.mgrid[0:3, 0:4]
        >>> x = x.flatten()
        >>> y = y.flatten()
        >>> load_arrays('img', x, y, ivals, (3, 4), DataIMG)

        """
        self.set_data(id, self.unpack_arrays(*args))

    # DOC-TODO: should unpack_ascii be merged into this?
    def unpack_table(self, filename, ncols=2, colkeys=None, dstype=Data1D):
        """Unpack a FITS binary file into a data structure.

        Parameters
        ----------
        filename
           Identify the file to read: a file name, or a data structure
           representing the data to use, as used by the I/O backend in
           use by Sherpa: a ``TABLECrate`` for crates, as used by CIAO,
           or a list of AstroPy HDU objects.
        ncols : int, optional
           The number of columns to read in (the first `ncols` columns
           in the file). The meaning of the columns is determined by
           the `dstype` parameter.
        colkeys : array of str, optional
           An array of the column name to read in. The default is
           ``None``.
        dstype : optional
           The data class to use. The default is `Data1D` and it
           is expected to be derived from `sherpa.data.BaseData`.

        Returns
        -------
        instance
           The class of the returned object is controlled by the
           `dstype` parameter.

        See Also
        --------
        load_table : Load a FITS binary file as a data set.
        set_data : Set a data set.
        unpack_ascii : Unpack an ASCII file into a data structure.

        Examples
        --------

        Read in the first two columns of the file, as the independent
        (X) and dependent (Y) columns of a data set:

        >>> d = unpack_table('sources.fits')

        Read in the first three columns (the third column is taken to
        be the error on the dependent variable):

        >>> d = unpack_table('sources.fits', ncols=3)

        Read in from columns 'RMID' and 'SUR_BRI':

        >>> d = unpack_table('rprof.fits', colkeys=['RMID', 'SUR_BRI'])

        The first three columns are taken to be the two independent
        axes of a two-dimensional data set (``x0`` and ``x1``) and
        the dependent value (``y``):

        >>> d = unpack_table('fields.fits', ncols=3,
        ...                  dstype=sherpa.astro.data.Data2D)

        When using the Crates I/O library, the file name can include
        CIAO Data Model syntax, such as column selection. This can
        also be done using the `colkeys` parameter, as shown above:

        >>> d = unpack_table('rprof.fits[cols rmid,sur_bri,sur_bri_err]',
        ...                  ncols=3)

        """
        return sherpa.astro.io.read_table(filename, ncols, colkeys, dstype)

    # DOC-TODO: the field listing really should be somewhere else
    # as it's needed in multiple places (ideally in the
    # DataX class documentation, but users may not find it)
    # DOC-TODO: what do the shape arguments for Data2D/Data2DInt mean?
    def load_table(self, id, filename=None, ncols=2, colkeys=None,
                   dstype=Data1D):
        """Load a FITS binary file as a data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename
           Identify the file to read: a file name, or a data structure
           representing the data to use, as used by the I/O backend in
           use by Sherpa: a ``TABLECrate`` for crates, as used by CIAO,
           or a list of AstroPy HDU objects.
        ncols : int, optional
           The number of columns to read in (the first ``ncols`` columns
           in the file). The meaning of the columns is determined by
           the ``dstype`` parameter.
        colkeys : array of str, optional
           An array of the column name to read in. The default is
           ``None``.
        dstype : optional
           The data class to use. The default is `Data1D`.

        See Also
        --------
        load_arrays : Create a data set from array values.
        load_ascii : Load an ASCII file as a data set.
        load_image : Load an image as a data set.
        set_data : Set a data set.
        unpack_table : Unpack a FITS binary table into a data structure.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The column order for the different data types are as follows,
        where ``x`` indicates an independent axis and ``y`` the dependent
        axis:

        +------------+-----------------+--------------------+
        | Identifier | Required Fields |   Optional Fields  |
        +============+=================+====================+
        | Data1D     | x, y            | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+
        | Data1DInt  | xlo, xhi, y     | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+
        | Data2D     | x0, x1, y       | shape,             |
        |            |                 | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+
        | Data2DInt  | x0lo, x1lo,     | shape,             |
        |            | x0hi, x1hi, y   | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+

        Examples
        --------

        Read in the first two columns of the file, as the independent
        (X) and dependent (Y) columns of the default data set:

        >>> load_table('sources.fits')

        Read in the first three columns (the third column is taken to
        be the error on the dependent variable):

        >>> load_table('sources.fits', ncols=3)

        Read in from columns 'RMID' and 'SUR_BRI' into data set
        'prof':

        >>> load_table('prof', 'rprof.fits',
        ...            colkeys=['RMID', 'SUR_BRI'])

        The first three columns are taken to be the two independent
        axes of a two-dimensional data set (``x0`` and ``x1``) and
        the dependent value (``y``):

        >>> load_table('fields.fits', ncols=3,
        ...            dstype=sherpa.astro.data.Data2D)

        When using the Crates I/O library, the file name can include
        CIAO Data Model syntax, such as column selection. This can
        also be done using the ``colkeys`` parameter, as shown above:

        >>> load_table('prof',
        ...            'rprof.fits[cols rmid,sur_bri,sur_bri_err]',
        ...            ncols=3)

        Read in a data set using Crates:

        >>> cr = pycrates.read_file('table.fits')
        >>> load_table(cr)

        Read in a data set using AstroPy:

        >>> hdus = astropy.io.fits.open('table.fits')
        >>> load_table(hdus)

        """
        if filename is None:
            id, filename = filename, id

        self.set_data(id, self.unpack_table(filename, ncols, colkeys, dstype))

    # DOC-TODO: should unpack_ascii be merged into unpack_table?
    # DOC-TODO: I am going to ignore the crates support here as
    # it is somewhat meaningless, since the crate could
    # have been read from a FITS binary table.
    def unpack_ascii(self, filename, ncols=2, colkeys=None,
                     dstype=Data1D, sep=' ', comment='#'):
        """Unpack an ASCII file into a data structure.

        Parameters
        ----------
        filename : str
           The name of the file to read in. Selection of the relevant
           column depends on the I/O library in use (Crates or
           AstroPy).
        ncols : int, optional
           The number of columns to read in (the first `ncols` columns
           in the file). The meaning of the columns is determined by
           the `dstype` parameter.
        colkeys : array of str, optional
           An array of the column name to read in. The default is
           ``None``.
        sep : str, optional
           The separator character. The default is ``' '``.
        comment : str, optional
           The comment character. The default is ``'#'``.
        dstype : optional
           The data class to use. The default is `Data1D` and it
           is expected to be derived from `sherpa.data.BaseData`.

        Returns
        -------
        instance
           The type of the returned object is controlled by the
           `dstype` parameter.

        See Also
        --------
        load_ascii : Load an ASCII file as a data set.
        set_data : Set a data set.
        unpack_table : Unpack a FITS binary file into a data structure.

        Examples
        --------

        Read in the first two columns of the file, as the independent
        (X) and dependent (Y) columns of a data set:

        >>> d = unpack_ascii('sources.dat')

        Read in the first three columns (the third column is taken to
        be the error on the dependent variable):

        >>> d = unpack_ascii('sources.dat', ncols=3)

        Read in from columns 'col2' and 'col3':

        >>> d = unpack_ascii('tbl.dat', colkeys=['col2', 'col3'])

        The first three columns are taken to be the two independent
        axes of a two-dimensional data set (``x0`` and ``x1``) and
        the dependent value (``y``):

        >>> d = unpack_ascii('fields.dat', ncols=3,
        ...                  dstype=sherpa.astro.data.Data2D)

        When using the Crates I/O library, the file name can include
        CIAO Data Model syntax, such as column selection. This can
        also be done using the `colkeys` parameter, as shown above:

        >>> d = unpack_ascii('tbl.dat[cols rmid,sur_bri,sur_bri_err]',
        ...                  ncols=3)

        """
        return sherpa.astro.io.read_ascii(filename, ncols, colkeys, dstype,
                                          sep=sep, comment=comment)

    # DOC-TODO: I am going to ignore the crates support here as
    # it is somewhat meaningless, since the crate could
    # have been read from a FITS binary table.
    # DOC-TODO: how best to include datastack support?
    # DOC-TODO: what does shape mean here (how is it encoded)?
    def load_ascii(self, id, filename=None, ncols=2, colkeys=None,
                   dstype=Data1D, sep=' ', comment='#'):
        """Load an ASCII file as a data set.

        The standard behavior is to create a single data set, but
        multiple data sets can be loaded with this command, as
        described in the `sherpa.astro.datastack` module.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to read in. Selection of the relevant
           column depends on the I/O library in use (Crates or
           AstroPy).
        ncols : int, optional
           The number of columns to read in (the first ``ncols`` columns
           in the file). The meaning of the columns is determined by
           the ``dstype`` parameter.
        colkeys : array of str, optional
           An array of the column name to read in. The default is
           ``None``.
        sep : str, optional
           The separator character. The default is ``' '``.
        comment : str, optional
           The comment character. The default is ``'#'``.
        dstype : optional
           The data class to use. The default is `Data1D`.

        See Also
        --------
        load_ascii_with_errors : Load an ASCII file with asymmetric errors as a data set.
        load_table : Load a FITS binary file as a data set.
        load_image : Load an image as a data set.
        set_data : Set a data set.
        unpack_ascii : Unpack an ASCII file into a data structure.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The column order for the different data types are as follows,
        where ``x`` indicates an independent axis and ``y`` the
        dependent axis.

        +------------+-----------------+--------------------+
        | Identifier | Required Fields |   Optional Fields  |
        +============+=================+====================+
        | Data1D     | x, y            | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+
        | Data1DInt  | xlo, xhi, y     | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+
        | Data2D     | x0, x1, y       | shape,             |
        |            |                 | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+
        | Data2DInt  | x0lo, x1lo,     | shape,             |
        |            | x0hi, x1hi, y   | statistical error, |
        |            |                 | systematic error   |
        +------------+-----------------+--------------------+

        Examples
        --------

        Read in the first two columns of the file, as the independent
        (X) and dependent (Y) columns of the default data set:

        >>> load_ascii('sources.dat')

        Read in the first three columns (the third column is taken to
        be the error on the dependent variable):

        >>> load_ascii('sources.dat', ncols=3)

        Read in from columns 'RMID' and 'SUR_BRI' into data set
        'prof':

        >>> load_ascii('prof', 'rprof.dat',
        ...            colkeys=['RMID', 'SUR_BRI'])

        The first three columns are taken to be the two independent
        axes of a two-dimensional data set (``x0`` and ``x1``) and
        the dependent value (``y``):

        >>> load_ascii('fields.txt', ncols=3,
        ...            dstype=sherpa.astro.data.Data2D)

        When using the Crates I/O library, the file name can include
        CIAO Data Model syntax, such as column selection. This can
        also be done using the ``colkeys`` parameter, as shown above:

        >>> load_ascii('prof',
        ...            'rprof.dat[cols rmid,sur_bri,sur_bri_err]',
        ...            ncols=3)

        """
        if filename is None:
            id, filename = filename, id

        self.set_data(id, self.unpack_ascii(filename, ncols=ncols,
                                            colkeys=colkeys, dstype=dstype,
                                            sep=sep, comment=comment))

    # DOC-NOTE: also in sherpa.utils
    def unpack_data(self, filename, *args, **kwargs):
        """Create a sherpa data object from a file.

        The object returned by `unpack_data` can be used in a
        `set_data` call. The data types supported are those
        supported by `unpack_pha`, `unpack_image`, `unpack_table`,
        and `unpack_ascii`.

        Parameters
        ----------
        filename
           A file name or a data structure representing the data to
           use, as used by the I/O backend in use by Sherpa: e.g.  a
           ``PHACrateDataset``, ``TABLECrate``, or ``IMAGECrate`` for
           crates, as used by CIAO, or a list of AstroPy HDU objects.
        args
           The arguments supported by `unpack_pha`, `unpack_image`,
           `unpack_table`, and `unpack_ascii`.
        kwargs
           The keyword arguments supported by `unpack_pha`, `unpack_image`,
           `unpack_table`, and `unpack_ascii`.

        Returns
        -------
        instance
           The data set object.

        See Also
        --------
        get_data : Return the data set by identifier.
        load_arrays : Create a data set from array values.
        set_data : Set a data set.
        unpack_arrays : Create a sherpa data object from arrays of data.
        unpack_ascii : Unpack an ASCII file into a data structure.
        unpack_image : Create an image data structure.
        unpack_pha : Create a PHA data structure.
        unpack_table : Unpack a FITS binary file into a data structure.

        Examples
        --------

        Create a data object from the contents of the file "src.dat"
        and use it to create a Sherpa data set called "src":

        >>> dat = unpack_data('src.dat')
        >>> set_data('src', dat)

        """
        try:
            data = self.unpack_pha(filename, *args, **kwargs)
        except:
            try:
                data = self.unpack_image(filename, *args, **kwargs)
            except:
                try:
                    data = self.unpack_table(filename, *args, **kwargs)
                except:
                    # If this errors out then so be it
                    data = self.unpack_ascii(filename, *args, **kwargs)

        return data

    def load_ascii_with_errors(self, id, filename=None, colkeys=None, sep=' ',
                               comment='#', func=numpy.average, delta=False):
        """Load an ASCII file with asymmetric errors as a data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to read in. Selection of the relevant
           column depends on the I/O library in use (Crates or
           AstroPy).
        sep : str, optional
           The separator character. The default is ``' '``.
        comment : str, optional
           The comment character. The default is ``'#'``.
        func: python function, optional
           The function used to combine the lo and hi values to estimate
           an error. The function should take two arguments ``(lo, hi)``
           and return a single NumPy array, giving the per-bin error.
           The default function used is numpy.average.
        delta: boolean, optional
           The flag is used to indicate if the asymmetric errors for the
           third and fourth columns are delta values from the second (y)
           column or not.
           The default value is False

        See Also
        --------
        load_ascii: Load an ASCII file as a data set.
        load_arrays : Create a data set from array values.
        load_table : Load a FITS binary file as a data set.
        load_image : Load an image as a data set.
        resample_data : Resample data with asymmetric error bars.
        set_data : Set a data set.
        unpack_ascii : Unpack an ASCII file into a data structure.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The column order for the different data types are as follows,
        where ``x`` indicates an independent axis, ``y`` the dependent
        axis, the asymmetric errors ``elo`` and ``ehi``.

        +----------------------+-----------------+--------------------+
        | Identifier           | Required Fields |   Optional Fields  |
        +======================+=================+====================+
        | Data1DAsymmetricErrs | x, y, elo, ehi  |                    |
        +----------------------+-----------------+--------------------+

        Examples
        --------

        Read in the first four columns of the file, as the independent
        (X), dependent (Y), error low (ELO) and error high (EHI) columns
        of the default data set:

        >>> load_ascii_with_errors('sources.dat')

        Read in the first four columns (x, y, elo, ehi) where elo and ehi
        are of the form y - delta_lo and y + delta_hi, respectively.

        >>> load_ascii_with_errors('sources.dat', delta=True)

        Read in the first four columns (x, y, elo, ehi) where elo and ehi
        are of the form delta_lo and delta_hi, respectively.

        >>> def rms(lo, hi):
        ...     return numpy.sqrt(lo * lo + hi * hi)
        ...
        >>> load_ascii_with_errors('sources.dat', func=rms)

        Read in the first four columns (x, y, elo, ehi) where elo and ehi
        are of the form delta_lo and delta_hi, respectively. The `func`
        argument is used to calculate the error based on the elo and ehi
        column values.
        """

        if filename is None:
            id, filename = filename, id
        self.set_data(id, self.unpack_ascii(filename, ncols=4,
                                            colkeys=colkeys,
                                            dstype=Data1DAsymmetricErrs,
                                            sep=sep, comment=comment))

        data = self.get_data(id)

        if not delta:
            data.elo = data.y - data.elo
            data.ehi = data.ehi - data.y

        if func is numpy.average:
            staterror = func([data.elo, data.ehi], axis=0)
        else:
            staterror = func(data.elo, data.ehi)

        data.staterror = staterror

    def _load_data(self, id, datasets):
        """Load one or more datasets.

        Used by load_data and load_pha.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. For multi-dataset
           files, currently only PHA2, the id value indicates the
           first dataset: if it is an integer then the numbering
           starts at id, and if a string then a suffix of 1 to n is
           added.  If not given then the default identifier is used,
           as returned by `get_default_id`.
        datasets : Data instance or iterable of Data instances
           The data to load, either as a single item or, for
           multiple-dataset files, an iterable of them.

        """

        if not numpy.iterable(datasets):
            self.set_data(id, datasets)
            return

        # One issue with the following is that if there's
        # only one dataset in phasets and id is a string then the
        # output will be "foo1" rather than "foo" (when
        # id="foo").  DJB thinks we can live with this.
        #
        if id is None:
            id = self.get_default_id()

        num = len(datasets)
        ids = []
        for ctr, data in enumerate(datasets):
            try:
                idval = id + ctr
            except TypeError:
                # id is assumed to be a string
                idval = id + str(ctr + 1)

            self.set_data(idval, data)
            ids.append(idval)

        if num > 1:
            info("Multiple data sets have been input: " +
                 "{}-{}".format(ids[0], ids[-1]))
        else:
            info("One data set has been input: {}".format(ids[0]))

    # DOC-NOTE: also in sherpa.utils without the support for
    #           multiple datasets.
    #
    def load_data(self, id, filename=None, *args, **kwargs):
        # pylint: disable=W1113
        """Load a data set from a file.

        This loads a data set from the file, trying in order
        `load_pha`, `load_image`, `load_table`, then `load_ascii`.

        .. versionchanged:: 4.13.1
           The id argument is now used to define the first identifier
           when loading in a PHA2 file to match `load_pha` (previously
           the range always started at 1).

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. For multi-dataset
           files, currently only PHA2, the id value indicates the
           first dataset: if it is an integer then the numbering
           starts at id, and if a string then a suffix of 1 to n is
           added.  If not given then the default identifier is used,
           as returned by `get_default_id`.
        filename
           A file name or a data structure representing the data to
           use, as used by the I/O backend in use by Sherpa: e.g.  a
           ``PHACrateDataset``, ``TABLECrate``, or ``IMAGECrate`` for
           crates, as used by CIAO, or a list of AstroPy HDU objects.
        args
           The arguments supported by `load_pha`, `load_image`,
           `load_table`, and `load_ascii`.
        kwargs
           The keyword arguments supported by `load_pha`, `load_image`,
           `load_table`, and `load_ascii`.

        See Also
        --------
        load_arrays : Create a data set from array values.
        load_ascii : Load an ASCII file as a data set.
        load_image : Load an image as a data set.
        load_pha : Load a PHA data set.
        load_table : Load a FITS binary file as a data set.
        set_data : Set a data set.
        unpack_data : Create a sherpa data object from a file.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments,
        then they are interpreted as the `id` and `filename`
        parameters, respectively. The remaining parameters are
        expected to be given as named arguments.

        Examples
        --------

        >>> load_data('tbl.dat')

        >>> load_data('hist.dat', dstype=Data1DInt)

        >>> load_data('img', 'img.fits')
        >>> load_data('bg', 'img_bg.fits')

        >>> cols = ['rmid', 'sur_bri', 'sur_bri_err']
        >>> load_data(2, 'profile.fits', colkeys=cols)

        """
        if filename is None:
            id, filename = filename, id

        datasets = self.unpack_data(filename, *args, **kwargs)
        self._load_data(id, datasets)

    def unpack_image(self, arg, coord='logical',
                     dstype=sherpa.astro.data.DataIMG):
        """Create an image data structure.

        Parameters
        ----------
        arg
           Identify the data: a file name, or a data structure
           representing the data to use, as used by the I/O backend in
           use by Sherpa: an ``IMAGECrate`` for crates, as used by CIAO,
           or a list of AstroPy HDU objects.
        coord : { 'logical', 'image', 'physical', 'world', 'wcs' }, optional
           Ensure that the image contains the given coordinate system.
        dstype : optional
           The image class to use. The default is `DataIMG`.

        Returns
        -------
        img
           The class of the returned object is controlled by the
           ``dstype`` parameter.

        Raises
        ------
        sherpa.utils.err.DataErr
           If the image does not contain the requested coordinate
           system.

        See Also
        --------
        load_image : Load an image as a data set.
        set_data : Set a data set.

        Examples
        --------

        >>> img1 = unpack_img("img.fits")
        >>> set_data(img1)

        >>> img = unpack_img('img.fits', 'physical')

        Read in an image using Crates:

        >>> cr = pycrates.read_file('broad.img')
        >>> idata = unpack_img(cr)

        Read in an image using AstroPy:

        >>> hdus = astropy.io.fits.open('broad.img')
        >>> idata = unpack_img(hdus)

        """
        return sherpa.astro.io.read_image(arg, coord, dstype)

    def load_image(self, id, arg=None, coord='logical',
                   dstype=sherpa.astro.data.DataIMG):
        """Load an image as a data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        arg
           Identify the image data: a file name, or a data structure
           representing the data to use, as used by the I/O backend in
           use by Sherpa: an ``IMAGECrate`` for crates, as used by CIAO,
           or a list of AstroPy HDU objects.
        coord : { 'logical', 'image', 'physical', 'world', 'wcs' }
           The coordinate system to use. The 'image' option is the
           same as 'logical', and 'wcs' the same as 'world'.
        dstype : optional
           The data class to use. The default is `DataIMG`.

        See Also
        --------
        load_arrays : Create a data set from array values.
        load_ascii : Load an ASCII file as a data set.
        load_table : Load a FITS binary file as a data set.
        set_coord : Set the coordinate system to use for image analysis.
        set_data : Set a data set.
        unpack_image : Create an image data structure.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `arg` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `arg` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Examples
        --------

        Load the image from the file "img.fits" into the default data
        set:

        >>> load_image('img.fits')

        Set the 'bg' data set to the contents of the file
        "img_bg.fits":

        >>> load_image('bg', 'img_bg.fits')

        """
        if arg is None:
            id, arg = arg, id
        self.set_data(id, self.unpack_image(arg, coord, dstype))

    # DOC-TODO: what does this return when given a PHA2 file?
    def unpack_pha(self, arg, use_errors=False):
        """Create a PHA data structure.

        Any instrument or background data sets referenced in the
        header of the PHA file - e.g. with the ANCRFILE, RESPFILE,
        and BACKFILE keywords - will also be loaded.

        Parameters
        ----------
        arg
           Identify the PHA file: a file name, or a data structure
           representing the data to use, as used by the I/O backend in
           use by Sherpa: a ``TABLECrate`` for crates, as used by CIAO,
           or a list of AstroPy HDU objects.
        use_errors : bool, optional
           If ``True`` then the statistical errors are taken from the
           input data, rather than calculated by Sherpa from the
           count values. The default is ``False``.

        Returns
        -------
        pha : a `sherpa.astro.data.DataPHA` instance

        See Also
        --------
        load_pha : Load a file as a PHA data set.
        pack_pha : Convert a PHA data set into a file structure.
        set_data : Set a data set.

        Examples
        --------

        >>> pha1 = unpack_arf("src1.pi")
        >>> pha2 = unpack_arf("field.pi")
        >>> set_data(1, pha1)
        >>> set_bkg(1, pha2)

        Read in a PHA file using Crates:

        >>> cr = pycrates.read_file("src.fits")
        >>> pha = unpack_pha(cr)

        Read in a PHA file using AstroPy:

        >>> hdus = astropy.io.fits.open("src.fits")
        >>> pha = unpack_pha(hdus)

        """
        use_errors = sherpa.utils.bool_cast(use_errors)
        return sherpa.astro.io.read_pha(arg, use_errors)

    # DOC-TODO: what does this return when given a PHA2 file?
    def unpack_bkg(self, arg, use_errors=False):
        """Create a PHA data structure for a background data set.

        Any instrument information referenced in the header of the PHA
        file - e.g. with the ANCRFILE and RESPFILE, keywords - will
        also be loaded. Unlike `unpack_pha`, background files will not
        be loaded.

        Parameters
        ----------
        arg
           Identify the PHA file: a file name, or a data structure
           representing the data to use, as used by the I/O backend in
           use by Sherpa: a ``TABLECrate`` for crates, as used by CIAO,
           or a list of AstroPy HDU objects.
        use_errors : bool, optional
           If ``True`` then the statistical errors are taken from the
           input data, rather than calculated by Sherpa from the
           count values. The default is ``False``.

        Returns
        -------
        pha : a `sherpa.astro.data.DataPHA` instance

        See Also
        --------
        load_bkg : Load the background from a file and add it to a PHA data set.
        set_bkg : Set the background for a data set.

        Examples
        --------

        >>> pha1 = unpack_arf("src1.pi")
        >>> pha2 = unpack_bkg("field.pi")
        >>> set_data(1, pha1)
        >>> set_bkg(1, pha2)

        Read in a PHA file using Crates:

        >>> cr = pycrates.read_file("bg.fits")
        >>> pha = unpack_pha(cr)

        Read in a PHA file using AstroPy:

        >>> hdus = astropy.io.fits.open("bg.fits")
        >>> pha = unpack_pha(hdus)

        """
        use_errors = sherpa.utils.bool_cast(use_errors)
        return sherpa.astro.io.read_pha(arg, use_errors, True)

    # DOC-TODO: how best to include datastack support?
    def load_pha(self, id, arg=None, use_errors=False):
        """Load a PHA data set.

        This will load the PHA data and any related information, such
        as ARF, RMF, and background. The background is loaded but
        *not* subtracted. Any grouping information in the file will be
        applied to the data. The quality information is read in, but
        *not* automatically applied. See `subtract` and `ignore_bad`.

        The standard behavior is to create a single data set, but
        multiple data sets can be loaded with this command, as
        described in the `sherpa.astro.datastack` module.

        .. versionchanged:: 4.12.2
           The id argument is now used to define the first identifier
           when loading in a PHA2 file (previously they always used
           the range 1 to number of files).

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. For PHA2 files,
           that is those that contain multiple datasets, the id value
           indicates the first dataset: if it is an integer then the
           numbering starts at id, and if a string then a suffix of 1
           to n is added.  If not given then the default identifier is
           used, as returned by `get_default_id`.
        arg
           Identify the data to read: a file name, or a data structure
           representing the data to use, as used by the I/O backend in
           use by Sherpa: a ``PHACrateDataset`` for crates, as used by
           CIAO, or a list of AstroPy HDU objects.
        use_errors : bool, optional
           If ``True`` then the statistical errors are taken from the
           input data, rather than calculated by Sherpa from the
           count values. The default is ``False``.

        See Also
        --------
        ignore_bad : Exclude channels marked as bad in a PHA data set.
        load_arf : Load an ARF from a file and add it to a PHA data set.
        load_bkg : Load the background from a file and add it to a PHA data set.
        load_rmf : Load a RMF from a file and add it to a PHA data set.
        pack_pha : Convert a PHA data set into a file structure.
        save_pha : Save a PHA data set to a file.
        subtract : Subtract the background estimate from a data set.
        unpack_pha : Create a PHA data structure.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `arg` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `arg` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The `minimum_energy` setting of the `ogip` section of the
        Sherpa configuration file determines the behavior when an
        ARF with a minimum energy of 0 is read in. The default is
        to replace the 0 by the value 1e-10, which will also cause
        a warning message to be displayed.

        Examples
        --------

        Load the PHA file 'src.pi' into the default data set, and
        automatically load the ARF, RMF, and background from the files
        pointed to by the ANCRFILE, RESPFILE, and BACKFILE keywords in
        the file. The background is then subtracted and any 'bad
        quality' bins are removed:

        >>> load_pha('src.pi')
        read ARF file src.arf
        read RMF file src.rmf
        read background file src_bkg.pi
        >>> subtract()
        >>> ignore_bad()

        Load two files into data sets 'src' and 'bg':

        >>> load_pha('src', 'x1.fits')
        >>> load_pha('bg', 'x2.fits')

        If a type II PHA data set is loaded, then multiple data sets
        will be created, one for each order. The default behavior is
        to use the dataset identifiers 1 to the number of files.

        >>> clean()
        >>> load_pha('src.pha2')
        >>> list_data_ids()
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

        If given an identifier as the first argument then this is used
        to start the numbering scheme for PHA2 files. If id is an
        integer then the numbers go from id:

        >>> clean()
        >>> load_pha(20, 'src.pha2')
        >>> list_data_ids()
        [20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31]

        If the id is a string then the identifier is formed by adding
        the number of the dataset (starting at 1) to the end of
        id. Note that the `list_data_ids` routine does not guarantee
        an ordering to the output (as shown below):

        >>> clean()
        >>> load_pha('x', 'src.pha2')
        >>> list_data_ids()
        ['x1', 'x10', 'x11', 'x12', 'x2', 'x3', 'x4', 'x5', 'x6',
         'x7', 'x8', 'x9']

        Create the data set from the data read in by Crates:

        >>> pha = pycrates.read_pha('src.pi')
        >>> load_pha(pha)
        read ARF file src.arf
        read RMF file src.rmf
        read background file src_bkg.pi

        Create the data set from the data read in by AstroPy:

        >>> hdus = astropy.io.fits.open('src.pi')
        >>> load_pha(hdus)
        read ARF file src.arf
        read RMF file src.rmf
        read background file src_bkg.pi

        The default behavior is to calculate the errors based on the
        counts values and the choice of statistic -
        e.g. ``chi2gehrels`` or ``chi2datavar`` - but the statistical
        errors from the input file can be used instead by setting
        ``use_errors`` to ``True``:

        >>> load_pha('source.fits', use_errors=True)

        """
        if arg is None:
            id, arg = arg, id

        phasets = self.unpack_pha(arg, use_errors)
        self._load_data(id, phasets)

    def _get_pha_data(self, id):
        """Ensure the dataset is a PHA"""
        data = self.get_data(id)
        if not isinstance(data, sherpa.astro.data.DataPHA):
            raise ArgumentErr('nopha', self._fix_id(id))
        return data

    def _get_img_data(self, id):
        """Ensure the dataset is an image"""
        data = self.get_data(id)
        if not isinstance(data, sherpa.astro.data.DataIMG):
            raise ArgumentErr('noimg', self._fix_id(id))
        return data

    # def _read_error(self, filename, *args, **kwargs):
    #     err = None
    #     try:
    #         err = sherpa.astro.io.backend.get_ascii_data(filename, *args,
    #                                                    **kwargs)[1].pop()
    #     except:
    #         try:
    #             err = sherpa.astro.io.backend.get_table_data(filename, *args,
    #                                                        **kwargs)[1].pop()
    #         except:
    #             try:
    #                 err = sherpa.astro.io.read_image(filename, *args, **kwargs)
    #                 err = err.get_dep()
    #             except:
    #                 raise

    #     return err

    # DOC-NOTE: also in sherpa.utils
    # DOC-TODO: does ncols make sense here? (have removed for now)
    #
    def load_filter(self, id, filename=None, bkg_id=None, ignore=False,
                    ncols=2, *args, **kwargs):
        # pylint: disable=W1113
        """Load the filter array from a file and add to a data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file that contains the filter
           information. This file can be a FITS table or an ASCII
           file. Selection of the relevant column depends on the I/O
           library in use (Crates or AstroPy).
        bkg_id : int or str, optional
           Set if the filter array should be associated with the
           background associated with the data set.
        ignore : bool, optional
           If ``False`` (the default) then include bins with a non-zero
           filter value, otherwise exclude these bins.
        colkeys : array of str, optional
           An array of the column name to read in. The default is
           ``None``.
        sep : str, optional
           The separator character. The default is ``' '``.
        comment : str, optional
           The comment character. The default is ``'#'``.

        See Also
        --------
        get_filter : Return the filter expression for a data set.
        ignore : Exclude data from the fit.
        notice : Include data in the fit.
        save_filter : Save the filter array to a file.
        set_filter : Set the filter array of a data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Examples
        --------

        Read in the first column of the file and apply it to the
        default data set:

        >>> load_filter('filt.dat')

        Select the FILTER column of the file:

        >>> load_filter(2, 'filt.dat', colkeys=['FILTER'])

        When using Crates as the I/O library, the above can
        also be written as

        >>> load_filter(2, 'filt.dat[cols filter]')

        Read in a filter for an image. The image must match the size
        of the data and, as ``ignore=True``, pixels with a non-zero
        value are excluded (rather than included):

        >>> load_filter('img', 'filt.img', ignore=True)

        """
        if filename is None:
            id, filename = filename, id

        self.set_filter(id, self._read_user_model(filename, *args, **kwargs)[1],
                        bkg_id=bkg_id, ignore=ignore)

    # DOC-TODO: does ncols make sense here? (have removed for now)
    # DOC-TODO: prob. needs a review as the existing ahelp documentation
    # talks about 2 cols, but experimentation suggests 1 col.
    #
    def load_grouping(self, id, filename=None, bkg_id=None, *args, **kwargs):
        # pylint: disable=W1113
        """Load the grouping scheme from a file and add to a PHA data set.

        This function sets the grouping column but does not
        automatically group the data, since the quality array may also
        need updating. The `group` function will apply the grouping
        information.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file that contains the grouping
           information. This file can be a FITS table or an ASCII
           file. Selection of the relevant column depends on the I/O
           library in use (Crates or AstroPy).
        bkg_id : int or str, optional
           Set if the grouping scheme should be associated with the
           background associated with the data set.
        colkeys : array of str, optional
           An array of the column name to read in. The default is
           ``None``.
        sep : str, optional
           The separator character. The default is ``' '``.
        comment : str, optional
           The comment character. The default is ``'#'``.

        See Also
        --------
        get_grouping : Return the gouping array for a PHA data set.
        group : Turn on the grouping for a PHA data set.
        load_quality : Load the quality array from a file and add to a PHA data set.
        save_grouping : Save the grouping scheme to a file.
        set_grouping : Apply a set of grouping flags to a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        There is no check made to see if the grouping array contains
        valid data.

        Examples
        --------

        When using Crates as the I/O library, select the grouping
        column from the file 'src.pi', and use it to set the
        values in the default data set:

        >>> load_grouping('src.pi[cols grouping]')

        Use the ``colkeys`` option to define the column in the input
        file:

        >>> load_grouping('src.pi', colkeys=['grouping'])

        Load the first column in 'grp.dat' and use it to populate
        the grouping array of the data set called 'core'.

        >>> load_grouping('core', 'grp.dat')

        Use `group_counts` to calculate a grouping scheme for the
        data set labelled 'src1', save this scheme to the file
        'grp.dat', and then load this scheme in for data set
        'src2'.

        >>> group_counts('src1', 10)
        >>> save_grouping('src1', 'grp.dat')
        >>> load_grouping('src2', 'grp.dat', colkeys=['groups'])

        """
        if filename is None:
            id, filename = filename, id

        grouping = self._read_user_model(filename, *args, **kwargs)[1]
        self.set_grouping(id, grouping, bkg_id=bkg_id)

    def load_quality(self, id, filename=None, bkg_id=None, *args, **kwargs):
        # pylint: disable=W1113
        """Load the quality array from a file and add to a PHA data set.

        This function sets the quality column but does not
        automatically ignore any columns marked as "bad". Use the
        `ignore_bad` function to apply the new quality information.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file that contains the quality
           information. This file can be a FITS table or an ASCII
           file. Selection of the relevant column depends on the I/O
           library in use (Crates or AstroPy).
        bkg_id : int or str, optional
           Set if the quality array should be associated with the
           background associated with the data set.
        colkeys : array of str, optional
           An array of the column name to read in. The default is
           ``None``.
        sep : str, optional
           The separator character. The default is ``' '``.
        comment : str, optional
           The comment character. The default is ``'#'``.

        See Also
        --------
        get_quality : Return the quality array for a PHA data set.
        ignore_bad : Exclude channels marked as bad in a PHA data set.
        load_grouping : Load the grouping scheme from a file and add to a PHA data set.
        save_quality: Save the quality array to a file.
        set_quality : Apply a set of quality flags to a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        There is no check made to see if the quality array contains
        valid data.

        Examples
        --------

        When using Crates as the I/O library, select the quality
        column from the file 'src.pi', and use it to set the
        values in the default data set:

        >>> load_quality('src.pi[cols quality]')

        Use the ``colkeys`` option to define the column in the input
        file:

        >>> load_quality('src.pi', colkeys=['quality'])

        Load the first column in 'grp.dat' and use it to populate
        the quality array of the data set called 'core'.

        >>> load_quality('core', 'grp.dat')

        """
        if filename is None:
            id, filename = filename, id

        self.set_quality(id,
                         self._read_user_model(filename, *args, **kwargs)[1], bkg_id=bkg_id)

    def set_filter(self, id, val=None, bkg_id=None, ignore=False):
        """Set the filter array of a data set.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        val : array
           The array of filter values (``0`` or ``1``). The size should
           match the array returned by `get_dep`.
        bkg_id : int or str, optional
           Set to identify which background component to set. The
           default value (``None``) means that this is for the source
           component of the data set.
        ignore : bool, optional
           If ``False`` (the default) then include bins with a non-zero
           filter value, otherwise exclude these bins.

        See Also
        --------
        get_dep : Return the dependent axis of a data set.
        get_filter : Return the filter expression for a data set.
        ignore : Exclude data from the fit.
        load_filter : Load the filter array from a file and add to a data set.
        notice : Include data in the fit.
        save_filter : Save the filter array to a file.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `val` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `val` parameters,
        respectively.

        Examples
        --------

        Ignore those bins with a value less 20.

        >>> d = get_dep()
        >>> set_filter(d >= 20)

        """
        if val is None:
            val, id = id, val

        filter = numpy.asarray(val, dtype=numpy.bool_)

        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        if numpy.iterable(d.mask):
            if len(d.mask) == len(filter):
                if not ignore:
                    d.mask |= filter
                else:
                    d.mask &= ~filter
            else:
                raise DataErr('mismatch', len(d.mask), len(filter))
        else:
            if len(d.get_y(False)) == len(filter):
                if not ignore:
                    d.mask = filter
                else:
                    d.mask = ~filter
            else:
                raise DataErr('mismatch', len(d.get_y(False)), len(filter))

    # DOC-NOTE: also in sherpa.utils
    # DOC-TODO: does ncols make sense here? (have removed for now)
    def load_staterror(self, id, filename=None, bkg_id=None, *args, **kwargs):
        # pylint: disable=W1113
        """Load the statistical errors from a file.

        Read in a column or image from a file and use the values
        as the statistical errors for a data set. This over rides
        the errors calculated by any statistic, such as
        ``chi2gehrels`` or ``chi2datavar``.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to read in. Supported formats depends
           on the I/O library in use (Crates or AstroPy) and the
           type of data set (e.g. 1D or 2D).
        bkg_id : int or str, optional
           Set to identify which background component to set. The
           default value (``None``) means that this is for the source
           component of the data set.
        colkeys : array of str, optional
           An array of the column name to read in. The default is
           ``None``.
        sep : str, optional
           The separator character. The default is ``' '``.
        comment : str, optional
           The comment character. The default is ``'#'``.

        See Also
        --------
        get_staterror : Return the statistical error on the dependent axis of a data set.
        load_syserror : Load the systematic errors from a file.
        set_staterror : Set the statistical errors on the dependent axis of a data set.
        set_stat : Set the statistical method.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Examples
        --------

        Read in the first column from 'tbl.dat':

        >>> load_staterror('tbl.dat')

        Use the column labelled 'col3'

        >>> load_staterror('tbl.dat', colkeys=['col3'])

        When using the Crates I/O library, the file name can include
        CIAO Data Model syntax, such as column selection:

        >>> load_staterror('tbl.dat[cols col3]')

        Read in the first column from the file 'errors.fits' as the
        statistical errors for the 'core' data set:

        >>> load_staterror('core', 'errors.fits')

        The data set labelled 'img' is loaded from the file
        'image.fits' and the statistical errors from 'err.fits'.
        The dimensions of the two images must be the same.

        >>> load_image('img', 'image.fits')
        >>> load_staterror('img', 'err.fits')

        """
        if filename is None:
            id, filename = filename, id

        self.set_staterror(id,
                           self._read_user_model(filename, *args, **kwargs)[1], bkg_id=bkg_id)

    # DOC-NOTE: also in sherpa.utils
    # DOC-NOTE: is ncols really 2 here? Does it make sense?
    def load_syserror(self, id, filename=None, bkg_id=None, *args, **kwargs):
        # pylint: disable=W1113
        """Load the systematic errors from a file.

        Read in a column or image from a file and use the values
        as the systematic errors for a data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to read in. Supported formats depends
           on the I/O library in use (Crates or AstroPy) and the
           type of data set (e.g. 1D or 2D).
        bkg_id : int or str, optional
           Set to identify which background component to set. The
           default value (``None``) means that this is for the source
           component of the data set.
        ncols : int, optional
           The number of columns to read in (the first ``ncols`` columns
           in the file).
        colkeys : array of str, optional
           An array of the column name to read in. The default is
           ``None``.
        sep : str, optional
           The separator character. The default is ``' '``.
        comment : str, optional
           The comment character. The default is ``'#'``.

        See Also
        --------
        get_syserror : Return the systematic error on the dependent axis of a data set.
        load_staterror : Load the statistical errors from a file.
        set_syserror : Set the systematic errors on the dependent axis of a data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Examples
        --------

        Read in the first column from 'tbl.dat':

        >>> load_syserror('tbl.dat')

        Use the column labelled 'col3'

        >>> load_syserror('tbl.dat', colkeys=['col3'])

        When using the Crates I/O library, the file name can include
        CIAO Data Model syntax, such as column selection:

        >>> load_syserror('tbl.dat[cols col3]')

        Read in the first column from the file 'errors.fits' as the
        systematic errors for the 'core' data set:

        >>> load_syserror('core', 'errors.fits')

        The data set labelled 'img' is loaded from the file
        'image.fits' and the systematic errors from 'syserr.fits'.
        The dimensions of the two images must be the same.

        >>> load_image('img', 'image.fits')
        >>> load_syserror('img', 'syserr.fits')

        """
        if filename is None:
            id, filename = filename, id

        self.set_syserror(id,
                          self._read_user_model(filename, *args, **kwargs)[1], bkg_id=bkg_id)

    # also in sherpa.utils
    def set_dep(self, id, val=None, bkg_id=None):
        """Set the dependent axis of a data set.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        val : array
           The array of values for the dependent axis.
        bkg_id : int or str, optional
           Set to identify which background component to set. The
           default value (``None``) means that this is for the source
           component of the data set.

        See Also
        --------
        dataspace1d : Create the independent axis for a 1D data set.
        dataspace2d : Create the independent axis for a 2D data set.
        get_dep : Return the dependent axis of a data set.
        load_arrays : Create a data set from array values.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `val` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `val` parameters,
        respectively.

        Examples
        --------

        Create a 1D data set with values at (0,4), (2,10), (4,12),
        (6,8), (8,2), and (10,12):

        >>> dataspace1d(0, 10, 2, dstype=Data1D)
        >>> set_dep([4, 10, 12, 8, 2, 12])

        Set the values for the source and background of the data set
        'src':

        >>> set_dep('src', y1)
        >>> set_dep('src', bg1, bkg_id=1)

        """
        if val is None:
            val, id = id, val
        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)

        dep = None
        if isinstance(d, sherpa.astro.data.DataPHA):
            if numpy.iterable(val):
                dep = numpy.asarray(val, SherpaFloat)
            else:
                val = SherpaFloat(val)
                dep = numpy.array([val] * len(d.channel))
            d.counts = dep
        else:
            if numpy.iterable(val):
                dep = numpy.asarray(val, SherpaFloat)
            else:
                val = SherpaFloat(val)
                dep = numpy.array([val] * len(d.get_indep()[0]))
            d.y = dep

    set_counts = set_dep

    # DOC-NOTE: also in sherpa.utils
    def set_staterror(self, id, val=None, fractional=False, bkg_id=None):
        """Set the statistical errors on the dependent axis of a data set.

        These values over-ride the errors calculated by any statistic,
        such as ``chi2gehrels`` or ``chi2datavar``.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        val : array or scalar
           The systematic error.
        fractional : bool, optional
           If ``False`` (the default value), then the `val` parameter is
           the absolute value, otherwise the `val` parameter
           represents the fractional error, so the absolute value is
           calculated as ``get_dep() * val`` (and `val` must be
           a scalar).
        bkg_id : int or str, optional
           Set to identify which background component to set. The
           default value (``None``) means that this is for the source
           component of the data set.

        See Also
        --------
        load_staterror : Load the statistical errors from a file.
        load_syserror : Load the systematic errors from a file.
        set_syserror : Set the systematic errors on the dependent axis of a data set.
        get_error : Return the errors on the dependent axis of a data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `val` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `val` parameters,
        respectively.

        Examples
        --------

        Set the statistical error for the default data set to the value
        in ``dys`` (a scalar or an array):

        >>> set_staterror(dys)

        Set the statistical error on the 'core' data set to be 5% of
        the data values:

        >>> set_staterror('core', 0.05, fractional=True)

        """
        if val is None:
            val, id = id, val
        err = None

        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)

        fractional = sherpa.utils.bool_cast(fractional)
        if numpy.iterable(val):
            err = numpy.asarray(val, SherpaFloat)
        elif val is not None:
            val = SherpaFloat(val)
            if fractional:
                err = val * d.get_dep()
            else:
                err = numpy.array([val] * len(d.get_dep()))
        d.staterror = err

    # DOC-NOTE: also in sherpa.utils
    def set_syserror(self, id, val=None, fractional=False, bkg_id=None):
        """Set the systematic errors on the dependent axis of a data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        val : array or scalar
           The systematic error.
        fractional : bool, optional
           If ``False`` (the default value), then the `val` parameter is
           the absolute value, otherwise the `val` parameter
           represents the fractional error, so the absolute value is
           calculated as ``get_dep() * val`` (and `val` must be
           a scalar).
        bkg_id : int or str, optional
           Set to identify which background component to set. The
           default value (``None``) means that this is for the source
           component of the data set.

        See Also
        --------
        load_staterror : Set the statistical errors on the dependent axis of a data set.
        load_syserror : Set the systematic errors on the dependent axis of a data set.
        set_staterror : Set the statistical errors on the dependent axis of a data set.
        get_error : Return the errors on the dependent axis of a data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `val` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `val` parameters,
        respectively.

        Examples
        --------

        Set the systematic error for the default data set to the value
        in ``dys`` (a scalar or an array):

        >>> set_syserror(dys)

        Set the systematic error on the 'core' data set to be 5% of
        the data values:

        >>> set_syserror('core', 0.05, fractional=True)

        """
        if val is None:
            val, id = id, val
        err = None

        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        fractional = sherpa.utils.bool_cast(fractional)

        if numpy.iterable(val):
            err = numpy.asarray(val, SherpaFloat)
        elif val is not None:
            val = SherpaFloat(val)
            if fractional:
                err = val * d.get_dep()
            else:
                err = numpy.array([val] * len(d.get_dep()))
        d.syserror = err

    def set_exposure(self, id, exptime=None, bkg_id=None):
        """Change the exposure time of a PHA data set.

        The exposure time of a PHA data set is taken from the
        ``EXPOSURE`` keyword in its header, but it can be changed
        once the file has been loaded.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        exptime : num
           The exposure time, in seconds.
        bkg_id : int or str, optional
           Set to identify which background component to set.  The
           default value (``None``) means that this is for the source
           component of the data set.

        See Also
        --------
        get_exposure : Return the exposure time of a PHA data set.
        set_areascal : Change the fractional area factor of a PHA data set.
        set_backscal : Change the area scaling of a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `exptime` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `exptime` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Examples
        --------

        Increase the exposure time of the default data set by 5 per
        cent.

        >>> etime = get_exposure()
        >>> set_exposure(etime * 1.05)

        Use the EXPOSURE value from the ARF, rather than the
        value from the PHA file, for data set 2:

        >>> set_exposure(2, get_arf(2).exposure)

        Set the exposure time of the second background component
        of the 'jet' data set.

        >>> set_exposure('jet', 12324.45, bkg_id=2)

        """
        if exptime is None:
            exptime, id = id, exptime

        if exptime is not None:
            exptime = SherpaFloat(exptime)

        if bkg_id is not None:
            self.get_bkg(id, bkg_id).exposure = exptime
        else:
            self._get_pha_data(id).exposure = exptime

    def set_backscal(self, id, backscale=None, bkg_id=None):
        """Change the area scaling of a PHA data set.

        The area scaling factor of a PHA data set is taken from the
        BACKSCAL keyword or column, but it can be changed once the
        file has been loaded.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        backscale : number or array
           The scaling factor.
        bkg_id : int or str, optional
           Set to identify which background component to set.  The
           default value (``None``) means that this is for the source
           component of the data set.

        See Also
        --------
        get_backscal : Return the area scaling of a PHA data set.
        set_areascal : Change the fractional area factor of a PHA data set.
        set_exposure : Change the exposure time of a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `backscale` parameter. If given two un-named arguments,
        then they are interpreted as the `id` and `backscale`
        parameters, respectively. The remaining parameters are
        expected to be given as named arguments.

        """
        if backscale is None:
            backscale, id = id, backscale

        if numpy.iterable(backscale):
            backscale = numpy.asarray(backscale)
        elif backscale is not None:
            backscale = SherpaFloat(backscale)

        if bkg_id is not None:
            self.get_bkg(id, bkg_id).backscal = backscale
        else:
            self._get_pha_data(id).backscal = backscale

    # DOC-TODO: the description needs improving.
    def set_areascal(self, id, area=None, bkg_id=None):
        """Change the fractional area factor of a PHA data set.

        The area scaling factor of a PHA data set is taken from the
        AREASCAL keyword, but it can be changed once the file has been
        loaded.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        area : number
           The scaling factor.
        bkg_id : int or str, optional
           Set to identify which background component to set.  The
           default value (``None``) means that this is for the source
           component of the data set.

        See Also
        --------
        get_areascal : Return the fractional area factor of a PHA data set.
        set_backscal : Change the area scaling of a PHA data set.
        set_exposure : Change the exposure time of a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `area` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `area` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        """
        if area is None:
            area, id = id, area

        if area is not None:
            area = SherpaFloat(area)

        if bkg_id is not None:
            self.get_bkg(id, bkg_id).areascal = area
        else:
            self._get_pha_data(id).areascal = area

    # DOC-NOTE: also in sherpa.utils, where it does not have
    #           the bkg_id parameter.
    #
    def get_staterror(self, id=None, filter=False, bkg_id=None):
        """Return the statistical error on the dependent axis of a data set.

        The function returns the statistical errors on the values
        (dependenent axis) of a data set, or its background. These
        may have been set explicitly - either when the data set was
        created or with a call to `set_staterror` - or as defined by
        the chosen fit statistic (such as "chi2gehrels").

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filter : bool, optional
           Should the filter attached to the data set be applied to
           the return value or not. The default is ``False``.
        bkg_id : int or str, optional
           Set if the values returned should be from the given
           background component, instead of the source data set.

        Returns
        -------
        staterrors : array
           The statistical error for each data point. This may be
           estimated from the data (e.g. with the ``chi2gehrels``
           statistic) or have been set explicitly (`set_staterror`).
           For PHA data sets, the return array will match the grouping
           scheme applied to the data set. The size of this array
           depends on the `filter` argument.

        Raises
        ------
        sherpa.utils.err.IdentifierErr
           If the data set does not exist.

        See Also
        --------
        get_error : Return the errors on the dependent axis of a data set.
        get_indep : Return the independent axis of a data set.
        get_syserror : Return the systematic errors on the dependent axis of a data set.
        list_data_ids : List the identifiers for the loaded data sets.
        set_staterror : Set the statistical errors on the dependent axis of a data set.

        Notes
        -----
        The default behavior is to not apply any filter defined on the
        independent axes to the results, so that the return value is for
        all points (or bins) in the data set. Set the `filter` argument
        to `True` to apply this filter.

        Examples
        --------

        If not explicitly given, the statistical errors on a data set
        may be calculated from the data values (the independent axis),
        depending on the chosen statistic:

        >>> load_arrays(1, [10, 15, 19], [4, 5, 9])
        >>> set_stat('chi2datavar')
        >>> get_staterror()
        array([ 2.        ,  2.23606798,  3.        ])
        >>> set_stat('chi2gehrels')
        >>> get_staterror()
        array([ 3.17944947,  3.39791576,  4.122499  ])

        If the statistical errors are set - either when the data set
        is created or with a call to `set_staterror` - then these values
        will be used, no matter the statistic:

        >>> load_arrays(1, [10, 15, 19], [4, 5, 9], [2, 3, 5])
        >>> set_stat('chi2datavar')
        >>> get_staterror()
        array([2, 3, 5])
        >>> set_stat('chi2gehrels')
        >>> get_staterror()
        array([2, 3, 5])

        """
        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        return d.get_staterror(filter, self.get_stat().calc_staterror)

    # DOC-NOTE: also in sherpa.utils, where it does not have
    #           the bkg_id parameter.
    #
    def get_syserror(self, id=None, filter=False, bkg_id=None):
        """Return the systematic error on the dependent axis of a data set.

        The function returns the systematic errors on the values
        (dependenent axis) of a data set, or its background. It is
        an error if called on a data set with no systematic errors
        (which are set with `set_syserror`).

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filter : bool, optional
           Should the filter attached to the data set be applied to
           the return value or not. The default is ``False``.
        bkg_id : int or str, optional
           Set if the values returned should be from the given
           background component, instead of the source data set.

        Returns
        -------
        syserrors : array
           The systematic error for each data point. The size of this
           array depends on the `filter` argument.

        Raises
        ------
        sherpa.utils.err.DataErr
           If the data set has no systematic errors.
        sherpa.utils.err.IdentifierErr
           If the data set does not exist.

        See Also
        --------
        get_error : Return the errors on the dependent axis of a data set.
        get_indep : Return the independent axis of a data set.
        get_staterror : Return the statistical errors on the dependent axis of a data set.
        list_data_ids : List the identifiers for the loaded data sets.
        set_syserror : Set the systematic errors on the dependent axis of a data set.

        Notes
        -----
        The default behavior is to not apply any filter defined on the
        independent axes to the results, so that the return value is for
        all points (or bins) in the data set. Set the `filter` argument
        to `True` to apply this filter.

        Examples
        --------

        Return the systematic error for the default data set:

        >>> yerr = get_syserror()

        Return an array that has been filtered to match the data:

        >>> yerr = get_syserror(filter=True)

        Return the filtered errors for data set "core":

        >>> yerr = get_syserror("core", filter=True)

        """
        d = self.get_data(id)
        id = self._fix_id(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        err = d.get_syserror(filter)
        if err is None or not numpy.iterable(err):
            raise DataErr('nosyserr', id)
        return err

    # DOC-NOTE: also in sherpa.utils, where it does not have
    #           the bkg_id parameter.
    #
    def get_error(self, id=None, filter=False, bkg_id=None):
        """Return the errors on the dependent axis of a data set.

        The function returns the total errors (a quadrature addition
        of the statistical and systematic errors) on the values
        (dependent axis) of a data set or its background. The individual
        components can be retrieved with the `get_staterror` and
        `get_syserror` functions.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filter : bool, optional
           Should the filter attached to the data set be applied to
           the return value or not. The default is ``False``.
        bkg_id : int or str, optional
           Set if the values returned should be from the given
           background component, instead of the source data set.

        Returns
        -------
        errors : array
           The error for each data point, formed by adding the
           statistical and systematic errors in quadrature.
           For PHA data sets, the return array will match the grouping
           scheme applied to the data set. The size of this array
           depends on the `filter` argument.

        Raises
        ------
        sherpa.utils.err.IdentifierErr
           If the data set does not exist.

        See Also
        --------
        get_dep : Return the dependent axis of a data set.
        get_staterror : Return the statistical errors on the dependent axis of a data set.
        get_syserror : Return the systematic errors on the dependent axis of a data set.
        list_data_ids : List the identifiers for the loaded data sets.

        Notes
        -----
        The default behavior is to not apply any filter defined on the
        independent axes to the results, so that the return value is for
        all points (or bins) in the data set. Set the `filter` argument
        to `True` to apply this filter.

        Examples
        --------

        Return the error values for the default data set, ignoring any
        filter applied to it:

        >>> err = get_error()

        Ensure that the return values are for the selected (filtered)
        points in the default data set (the return array may be smaller
        than in the previous example):

        >>> err = get_error(filter=True)

        Find the errors for the "core" data set and its two background
        components:

        >>> err = get_error('core', filter=True)
        >>> berr1 = get_error('core', bkg_id=1, filter=True)
        >>> berr2 = get_error('core', bkg_id=2, filter=True)

        """
        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        return d.get_error(filter, self.get_stat().calc_staterror)

    # DOC-NOTE: also in sherpa.utils
    def get_indep(self, id=None, filter=False, bkg_id=None):
        """Return the independent axes of a data set.

        This function returns the coordinates of each point, or pixel,
        in the data set. The `get_axes` function may be be preferred
        in some situations.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filter : bool, optional
           Should the filter attached to the data set be applied to
           the return value or not. The default is ``False``.
        bkg_id : int or str, optional
           Set if the values returned should be from the given
           background component, instead of the source data set.

        Returns
        -------
        axis : tuple of arrays
           The independent axis values. These are the values at which
           the model is evaluated during fitting. The values returned
           depend on the coordinate system in use for the data set (as
           set by `set_coord`). For PHA data sets the value returned
           is always in channels, whatever the `set_analysis` setting
           is, and does not follow any grouping setting for the data
           set.

        Raises
        ------
        sherpa.utils.err.IdentifierErr
           If the data set does not exist.

        See Also
        --------
        get_axes : Return information about the independent axes of a data set.
        get_dep : Return the dependent axis of a data set.
        list_data_ids : List the identifiers for the loaded data sets.
        set_coord : Set the coordinate system to use for image analysis.

        Notes
        -----
        For a two-dimensional image, with size n by m pixels, the
        `get_dep` function will return two arrays, each of size n * m,
        which contain the coordinate of the center of each pixel. The
        `get_axes` function will instead return the coordinates of
        each axis separately, i.e. arrays of size n and m.

        Examples
        --------

        For a one-dimensional data set, the X values are returned:

        >>> load_arrays(1, [10, 15, 19], [4, 5, 9], Data1D)
        >>> get_indep()
        (array([10, 15, 19]),)

        For a 2D data set the X0 and X1 values are returned:

        >>> x0 = [10, 15, 12, 19]
        >>> x1 = [12, 14, 10, 17]
        >>> y = [4, 5, 9, -2]
        >>> load_arrays(2, x0, x1, y, Data2D)
        >>> get_indep(2)
        (array([10, 15, 12, 19]), array([12, 14, 10, 17]))

        For PHA data sets the return value is in channel units:

        >>> load_pha('spec', 'src.pi')
        >>> set_analysis('spec', 'energy')
        >>> (chans,) = get_indep('spec')
        >>> chans[0:6]
        array([ 1.,  2.,  3.,  4.,  5.,  6.])

        If the ``filter`` flag is set then the return will be limited to
        the data that is used in the fit:

        >>> notice_id('spec', 0.5, 7)
        >>> (nchans,) = get_indep('spec', filter=True)
        >>> nchans[0:5]
        array([ 35.,  36.,  37.,  38.,  39.])

        For images the pixel coordinates of each pixel are returned,
        as 1D arrays, one value for each pixel:

        >>> load_image('img', 'image.fits')
        >>> (xvals, yvals) = get_indep('img')
        >>> xvals.shape
        (65536,)
        >>> yvals.shape
        (65536,)
        >>> xvals[0:5]
        array([ 1.,  2.,  3.,  4.,  5.])
        >>> yvals[0:5]
        array([ 1.,  1.,  1.,  1.,  1.])

        The coordinate system for image axes is determinated by the
        `set_coord` setting for the data set:

        >>> set_coord('img', 'physical')
        >>> (avals, bvals) = get_indep('img')
        >>> avals[0:5]
        array([  16.5,   48.5,   80.5,  112.5,  144.5])

        """
        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        return d.get_indep(filter=filter)

    def get_axes(self, id=None, bkg_id=None):
        """Return information about the independent axes of a data set.

        This function returns the coordinates of each point, or pixel,
        in the data set. The `get_indep` function may be be preferred
        in some situations.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        bkg_id : int or str, optional
           Set if the values returned should be from the given
           background component, instead of the source data set.

        Returns
        -------
        axis : tuple of arrays
           The independent axis values. The differences to `get_dep`
           that this represents the "alternate grid" for the axis. For
           PHA data, this is the energy grid (E_MIN and E_MAX). For
           image data it is an array for each axis, of the length of
           the axis, using the current coordinate system for the data
           set.

        Raises
        ------
        sherpa.utils.err.IdentifierErr
           If the data set does not exist.

        See Also
        --------
        get_indep : Return the independent axis of a data set.
        list_data_ids : List the identifiers for the loaded data sets.

        Examples
        --------

        For 1D data sets, the "alternate" view is the same as the
        independent axis:

        >>> load_arrays(1, [10, 15, 19], [4, 5, 9], Data1D)
        >>> get_indep()
        array([10, 15, 19])
        >>> get_axes()
        array([10, 15, 19])

        For a PHA data set, the approximate energy grid of the
        channels is returned (this is determined by the EBOUNDS
        extension of the RMF).

        >>> load_pha('core', 'src.pi')
        read ARF file src.arf
        read RMF file src.rmf
        read background file src_bkg.pi
        >>> (chans,) = get_indep()
        >>> (elo, ehi) = get_axes()
        >>> chans[0:5]
        array([ 1.,  2.,  3.,  4.,  5.])
        >>> elo[0:5]
        array([ 0.0073,  0.0146,  0.0292,  0.0438,  0.0584])
        >>> ehi[0:5]
        array([ 0.0146,  0.0292,  0.0438,  0.0584,  0.073 ])

        The image has 101 columns by 108 rows. The `get_indep`
        function returns one-dimensional arrays, for the full dataset,
        whereas `get_axes` returns values for the individual axis:

        >>> load_image('img', 'img.fits')
        >>> get_data('img').shape
        (108, 101)
        >>> set_coord('img', 'physical')
        >>> (x0, x1) = get_indep('img')
        >>> (a0, a1) = get_axes('img')
        >>> (x0.size, x1.size)
        (10908, 10908)
        >>> (a0.size, a1.size)
        (101, 108)
        >>> np.all(x0[:101] == a0)
        True
        >>> np.all(x1[::101] == a1)
        True

        """
        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)

        if isinstance(d, sherpa.astro.data.DataPHA):
            return d._get_ebins(group=False)

        if isinstance(d, (sherpa.data.Data2D,
                          sherpa.astro.data.DataIMG)):
            return d.get_axes()

        return d.get_indep()

    # DOC-NOTE: also in sherpa.utils
    def get_dep(self, id=None, filter=False, bkg_id=None):
        """Return the dependent axis of a data set.

        This function returns the data values (the dependent axis)
        for each point or pixel in the data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filter : bool, optional
           Should the filter attached to the data set be applied to
           the return value or not. The default is ``False``.
        bkg_id : int or str, optional
           Set if the values returned should be from the given
           background component, instead of the source data set.

        Returns
        -------
        axis : array
           The dependent axis values. The model estimate is compared
           to these values during fitting. For PHA data sets, the
           return array will match the grouping scheme applied to
           the data set. This array is one-dimensional, even for
           two dimensional (e.g. image) data.

        Raises
        ------
        sherpa.utils.err.IdentifierErr
           If the data set does not exist.

        See Also
        --------
        get_error : Return the errors on the dependent axis of a data set.
        get_indep : Return the independent axis of a data set.
        get_rate : Return the count rate of a PHA data set.
        list_data_ids : List the identifiers for the loaded data sets.

        Examples
        --------

        >>> load_arrays(1, [10, 15, 19], [4, 5, 9], Data1D)
        >>> get_dep()
        array([4, 5, 9])

        >>> x0 = [10, 15, 12, 19]
        >>> x1 = [12, 14, 10, 17]
        >>> y = [4, 5, 9, -2]
        >>> load_arrays(2, x0, x1, y, Data2D)
        >>> get_dep(2)
        array([4, 5, 9, -2])

        If the ``filter`` flag is set then the return will be limited to
        the data that is used in the fit:

        >>> load_arrays(1, [10, 15, 19], [4, 5, 9])
        >>> ignore_id(1, 17, None)
        >>> get_dep()
        array([4, 5, 9])
        >>> get_dep(filter=True)
        array([4, 5])

        An example with a PHA data set named 'spec':

        >>> notice_id('spec', 0.5, 7)
        >>> yall = get_dep('spec')
        >>> yfilt = get_dep('spec', filter=True)
        >>> yall.size
        1024
        >>> yfilt.size
        446

        For images, the data is returned as a one-dimensional array:

        >>> load_image('img', 'image.fits')
        >>> ivals = get_dep('img')
        >>> ivals.shape
        (65536,)

        """
        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        dep = d.get_y(filter)
        if isinstance(d, sherpa.astro.data.DataPHA):
            old = d._rate
            d._rate = False  # return predicted counts, not rate for PHA
            dep = d.get_y(filter)
            d._rate = old
        return dep

    get_counts = get_dep

    def get_rate(self, id=None, filter=False, bkg_id=None):
        """Return the count rate of a PHA data set.

        Return an array of count-rate values for each bin in the
        data set. The units of the returned values depends on the
        values set by the `set_analysis` rountine for the data
        set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filter : bool, optional
           Should the filter attached to the data set be applied to
           the return value or not. The default is ``False``.
        bkg_id : int or str, optional
           Set if the rate should be taken from the background
           associated with the data set.

        Returns
        -------
        rate : array
           The rate array. The output matches the grouping of the data
           set. The units are controlled by the `set_analysis` setting
           for this data set; that is, the units used in `plot_data`,
           except that the `type` argument to `set_analysis` is ignored.
           The return array will match the grouping scheme applied to
           the data set.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.

        See Also
        --------
        get_dep : Return the data for a data set.
        ignore : Exclude data from the fit.
        notice : Include data in the fit.
        plot_data : Plot the data values.
        set_analysis : Set the units used when fitting and displaying spectral data.

        Examples
        --------

        Return the count-rate for the default data set. For a PHA
        data set, where `set_analysis` has not been called, the return
        value will be in units of count/second/keV, and a value for
        each group in the data set is returned.

        >>> rate = get_rate()

        The return value is grouped to match the data, but is not
        filtered (with the default `filter` argument). The data
        set used here 46 groups in it, but after filtering only has 40
        groups, but the call to `get_rate` returns a 46-element array
        unless `filter` is explicitly set to `True`:

        >>> notice()
        >>> get_rate().size
        46
        >>> ignore(None, 0.5)
        >>> ignore(7, None)
        >>> get_rate().size
        46
        >>> get_rate(filter=True).size
        40

        The rate of data set 2 will be in units of count/s/Angstrom
        and only cover the range 20 to 22 Angstroms:

        >>> set_analysis(2, 'wave')
        >>> notice_id(2, 20, 22)
        >>> r2 = get_rate(2, filter=True)

        The returned rate is now in units of count/s (the return value
        is multiplied by `binwidth^factor`, where `factor` is normally
        0):

        >>> set_analysis(2, 'wave', factor=1)
        >>> r2 = get_rate(2, filter=True)

        Return the count rate for the second background component of
        data set "grating":

        >>> get_rate(id="grating", bkg_id=2)

        """
        d = self._get_pha_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        old = d._rate
        d._rate = True     # return count rate for PHA
        rate = d.get_y(filter)
        d._rate = old
        return rate

    # DOC-TODO: how to get the corresponding x bins for this data?
    # i.e. what are the X values for these points
    def get_specresp(self, id=None, filter=False, bkg_id=None):
        """Return the effective area values for a PHA data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filter : bool, optional
           Should the filter attached to the data set be applied to
           the ARF or not. The default is ``False``.
        bkg_id : int or str, optional
           Set if the ARF should be taken from a background set
           associated with the data set.

        Returns
        -------
        arf : array
           The effective area values for the data set (or background
           component).

        Examples
        --------

        Return the effective-area values for the default data set:

        >>> arf = get_specresp()

        Return the area for the second background component of the
        data set with the id "eclipse":

        >>> barf = get_spectresp("eclipse", bkg_id=2)

        """
        d = self._get_pha_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        return d.get_specresp(filter)

    def get_exposure(self, id=None, bkg_id=None):
        """Return the exposure time of a PHA data set.

        The exposure time of a PHA data set is taken from the
        EXPTIME keyword in its header, but it can be changed
        once the file has been loaded.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        bkg_id : int or str, optional
           Set to identify which background component to use.  The
           default value (``None``) means that the time is for the
           source component of the data set.

        Returns
        -------
        exposure : number
           The exposure time, in seconds.

        See Also
        --------
        get_areascal : Return the fractional area factor of a PHA data set.
        get_backscal : Return the area scaling of a PHA data set.
        set_exposure : Change the exposure time of a PHA data set.

        Examples
        --------

        Return the exposure time for the default data set.

        >>> t = get_exposure()

        Return the exposure time for the data set with identifier 2:

        >>> t2 = get_exposure(2)

        Return the exposure time for the first background component
        of data set "core":

        >>> tbkg = get_exposure('core', bkg_id=1)

        """
        if bkg_id is not None:
            return self.get_bkg(id, bkg_id).exposure
        return self._get_pha_data(id).exposure

    def get_backscal(self, id=None, bkg_id=None):
        """Return the BACKSCAL scaling of a PHA data set.

        Return the BACKSCAL setting [1]_ for the source or background
        component of a PHA data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        bkg_id : int or str, optional
           Set to identify which background component to use.  The
           default value (``None``) means that the value is for the
           source component of the data set.

        Returns
        -------
        backscal : number or ndarray
           The BACKSCAL value, which can be a scalar or a 1D array.

        See Also
        --------
        get_areascal : Return the fractional area factor of a PHA data set.
        get_bkg_scale : Return the background scaling factor for a PHA data set.
        set_backscal : Change the area scaling of a PHA data set.

        Notes
        -----
        The BACKSCAL value can be defined as the ratio of the area of
        the source (or background) extraction region in image pixels
        to the total number of image pixels. The fact that there is no
        ironclad definition for this quantity does not matter so long
        as the value for a source dataset and its associated
        background dataset are defined in the similar manner, because
        only the ratio of source and background BACKSCAL values is
        used. It can be a scalar or be an array.

        References
        ----------

        .. [1] "The OGIP Spectral File Format", Arnaud, K. & George, I.
               http://heasarc.gsfc.nasa.gov/docs/heasarc/ofwg/docs/spectra/ogip_92_007/ogip_92_007.html

        Examples
        --------

        >>> get_backscal()
        7.8504301607718007e-06
        >>> get_backscal(bkg_id=1)
        0.00022745132446289

        """
        if bkg_id is not None:
            return self.get_bkg(id, bkg_id).backscal
        return self._get_pha_data(id).backscal

    def get_bkg_scale(self, id=None, bkg_id=1, units='counts',
                      group=True, filter=False):
        """Return the background scaling factor for a background data set.

        Return the factor applied to the background component to scale
        it to match it to the source, either when subtracting the
        background (units='counts'), or fitting it simultaneously
        (units='rate').

        .. versionchanged:: 4.12.2
           The bkg_id, counts, group, and filter parameters have been
           added and the routine no-longer calculates the average
           scaling for all the background components but just for the
           given component.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        bkg_id : int or str, optional
           Set to identify which background component to use.  The
           default value is 1.
        units : {'counts', 'rate'}, optional
           The correction is applied to a model defined as counts, the
           default, or a rate. The latter should be used when
           calculating the correction factor for adding the background
           data to the source aperture.
        group : bool, optional
            Should the values be grouped to match the data?
        filter : bool, optional
            Should the values be filtered to match the data?

        Returns
        -------
        ratio : number or array
           The scaling factor. The result can vary per channel, in which case
           an array is returned.

        See Also
        --------
        get_areascal : Return the fractional area factor of a PHA data set.
        get_backscal : Return the area scaling factor for a PHA data set.
        set_backscal : Change the area scaling of a PHA data set.
        set_full_model : Define the convolved model expression for a data set.
        set_bkg_full_model : Define the convolved background model expression for a PHA data set.

        Notes
        -----
        The scale factor when units='counts' is::

          exp_src * bscale_src * areascal_src /
          (exp_bgnd * bscale_bgnd * areascal_ngnd) /
          nbkg

        where ``exp_x``, ``bscale_x``. and ``areascal_x`` are the
        exposure, BACKSCAL, and AREASCAL values for the source
        (``x=src``) and background (``x=bgnd``) regions, respectively,
        and ``nbkg`` is the number of background datasets associated
        with the source aperture. When units='rate', the exposure and
        areascal corrections are not included.

        Examples
        --------

        Return the background-scaling factor for the default dataset (this
        assumes there's only one background component).

        >>> get_bkg_scale()
        0.034514770047217924

        Return the factor for dataset "pi":

        >>> get_bkg_scale('pi')
        0.034514770047217924

        Calculate the factors for the first two background components
        of the default dataset, valid for combining the source
        and background models to fit the source aperture:

        >>> scale1 = get_bkg_scale(units='rate')
        >>> scale2 = get_bkg_scale(units='rate', bkg_id=2)

        """

        dset = self._get_pha_data(id)
        scale = dset.get_background_scale(bkg_id, units=units,
                                          group=group, filter=filter)
        if scale is None:
            # TODO: need to add bkg_id?
            raise DataErr('nobkg', self._fix_id(id))

        return scale

    def get_areascal(self, id=None, bkg_id=None):
        """Return the fractional area factor of a PHA data set.

        Return the AREASCAL setting [1]_ for the source or background
        component of a PHA data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        bkg_id : int or str, optional
           Set to identify which background component to use.  The
           default value (``None``) means that the value is for the
           source component of the data set.

        Returns
        -------
        areascal : number or ndarray
           The AREASCAL value, which can be a scalar or a 1D array.

        See Also
        --------
        get_backscal : Return the area scaling of a PHA data set.
        set_areascal : Change the fractional area factor of a PHA data set.

        Notes
        -----
        The fractional area scale is normally set to 1, with the ARF used
        to scale the model.

        References
        ----------

        .. [1] "The OGIP Spectral File Format", Arnaud, K. & George, I.
               http://heasarc.gsfc.nasa.gov/docs/heasarc/ofwg/docs/spectra/ogip_92_007/ogip_92_007.html

        Examples
        --------

        Return the AREASCAL value for the default data set:

        >>> get_areascal()

        Return the AREASCAL value for the first background component
        of dataset 2:

        >>> get_areascal(id=2, bkg_id=1)

        """
        if bkg_id is not None:
            return self.get_bkg(id, bkg_id).areascal
        return self._get_pha_data(id).areascal

    def _save_type(self, objtype, id, filename, bkg_id=None, **kwargs):
        if filename is None:
            id, filename = filename, id
        _check_type(filename, string_types, 'filename', 'a string')
        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)

        if isinstance(d, (sherpa.astro.data.DataIMG,
                          sherpa.astro.data.DataIMGInt,
                          sherpa.data.Data2D, sherpa.data.Data2DInt)):

            backup = d.y
            if objtype == 'delchi':
                raise AttributeError("save_delchi() does not apply for images")

            imgtype = getattr(self, 'get_' + objtype + '_image', None)
            if imgtype is None:
                raise AttributeError("'get_%s_image()' not found" % objtype)

            obj = imgtype(id)

            try:
                # write out the array using the source dataset,
                # include WCS etc.
                d.y = obj.y.ravel()

                sherpa.astro.io.write_image(filename, d, **kwargs)
            finally:
                d.y = backup
            return

        funcname = 'get_'
        if bkg_id is not None:
            funcname += 'bkg_'

        plottype = getattr(self, funcname + objtype + '_plot', None)
        if plottype is None:
            raise AttributeError("'%s%s_plot()' not found" % (funcname,
                                                              objtype))

        obj = plottype(id)
        if bkg_id is not None:
            obj = plottype(id, bkg_id=bkg_id)

        args = None
        fields = None

#        if type(d) in (sherpa.data.Data1DInt, sherpa.astro.data.DataPHA):
#            args = [obj.xlo, obj.xhi, obj.y]
#            fields = ["XLO", "XHI", str(objtype).upper()]
        if isinstance(d, sherpa.astro.data.DataPHA) and \
           objtype in ('model', 'source'):
            args = [obj.xlo, obj.xhi, obj.y]
            fields = ["XLO", "XHI", str(objtype).upper()]
        else:
            args = [obj.x, obj.y]
            fields = ["X", str(objtype).upper()]

        sherpa.astro.io.write_arrays(filename, args, fields=fields, **kwargs)

# To fix bug report 13536, save many kinds of data to ASCII by default,
# and let user override if they want FITS (or vice-versa).  The new defaults
# as of CIAO 4.6 are:
#
# ascii = False (i.e., write to FITS):
#
# save_pha
# save_image
# save_table
#
# ascii = True (i.e., write to ASCII):
#
# save_arrays
# save_source
# save_model
# save_resid
# save_delchi
# save_filter
# save_staterror
# save_syserror
# save_error
# save_grouping
# save_quality
# save_data
#
# My logic is that in the former group, you are focused on writing to a
# specific kind of file (PHA, image or table) so use FITS by default.
# In the latter group, you are not focused on file type, but on some
# data or model attribute you want to write out and read into some other
# program with ease.  ASCII is probably better for that.
# SMD 05/15/13
#

    # DOC-NOTE: also in sherpa.utils with a different interface
    def save_arrays(self, filename, args, fields=None, ascii=True,
                    clobber=False):
        """Write a list of arrays to a file.

        Parameters
        ----------
        filename : str
           The name of the file to write the array to.
        args : array of arrays
           The arrays to write out.
        fields : array of str
           The column names (should match the size of `args`).
        ascii : bool, optional
           If ``False`` then the data is written as a FITS format binary
           table. The default is ``True``. The exact format of the
           output file depends on the I/O library in use (Crates or
           AstroPy).
        clobber : bool, optional
           This flag controls whether an existing file can be
           overwritten (``True``) or if it raises an exception (``False``,
           the default setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        save_data : Save the data to a file.
        save_image : Save the pixel values of a 2D data set to a file.
        save_table : Save a data set to a file as a table.

        Examples
        --------

        Write the x and y columns from the default data set to the
        file 'src.dat':

        >>> x = get_indep()
        >>> y = get_dep()
        >>> save_arrays('src.dat', [x, y])

        Use the column names "r" and "surbri" for the columns:

        >>> save_arrays('prof.fits', [x,y], fields=["r", "surbri"],
        ...             ascii=False, clobber=True)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        sherpa.astro.io.write_arrays(filename, args, fields=fields,
                                     ascii=ascii, clobber=clobber)

    # DOC-NOTE: also in sherpa.utils with a different API
    def save_source(self, id, filename=None, bkg_id=None, ascii=False,
                    clobber=False):
        """Save the model values to a file.

        The model is evaluated on the grid of the data set, but does
        not include any instrument response (such as a PSF or ARF and
        RMF).

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the array to. The format
           is determined by the `ascii` argument.
        bkg_id : int or str, optional
           Set if the background model should be written out
           rather than the source.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS format binary
           table. The default is ``False``. The exact format of the
           output file depends on the I/O library in use (Crates or
           AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IdentifierErr
           If no model has been set for this data set.
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        save_data : Save the data to a file.
        save_model : Save the model values to a file.
        set_model : Set the source model expression for a data set.
        set_full_model : Define the convolved model expression for a data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The output file contains the columns ``X`` and ``SOURCE`` for 1D
        data sets. The residuals array respects any filter or (for PHA
        files), grouping settings.

        Examples
        --------

        Write the model values for the default data set to the file
        "model.fits":

        >>> save_source('model.fits')

        Write the model from the data set 'jet' to the ASCII file
        "model.dat":

        >>> save_source('jet', "model.dat", ascii=True)

        For 2D (image) data sets, the model is written out as an
        image:

        >>> save_source('img', 'model.img')

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        self._save_type('source', id, filename, ascii=ascii, clobber=clobber,
                        bkg_id=bkg_id)

    # DOC-NOTE: also in sherpa.utils with a different API
    def save_model(self, id, filename=None, bkg_id=None, ascii=False,
                   clobber=False):
        """Save the model values to a file.

        The model is evaluated on the grid of the data set, including
        any instrument response (such as a PSF or ARF and RMF).

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the array to. The format
           is determined by the `ascii` argument.
        bkg_id : int or str, optional
           Set if the background model should be written out
           rather than the source.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS format binary
           table. The default is ``False``. The exact format of the
           output file depends on the I/O library in use (Crates or
           AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IdentifierErr
           If no model has been set for this data set.
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        save_data : Save the data to a file.
        save_source : Save the model values to a file.
        set_model : Set the source model expression for a data set.
        set_full_model : Define the convolved model expression for a data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The output file contains the columns ``X`` and ``MODEL`` for 1D
        data sets. The residuals array respects any filter or (for PHA
        files), grouping settings.

        Examples
        --------

        Write the model values for the default data set to the file
        "model.fits":

        >>> save_model('model.fits')

        Write the model from the data set 'jet' to the ASCII file
        "model.dat":

        >>> save_model('jet', "model.dat", ascii=True)

        For 2D (image) data sets, the model is written out as an
        image:

        >>> save_model('img', 'model.img')

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        self._save_type('model', id, filename, ascii=ascii, clobber=clobber,
                        bkg_id=bkg_id)

    # DOC-NOTE: also in sherpa.utils with a different API
    def save_resid(self, id, filename=None, bkg_id=None, ascii=False,
                   clobber=False):
        """Save the residuals (data-model) to a file.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the array to. The format
           is determined by the `ascii` argument.
        bkg_id : int or str, optional
           Set if the background residuals should be written out
           rather than the source.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS format binary
           table. The default is ``False``. The exact format of the
           output file depends on the I/O library in use (Crates or
           AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IdentifierErr
           If no model has been set for this data set.
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        save_data : Save the data to a file.
        save_delchi : Save the ratio of residuals (data-model) to error to a file.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The output file contains the columns ``X`` and ``RESID``. The
        residuals array respects any filter or (for PHA files),
        grouping settings.

        Examples
        --------

        Write the residuals to the file "resid.fits":

        >>> save_resid('resid.fits')

        Write the residuals from the data set 'jet' to the
        ASCII file "resid.dat":

        >>> save_resid('jet', "resid.dat", ascii=True)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        self._save_type('resid', id, filename, ascii=ascii, clobber=clobber,
                        bkg_id=bkg_id)

    # DOC-NOTE: also in sherpa.utils with a different API
    def save_delchi(self, id, filename=None, bkg_id=None, ascii=True,
                    clobber=False):
        """Save the ratio of residuals (data-model) to error to a file.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the array to. The format
           is determined by the `ascii` argument.
        bkg_id : int or str, optional
           Set if the background residuals should be written out
           rather than the source.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS format binary
           table. The default is ``True``. The exact format of the
           output file depends on the I/O library in use (Crates or
           AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IdentifierErr
           If no model has been set for this data set.
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        save_data : Save the data to a file.
        save_resid : Save the residuals (data-model) to a file.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The output file contains the columns ``X`` and ``DELCHI``. The
        residuals array respects any filter or (for PHA files),
        grouping settings.

        Examples
        --------

        Write the residuals to the file "delchi.dat":

        >>> save_delchi('delchi.dat')

        Write the residuals from the data set 'jet' to the
        FITS file "delchi.fits":

        >>> save_delchi('jet', "delchi.fits", ascii=False)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        self._save_type('delchi', id, filename, ascii=ascii, clobber=clobber,
                        bkg_id=bkg_id)

    # DOC-NOTE: also in sherpa.utils with a different interface
    def save_filter(self, id, filename=None, bkg_id=None, ascii=True,
                    clobber=False):
        """Save the filter array to a file.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the array to. The format
           is determined by the `ascii` argument.
        bkg_id : int or str, optional
           Set if the background should be written out rather
           than the source.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS format binary
           table. The default is ``True``. The exact format of the
           output file depends on the I/O library in use (Crates or
           AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.DataErr
           If the data set has not been filtered.
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        load_filter : Load the filter array from a file and add to a data set.
        save_data : Save the data to a file.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The output file contains the columns ``X`` and ``FILTER``.

        Examples
        --------

        Write the filter from the default data set as an ASCII file:

        >>> save_filter('filt.dat')

        Write the filter for data set 'src' to a FITS format file:

        >>> save_filter('src', 'filter.fits', ascii=False)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        if filename is None:
            id, filename = filename, id
        _check_type(filename, string_types, 'filename', 'a string')
        id = self._fix_id(id)

        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        else:
            d = self.get_data(id)

        # Leave this check as d.mask is False since d.mask need not be a boolean
        # and we want different errors if mask is True or False (and leave as
        # the iterable check to catch 'd.mask' is True or any other value that
        # could cause the following code to fall over).
        #
        if d.mask is False:
            raise DataErr('notmask')
        if not numpy.iterable(d.mask):
            raise DataErr('nomask', id)

        if isinstance(d, sherpa.astro.data.DataPHA):
            x = d._get_ebins(group=True)[0]
        else:
            x = d.get_indep(filter=False)[0]

        mask = numpy.asarray(d.mask, int)

        self.save_arrays(filename, [x, mask], fields=['X', 'FILTER'],
                         ascii=ascii, clobber=clobber)

    # DOC-NOTE: also in sherpa.utils with a different interface
    def save_staterror(self, id, filename=None, bkg_id=None, ascii=True,
                       clobber=False):
        """Save the statistical errors to a file.

        If the statistical errors have not been set explicitly, then
        the values calculated by the statistic - such as ``chi2gehrels``
        or ``chi2datavar`` - will be used.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the array to. The format
           is determined by the `ascii` argument.
        bkg_id : int or str, optional
           Set if the background should be written out rather
           than the source.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS
           format binary table. The default is ``True``. The
           exact format of the output file depends on the
           I/O library in use (Crates or AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        load_staterror : Load the statistical errors from a file.
        save_error : Save the errors to a file.
        save_syserror : Save the systematic errors to a file.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The output file contains the columns ``X`` and ``STAT_ERR``.

        Examples
        --------

        Write out the statistical errors from the default data set to the
        file 'errs.dat'.

        >>> save_staterror('errs.dat')

        Over-write the file it it already exists, and take the data
        from the data set "jet":

        >>> save_staterror('jet', 'err.out', clobber=True)

        Write the data out in FITS format:

        >>> save_staterror('staterr.fits', ascii=False)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        if filename is None:
            id, filename = filename, id
        _check_type(filename, string_types, 'filename', 'a string')
        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        id = self._fix_id(id)

        if isinstance(d, sherpa.astro.data.DataPHA):
            x = d._get_ebins(group=True)[0]
        else:
            x = d.get_indep(filter=False)[0]

        err = self.get_staterror(id, filter=False, bkg_id=bkg_id)
        self.save_arrays(filename, [x, err], fields=['X', 'STAT_ERR'],
                         ascii=ascii, clobber=clobber)

    # DOC-NOTE: also in sherpa.utils with a different interface
    def save_syserror(self, id, filename=None, bkg_id=None, ascii=True,
                      clobber=False):
        """Save the systematic errors to a file.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the array to. The format
           is determined by the `ascii` argument.
        bkg_id : int or str, optional
           Set if the background should be written out rather
           than the source.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS
           format binary table. The default is ``True``. The
           exact format of the output file depends on the
           I/O library in use (Crates or AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If the data set does not contain any systematic errors.
        sherpa.utils.err.DataErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        load_syserror : Load the systematic errors from a file.
        save_error : Save the errors to a file.
        save_staterror : Save the statistical errors to a file.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The output file contains the columns ``X`` and ``SYS_ERR``.

        Examples
        --------

        Write out the systematic errors from the default data set to the
        file 'errs.dat'.

        >>> save_syserror('errs.dat')

        Over-write the file it it already exists, and take the data
        from the data set "jet":

        >>> save_syserror('jet', 'err.out', clobber=True)

        Write the data out in FITS format:

        >>> save_syserror('syserr.fits', ascii=False)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        if filename is None:
            id, filename = filename, id
        _check_type(filename, string_types, 'filename', 'a string')
        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        id = self._fix_id(id)

        if isinstance(d, sherpa.astro.data.DataPHA):
            x = d._get_ebins(group=True)[0]
        else:
            x = d.get_indep(filter=False)[0]

        err = self.get_syserror(id, filter=False, bkg_id=bkg_id)
        self.save_arrays(filename, [x, err], fields=['X', 'SYS_ERR'],
                         ascii=ascii, clobber=clobber)

    # DOC-NOTE: also in sherpa.utils with a different interface
    def save_error(self, id, filename=None, bkg_id=None, ascii=True,
                   clobber=False):
        """Save the errors to a file.

        The total errors for a data set are the quadrature combination
        of the statistical and systematic errors. The systematic
        errors can be 0. If the statistical errors have not been set
        explicitly, then the values calculated by the statistic - such
        as ``chi2gehrels`` or ``chi2datavar`` - will be used.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the array to. The format
           is determined by the `ascii` argument.
        bkg_id : int or str, optional
           Set if the background should be written out rather
           than the source.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS
           format binary table. The default is ``True``. The
           exact format of the output file depends on the
           I/O library in use (Crates or AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        get_error : Return the errors on the dependent axis of a data set.
        load_staterror : Load the statistical errors from a file.
        load_syserror : Load the systematic errors from a file.
        save_data : Save the data to a file.
        save_staterror : Save the statistical errors to a file.
        save_syserror : Save the systematic errors to a file.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The output file contains the columns ``X`` and ``ERR``.

        Examples
        --------

        Write out the errors from the default data set to the file
        'errs.dat'.

        >>> save_error('errs.dat')

        Over-write the file it it already exists, and take the data
        from the data set "jet":

        >>> save_error('jet', 'err.out', clobber=True)

        Write the data out in FITS format:

        >>> save_error('err.fits', ascii=False)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        if filename is None:
            id, filename = filename, id
        _check_type(filename, string_types, 'filename', 'a string')
        d = self.get_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        id = self._fix_id(id)

        if isinstance(d, sherpa.astro.data.DataPHA):
            x = d._get_ebins(group=True)[0]
        else:
            x = d.get_indep(filter=False)[0]

        err = self.get_error(id, filter=False, bkg_id=bkg_id)
        self.save_arrays(filename, [x, err], fields=['X', 'ERR'],
                         ascii=ascii, clobber=clobber)

    def save_pha(self, id, filename=None, bkg_id=None, ascii=False,
                 clobber=False):
        """Save a PHA data set to a file.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the array to. The format
           is determined by the `ascii` argument.
        bkg_id : int or str, optional
           Set if the background should be written out rather
           than the source.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS
           format binary table. The default is ``True``. The
           exact format of the output file depends on the
           I/O library in use (Crates or AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        load_pha : Load a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Examples
        --------

        Write out the PHA data from the default data set to the
        file 'src.pi':

        >>> save_pha('src.pi')

        Over-write the file it it already exists, and take the data
        from the data set "jet":

        >>> save_pha('jet', 'out.pi', clobber=True)

        Write the data out as an ASCII file:

        >>> save_pha('pi.dat', ascii=True)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        if filename is None:
            id, filename = filename, id
        _check_type(filename, string_types, 'filename', 'a string')
        d = self._get_pha_data(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)

        sherpa.astro.io.write_pha(filename, d, ascii=ascii, clobber=clobber)

    def save_grouping(self, id, filename=None, bkg_id=None, ascii=True, clobber=False):
        """Save the grouping scheme to a file.

        The output is a two-column file, containing the channel and
        grouping columns from the data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the array to. The format
           is determined by the `ascii` argument.
        bkg_id : int or str, optional
           Set if the grouping array should be taken from the
           background associated with the data set.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS
           format binary table. The default is ``True``. The
           exact format of the output file depends on the
           I/O library in use (Crates or AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        get_grouping : Return the gouping array for a PHA data set.
        load_quality : Load the quality array from a file and add to a PHA data set.
        set_grouping : Apply a set of grouping flags to a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The column names are 'CHANNEL' and 'GROUPS'.

        Examples
        --------

        Save the channel and grouping columns from the default data
        set to the file 'group.dat' as an ASCII file:

        >>> save_grouping('group.dat')

        Over-write the 'grp.fits' file, if it exists, and write
        out the grouping data from the 'jet' data set, as a FITS
        format file:

        >>> save_grouping('jet', 'grp.fits', ascii=False, clobber=True)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        if filename is None:
            id, filename = filename, id
        _check_type(filename, string_types, 'filename', 'a string')
        id = self._fix_id(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        else:
            d = self._get_pha_data(id)

        if d.grouping is None or not numpy.iterable(d.grouping):
            raise DataErr('nogrouping', id)

        sherpa.astro.io.write_arrays(filename, [d.channel, d.grouping],
                                     fields=['CHANNEL', 'GROUPS'], ascii=ascii,
                                     clobber=clobber)

    def save_quality(self, id, filename=None, bkg_id=None, ascii=True, clobber=False):
        """Save the quality array to a file.

        The output is a two-column file, containing the channel and
        quality columns from the data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the array to. The format
           is determined by the `ascii` argument.
        bkg_id : int or str, optional
           Set if the quality array should be taken from the
           background associated with the data set.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS
           format binary table. The default is ``True``. The
           exact format of the output file depends on the
           I/O library in use (Crates or AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        get_quality : Return the quality array for a PHA data set.
        load_quality : Load the quality array from a file and add to a PHA data set.
        set_quality : Apply a set of quality flags to a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The column names are 'CHANNEL' and 'QUALITY'.

        Examples
        --------

        Save the channel and quality columns from the default data
        set to the file 'quality.dat' as an ASCII file:

        >>> save_quality('quality.dat')

        Over-write the 'qual.fits' file, if it exists, and write
        out the quality array from the 'jet' data set, as a FITS
        format file:

        >>> save_quality('jet', 'qual.fits', ascii=False, clobber=True)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        if filename is None:
            id, filename = filename, id
        _check_type(filename, string_types, 'filename', 'a string')
        id = self._fix_id(id)
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        else:
            d = self._get_pha_data(id)

        if d.quality is None or not numpy.iterable(d.quality):
            raise DataErr('noquality', id)

        sherpa.astro.io.write_arrays(filename, [d.channel, d.quality],
                                     fields=['CHANNEL', 'QUALITY'], ascii=ascii,
                                     clobber=clobber)

    # DOC-TODO: setting ascii=True is not supported for crates
    # and in pyfits it seems to just be a 1D array (needs thinking about)
    def save_image(self, id, filename=None, ascii=False, clobber=False):
        """Save the pixel values of a 2D data set to a file.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the data to. The format
           is determined by the `ascii` argument.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS format binary
           table. The default is ``False``. The exact format of the
           output file depends on the I/O library in use (Crates or
           AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.
           If the data set does not contain 2D data.

        See Also
        --------
        save_data : Save the data to a file.
        save_model : Save the model values to a file.
        save_source : Save the model values to a file.
        save_table : Save a data set to a file as a table.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Examples
        --------

        Write the pixel values to the file "img.fits":

        >>> save_image('resid.fits')

        Write the data from the data set 'jet' to the file "jet.img":

        >>> save_image('jet', 'jet.img', clobber=True)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        if filename is None:
            id, filename = filename, id
        _check_type(filename, string_types, 'filename', 'a string')

        sherpa.astro.io.write_image(filename, self.get_data(id),
                                    ascii=ascii, clobber=clobber)

    # DOC-TODO: the output for an image is "excessive"
    def save_table(self, id, filename=None, ascii=False, clobber=False):
        """Save a data set to a file as a table.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the data to. The format
           is determined by the `ascii` argument.
        ascii : bool, optional
           If ``False`` then the data is written as a FITS format binary
           table. The default is ``False``. The exact format of the
           output file depends on the I/O library in use (Crates or
           AstroPy).
        clobber : bool, optional
           If `outfile` is not ``None``, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        save_data : Save the data to a file.
        save_image : Save the pixel values of a 2D data set to a file.
        save_pha : Save a PHA data set to a file.
        save_model : Save the model values to a file.
        save_source : Save the model values to a file.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Examples
        --------

        Write the data set to the file "table.fits":

        >>> save_table('table.fits')

        Write the data from the data set 'jet' to the file "jet.dat",
        as an ASCII file:

        >>> save_table('jet', 'jet.dat', ascii=True, clobber=True)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        if filename is None:
            id, filename = filename, id
        id = self._fix_id(id)
        _check_type(filename, string_types, 'filename', 'a string')

        sherpa.astro.io.write_table(filename, self.get_data(id),
                                    ascii=ascii, clobber=clobber)

    # DOC-NOTE: also in sherpa.utils
    def save_data(self, id, filename=None, bkg_id=None, ascii=True, clobber=False):
        """Save the data to a file.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        filename : str
           The name of the file to write the array to. The data is
           written out as an ASCII file.
        bkg_id : int or str, optional
           Set if the background should be written out rather
           than the source (for a PHA data set).
        ascii : bool, optional
           If ``False`` then the data is written as a FITS format binary
           table. The default is ``True``. The exact format of the
           output file depends on the I/O library in use (Crates or
           AstroPy).
        clobber : bool, optional
           This flag controls whether an existing file can be
           overwritten (``True``) or if it raises an exception (``False``,
           the default setting).

        Raises
        ------
        sherpa.utils.err.IdentifierErr
           If there is no matching data set.
        sherpa.utils.err.IOErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        save_arrays : Write a list of arrays to a file.
        save_delchi : Save the ratio of residuals (data-model) to error to a file.
        save_error : Save the errors to a file.
        save_filter : Save the filter array to a file.
        save_grouping : Save the grouping scheme to a file.
        save_image : Save the pixel values of a 2D data set to a file.
        save_pha : Save a PHA data set to a file.
        save_quality : Save the quality array to a file.
        save_resid : Save the residuals (data-model) to a file.
        save_staterror : Save the statistical errors to a file.
        save_syserror : Save the statistical errors to a file.
        save_table : Save a data set to a file as a table.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `filename` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `filename` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Examples
        --------

        Write the default data set out to the ASCII file 'src.dat':

        >>> save_data('src.dat')

        Write the 'rprof' data out to the FITS file 'prof.fits',
        over-writing it if it already exists:

        >>> save_data('rprof', 'prof.fits', clobber=True, ascii=True)

        """
        clobber = sherpa.utils.bool_cast(clobber)
        ascii = sherpa.utils.bool_cast(ascii)
        if filename is None:
            id, filename = filename, id
        _check_type(filename, string_types, 'filename', 'a string')
        if bkg_id is not None:
            d = self.get_bkg(id, bkg_id)
        else:
            d = self.get_data(id)

        try:
            sherpa.astro.io.write_pha(filename, d, ascii=ascii,
                                      clobber=clobber)
        except IOErr:
            try:
                sherpa.astro.io.write_image(filename, d, ascii=ascii,
                                            clobber=clobber)
            except IOErr:
                try:
                    sherpa.astro.io.write_table(filename, d, ascii=ascii,
                                                clobber=clobber)
                except IOErr:
                    # If this errors out then so be it
                    sherpa.io.write_data(filename, d, clobber=clobber)

    def pack_pha(self, id=None):
        """Convert a PHA data set into a file structure.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.

        Returns
        -------
        pha
           The return value depends on the I/O library in use.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.

        See Also
        --------
        load_pha : Load a file as a PHA data set.
        set_data : Set a data set.
        unpack_pha : Create a PHA data structure.

        """
        return sherpa.astro.io.pack_pha(self._get_pha_data(id))

    def pack_image(self, id=None):
        """Convert a data set into an image structure.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.

        Returns
        -------
        img
           The return value depends on the I/O library in use.

        See Also
        --------
        load_image : Load an image as a data set.
        set_data : Set a data set.
        unpack_image : Create an image data structure.

        """
        return sherpa.astro.io.pack_image(self.get_data(id))

    def pack_table(self, id=None):
        """Convert a data set into a table structure.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.

        Returns
        -------
        tbl
           The return value depends on the I/O library in use and the
           type of data (such as `Data1D`, `Data2D`).

        See Also
        --------
        load_table : Load a FITS binary file as a data set.
        set_data : Set a data set.
        unpack_table : Unpack a FITS binary file into a data structure.

        """
        return sherpa.astro.io.pack_table(self.get_data(id))

    @staticmethod
    def create_arf(elo, ehi, specresp=None, exposure=None, ethresh=None,
                   name='test-arf'):
        """Create an ARF.

        .. versionadded:: 4.10.1

        Parameters
        ----------
        elo, ehi : numpy.ndarray
            The energy bins (low and high, in keV) for the ARF. It is
            assumed that ehi_i > elo_i, elo_j > 0, the energy bins are
            either ascending - so elo_i+1 > elo_i - or descending
            (elo_i+1 < elo_i), and that there are no overlaps.
        specresp : None or array, optional
            The spectral response (in cm^2) for the ARF. It is assumed
            to be >= 0. If not given a flat response of 1.0 is used.
        exposure : number or None, optional
            If not None, the exposure of the ARF in seconds.
        ethresh : number or None, optional
            Passed through to the DataARF call. It controls whether
            zero-energy bins are replaced.
        name : str, optional
            The name of the ARF data set

        Returns
        -------
        arf : DataARF instance

        See Also
        --------
        create_rmf, get_arf, set_arf, unpack_arf

        Examples
        --------

        Create a flat ARF, with a value of 1.0 cm^2 for each bin,
        over the energy range 0.1 to 10 keV, with a bin spacing of
        0.01 keV.

        >>> egrid = np.arange(0.1, 10, 0.01)
        >>> arf = create_arf(egrid[:-1], egrid[1:])

        Create an ARF that has 10 percent more area than the ARF
        from the default data set::

        >>> arf1 = get_arf()
        >>> elo = arf1.energ_lo
        >>> ehi = arf1.energ_hi
        >>> y = 1.1 * arf1.specresp
        >>> arf2 = create_arf(elo, ehi, y, exposure=arf1.exposure)

        """
        return create_arf(elo, ehi, specresp, exposure, ethresh, name)

    @staticmethod
    def create_rmf(rmflo, rmfhi, startchan=1, e_min=None, e_max=None,
                   ethresh=None, fname=None, name='delta-rmf'):
        """Create an RMF.

        If fname is set to `None` then this creats a "perfect" RMF,
        which has a delta-function response (so each channel uniquely
        maps to a single energy bin), otherwise the RMF is taken from
        the image data stored in the file pointed to by `fname`.

        .. versionadded:: 4.10.1

        Parameters
        ----------
        rmflo, rmfhi : array
            The energy bins (low and high, in keV) for the RMF.
            It is assumed that emfhi_i > rmflo_i, rmflo_j > 0, that the energy
            bins are either ascending, so rmflo_i+1 > rmflo_i or descending
            (rmflo_i+1 < rmflo_i), and that there are no overlaps.
            These correspond to the Elow and Ehigh columns (represented
            by the ENERG_LO and ENERG_HI columns of the MATRIX block) of
            the OGIP standard.
        startchan : int, optional
            The starting channel number: expected to be 0 or 1 but this is
            not enforced.
        e_min, e_max : None or array, optional
            The E_MIN and E_MAX columns of the EBOUNDS block of the
            RMF.
        ethresh : number or None, optional
            Passed through to the DataRMF call. It controls whether
            zero-energy bins are replaced.
        fname : None or str, optional
            If None then a "perfect" RMF is generated, otherwise it gives
            the name of the two-dimensional image file which stores the
            response information (the format of this file matches that
            created by the CIAO tool rmfimg [1]_).
        name : str, optional
            The name of the RMF data set

        Returns
        -------
        rmf : DataRMF instance

        See Also
        --------
        create_arf, get_rmf, set_rmf, unpack_rmf

        References
        ----------

        .. [1] http://cxc.harvard.edu/ciao/ahelp/rmfimg.html

        """

        if fname is None:
            return create_delta_rmf(rmflo, rmfhi, offset=startchan,
                                    e_min=e_min, e_max=e_max, ethresh=ethresh,
                                    name=name)

        return create_non_delta_rmf(rmflo, rmfhi, fname,
                                    offset=startchan, e_min=e_min,
                                    e_max=e_max, ethresh=ethresh,
                                    name=name)

    def get_arf(self, id=None, resp_id=None, bkg_id=None):
        """Return the ARF associated with a PHA data set.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        resp_id : int or str, optional
           The identifier for the ARF within this data set, if there
           are multiple responses.
        bkg_id : int or str, optional
           Set this to return the given background component.

        Returns
        -------
        arf : a `sherpa.astro.instrument.ARF1D` instance
           This is a reference to the ARF, rather than a copy, so that
           changing the fields of the object will change the values in
           the data set.

        See Also
        --------
        fake_pha : Simulate a PHA data set from a model.
        get_response: Return the respone information applied to a PHA data set.
        load_arf : Load an ARF from a file and add it to a PHA data set.
        load_pha : Load a file as a PHA data set.
        set_full_model : Define the convolved model expression for a data set.
        set_arf : Set the ARF for use by a PHA data set.
        set_rmf : Set the RMF for use by a PHA data set.
        unpack_arf : Read in an ARF from a file.

        Examples
        --------

        Return the exposure field of the ARF from the default data
        set:

        >>> get_arf().exposure

        Copy the ARF from the default data set to data set 2:

        >>> arf1 = get_arf()
        >>> set_arf(2, arf1)

        Retrieve the ARF associated to the second background
        component of the 'core' data set:

        >>> bgarf = get_arf('core', 'bkg.arf', bkg_id=2)

        Retrieve the ARF and RMF for the default data set and
        use them to create a model expression which includes
        a power-law component (pbgnd) that is not convolved by the
        response:

        >>> arf = get_arf()
        >>> rmf = get_rmf()
        >>> src_expr = xsphabs.abs1 * powlaw1d.psrc
        >>> set_full_model(rmf(arf(src_expr)) + powlaw1d.pbgnd)
        >>> print(get_model())

        """
        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)

        arf, rmf = data.get_response(resp_id)
        if arf is None:
            raise IdentifierErr('getitem', 'ARF data set',
                                data._fix_response_id(resp_id),
                                'in PHA data set %s has not been set' %
                                str(self._fix_id(id)))

        if isinstance(arf, sherpa.astro.data.DataARF):
            arf = sherpa.astro.instrument.ARF1D(arf, data, rmf)

        return arf

    # DOC-TODO: add an example of a grating/multiple response
    def set_arf(self, id, arf=None, resp_id=None, bkg_id=None):
        """Set the ARF for use by a PHA data set.

        Set the effective area curve for a PHA data set, or its
        background.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        arf
           An ARF, such as returned by `get_arf` or `unpack_arf`.
        resp_id : int or str, optional
           The identifier for the ARF within this data set, if there
           are multiple responses.
        bkg_id : int or str, optional
           Set this to identify the ARF as being for use with the
           background.

        See Also
        --------
        get_arf : Return the ARF associated with a PHA data set.
        load_arf : Load an ARF from a file and add it to a PHA data set.
        load_pha : Load a file as a PHA data set.
        set_full_model : Define the convolved model expression for a data set.
        set_rmf : Set the RMF for use by a PHA data set.
        unpack_arf : Read in an ARF from a file.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `arf` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `arf` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        If a PHA data set has an associated ARF - either from when the
        data was loaded or explicitly with the `set_arf` function -
        then the model fit to the data will include the effect of the
        ARF when the model is created with `set_model` or
        `set_source`. In this case the `get_source` function returns
        the user model, and `get_model` the model that is fit to the
        data (i.e. it includes any response information; that is the
        ARF and RMF, if set). To include the ARF explicitly, use
        `set_full_model`.

        Examples
        --------

        Copy the ARF from the default data set to data set 2:

        >>> arf1 = get_arf()
        >>> set_arf(2, arf1)

        Read in an ARF from the file 'bkg.arf' and set it as the
        ARF for the background model of data set "core":

        >>> arf = unpack_arf('bkg.arf')
        >>> set_arf('core', arf, bkg_id=1)

        """
        if arf is None:
            id, arf = arf, id

        # store only the ARF dataset in the PHA response dict
        if type(arf) in (sherpa.astro.instrument.ARF1D,):
            arf = arf._arf
        _check_type(arf, sherpa.astro.data.DataARF, 'arf', 'an ARF data set')

        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
        data.set_arf(arf, resp_id)
        # Set units of source dataset from channel to energy
        if data.units == 'channel':
            data._set_initial_quantity()

    def unpack_arf(self, arg):
        """Create an ARF data structure.

        Parameters
        ----------
        arg
           Identify the ARF: a file name, or a data structure
           representing the data to use, as used by the I/O backend in
           use by Sherpa: a ``TABLECrate`` for crates, as used by CIAO,
           or a list of AstroPy HDU objects.

        Returns
        -------
        arf : a `sherpa.astro.instrument.ARF1D` instance

        See Also
        --------
        get_arf : Return the ARF associated with a PHA data set.
        load_arf : Load an ARF from a file and add it to a PHA data set.
        load_bkg_arf : Load an ARF from a file and add it to the background of a PHA data set.
        load_multi_arfs : Load multiple ARFs for a PHA data set.
        load_pha : Load a file as a PHA data set.
        load_rmf : Load a RMF from a file and add it to a PHA data set.
        set_full_model : Define the convolved model expression for a data set.

        Notes
        -----
        The `minimum_energy` setting of the `ogip` section of the
        Sherpa configuration file determines the behavior when an
        ARF with a minimum energy of 0 is read in. The default is
        to replace the 0 by the value 1e-10, which will also cause
        a warning message to be displayed.

        Examples
        --------

        >>> arf1 = unpack_arf("arf1.fits")
        >>> arf2 = unpack_arf("arf2.fits")

        Read in an ARF using Crates:

        >>> acr = pycrates.read_file("src.arf")
        >>> arf = unpack_arf(acr)

        Read in an ARF using AstroPy:

        >>> hdus = astropy.io.fits.open("src.arf")
        >>> arf = unpack_arf(hdus)

        """
        return sherpa.astro.instrument.ARF1D(sherpa.astro.io.read_arf(arg))

    # DOC-TODO: add an example of a grating/multiple response
    # DOC-TODO: how to describe I/O backend support?
    def load_arf(self, id, arg=None, resp_id=None, bkg_id=None):
        """Load an ARF from a file and add it to a PHA data set.

        Load in the effective area curve for a PHA data set, or its
        background. The `load_bkg_arf` function can be used for
        setting most background ARFs.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        arg
           Identify the ARF: a file name, or a data structure
           representing the data to use, as used by the I/O backend in
           use by Sherpa: a ``TABLECrate`` for crates, as used by CIAO,
           or a list of AstroPy HDU objects.
        resp_id : int or str, optional
           The identifier for the ARF within this data set, if there
           are multiple responses.
        bkg_id : int or str, optional
           Set this to identify the ARF as being for use with the
           background.

        See Also
        --------
        get_arf : Return the ARF associated with a PHA data set.
        load_bkg_arf : Load an ARF from a file and add it to the background of a PHA data set.
        load_multi_arfs : Load multiple ARFs for a PHA data set.
        load_pha : Load a file as a PHA data set.
        load_rmf : Load a RMF from a file and add it to a PHA data set.
        set_full_model : Define the convolved model expression for a data set.
        set_arf : Set the ARF for use by a PHA data set.
        unpack_arf : Create an ARF data structure.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `arg` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `arg` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        If a PHA data set has an associated ARF - either from when the
        data was loaded or explicitly with the `set_arf` function -
        then the model fit to the data will include the effect of the
        ARF when the model is created with `set_model` or
        `set_source`. In this case the `get_source` function returns
        the user model, and `get_model` the model that is fit to the
        data (i.e. it includes any response information; that is the
        ARF and RMF, if set). To include the ARF explicitly, use
        `set_full_model`.

        The `minimum_energy` setting of the `ogip` section of the
        Sherpa configuration file determines the behavior when an
        ARF with a minimum energy of 0 is read in. The default is
        to replace the 0 by the value 1e-10, which will also cause
        a warning message to be displayed.

        Examples
        --------

        Use the contents of the file 'src.arf' as the ARF for the
        default data set.

        >>> load_arf('src.arf')

        Read in an ARF from the file 'bkg.arf' and set it as the
        ARF for the background model of data set "core":

        >>> load_arf('core', 'bkg.arf', bkg_id=1)

        """
        if arg is None:
            id, arg = arg, id
        self.set_arf(id, self.unpack_arf(arg), resp_id, bkg_id)

    def get_bkg_arf(self, id=None):
        """Return the background ARF associated with a PHA data set.

        This is for the case when there is only one background
        component and one background response. If this does not hold,
        use `get_arf` and use the ``bkg_id`` and ``resp_id`` arguments.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.

        Returns
        -------
        arf : a `sherpa.astro.instrument.ARF1D` instance
           This is a reference to the ARF, rather than a copy, so that
           changing the fields of the object will change the values in
           the data set.

        See Also
        --------
        fake_pha : Simulate a PHA data set from a model.
        load_bkg_arf : Load an ARF from a file and add it to the background of a PHA data set.
        load_pha : Load a file as a PHA data set.
        set_full_model : Define the convolved model expression for a data set.
        set_arf : Set the ARF for use by a PHA data set.
        set_rmf : Set the RMF for use by a PHA data set.
        unpack_arf : Read in an ARF from a file.

        Examples
        --------

        Return the exposure field of the ARF from the background of
        the default data set:

        >>> get_bkg_arf().exposure

        Copy the ARF from the default data set to data set 2,
        as the first component:

        >>> arf1 = get_bkg_arf()
        >>> set_arf(2, arf1, bkg_id=1)

        """
        bkg_id = self._get_pha_data(id).default_background_id
        resp_id = self._get_pha_data(id).primary_response_id
        return self.get_arf(id, resp_id, bkg_id)

    # DOC-TODO: how to describe I/O backend support?
    def load_bkg_arf(self, id, arg=None):
        """Load an ARF from a file and add it to the background of a
        PHA data set.

        Load in the ARF to the background of the given data set. It
        is only for use when there is only one background component,
        and one response, for the source. For multiple backgrounds
        or responses, use `load_arf`.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        arg
           Identify the ARF: a file name, or a data structure
           representing the data to use, as used by the I/O backend in
           use by Sherpa: a ``TABLECrate`` for crates, as used by CIAO,
           or a list of AstroPy HDU objects.

        See Also
        --------
        load_arf : Load an ARF from a file and add it to a PHA data set.
        load_bkg_rmf : Load a RMF from a file and add it to the background of a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `arg` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `arg` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The `minimum_energy` setting of the `ogip` section of the
        Sherpa configuration file determines the behavior when an
        ARF with a minimum energy of 0 is read in. The default is
        to replace the 0 by the value 1e-10, which will also cause
        a warning message to be displayed.

        Examples
        --------

        Use the contents of the file 'bkg.arf' as the ARF for the
        background of the default data set.

        >>> load_bkg_arf('bkg.arf')

        Set 'core_bkg.arf' as the ARF for the background of data set
        'core':

        >>> load_bkg_arf('core', 'core_bkg.arf')

        """
        if arg is None:
            id, arg = arg, id
        bkg_id = self._get_pha_data(id).default_background_id
        resp_id = self._get_pha_data(id).primary_response_id
        self.set_arf(id, self.unpack_arf(arg), resp_id, bkg_id)

    def load_multi_arfs(self, id, filenames, resp_ids=None):
        """Load multiple ARFs for a PHA data set.

        A grating observation - such as a Chandra LETGS data set - may
        require multiple responses if the detector has insufficient energy
        resolution to sort the photons into orders. In this case, the
        extracted spectrum will contain the signal from more than one
        diffraction orders.

        This function lets the multiple ARFs for such a data set be
        loaded with one command. The `load_arf` function can instead
        be used to load them in individually.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        filenames : iterable of str
           An array of file names.
        resp_ids : iterable of int or str
           The identifiers for the ARF within this data set.
           The length should match the filenames argument.

        See Also
        --------
        load_arf : Load an ARF from a file and add it to a PHA data set.
        load_multi_rmfs : Load multiple RMFs for a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with two arguments, they are assumed to be
        ``filenames`` and ``resp_ids``, and three positional arguments
        means `id`, ``filenames``, and ``resp_ids``.

        The `minimum_energy` setting of the `ogip` section of the
        Sherpa configuration file determines the behavior when an
        ARF with a minimum energy of 0 is read in. The default is
        to replace the 0 by the value 1e-10, which will also cause
        a warning message to be displayed.

        Examples
        --------

        Load three ARFs into the default data set, using response ids of
        1, 2, and 3 for the LETG/HRC-S orders 1, 2, and 3 respectively:

        >>> arfs = ['leg_p1.arf', 'leg_p2.arf', 'leg_p3.arf']
        >>> load_multi_arfs(arfs, [1, 2, 3])

        Load in the ARFs to the data set with the identifier
        'lowstate':

        >>> load_multi_arfs('lowstate', arfs, [1, 2, 3])

        """
# if type(filenames) not in (list, tuple):
#             raise ArgumentError('Filenames must be contained in a list')
# if type(resp_ids) not in (list, tuple):
#             raise ArgumentError('Response IDs must be contained in a list')

        if resp_ids is None:
            id, filenames, resp_ids = resp_ids, id, filenames

        filenames = list(filenames)
        resp_ids = list(resp_ids)

        if len(filenames) != len(resp_ids):
            raise ArgumentErr('multirsp')

        for filename, resp_id in zip(filenames, resp_ids):
            self.load_arf(id, filename, resp_id)

    def get_rmf(self, id=None, resp_id=None, bkg_id=None):
        """Return the RMF associated with a PHA data set.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        resp_id : int or str, optional
           The identifier for the RMF within this data set, if there
           are multiple responses.
        bkg_id : int or str, optional
           Set this to return the given background component.

        Returns
        -------
        rmf : a `sherpa.astro.instrument.RMF1D` instance
           This is a reference to the RMF, rather than a copy, so that
           changing the fields of the object will change the values in
           the data set.

        See Also
        --------
        fake_pha : Simulate a PHA data set from a model.
        get_response: Return the respone information applied to a PHA data set.
        load_pha : Load a file as a PHA data set.
        load_rmf : Load a RMF from a file and add it to a PHA data set.
        set_full_model : Define the convolved model expression for a data set.
        set_arf : Set the ARF for use by a PHA data set.
        set_rmf : Set the RMF for use by a PHA data set.
        unpack_rmf : Read in a RMF from a file.

        Examples
        --------

        Copy the RMF from the default data set to data set 2:

        >>> rmf1 = get_rmf()
        >>> set_rmf(2, rmf1)

        Retrieve the RMF associated to the second background
        component of the 'core' data set:

        >>> bgrmf = get_rmf('core', 'bkg.rmf', bkg_id=2)

        Retrieve the ARF and RMF for the default data set and
        use them to create a model expression which includes
        a power-law component (pbgnd) that is not convolved by the
        response:

        >>> arf = get_arf()
        >>> rmf = get_rmf()
        >>> src_expr = xsphabs.abs1 * powlaw1d.psrc
        >>> set_full_model(rmf(arf(src_expr)) + powlaw1d.pbgnd)
        >>> print(get_model())

        """
        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)

        arf, rmf = data.get_response(resp_id)
        if rmf is None:
            raise IdentifierErr('getitem', 'RMF data set',
                                data._fix_response_id(resp_id),
                                'in PHA data set %s has not been set' %
                                str(self._fix_id(id)))

        if isinstance(rmf, sherpa.astro.data.DataRMF):
            rmf = sherpa.astro.instrument.RMF1D(rmf, data, arf)

        return rmf

    # DOC-TODO: add an example of a grating/multiple response
    def set_rmf(self, id, rmf=None, resp_id=None, bkg_id=None):
        """Set the RMF for use by a PHA data set.

        Set the redistribution matrix for a PHA data set, or its
        background.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        rmf
           An RMF, such as returned by `get_rmf` or `unpack_rmf`.
        resp_id : int or str, optional
           The identifier for the RMF within this data set, if there
           are multiple responses.
        bkg_id : int or str, optional
           Set this to identify the RMF as being for use with the
           background.

        See Also
        --------
        get_rmf : Return the RMF associated with a PHA data set.
        load_pha : Load a file as a PHA data set.
        load_rmf : Load a RMF from a file and add it to a PHA data set.
        set_full_model : Define the convolved model expression for a data set.
        set_arf : Set the ARF for use by a PHA data set.
        unpack_rmf : Create a RMF data structure.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `rmf` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `rmf` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        If a PHA data set has an associated RMF - either from when the
        data was loaded or explicitly with the `set_rmf` function -
        then the model fit to the data will include the effect of the
        RMF when the model is created with `set_model` or
        `set_source`. In this case the `get_source` function returns
        the user model, and `get_model` the model that is fit to the
        data (i.e. it includes any response information; that is the
        ARF and RMF, if set). To include the RMF explicitly, use
        `set_full_model`.

        Examples
        --------

        Copy the RMF from the default data set to data set 2:

        >>> rmf1 = get_rmf()
        >>> set_rmf(2, rmf1)

        Read in a RMF from the file 'bkg.rmf' and set it as the
        RMF for the background model of data set "core":

        >>> rmf = unpack_rmf('bkg.rmf')
        >>> set_rmf('core', rmf, bkg_id=1)

        """
        if rmf is None:
            id, rmf = rmf, id

        # store only the RMF dataset in the PHA response dict
        if type(rmf) in (sherpa.astro.instrument.RMF1D,):
            rmf = rmf._rmf
        _check_type(rmf, sherpa.astro.data.DataRMF, 'rmf', 'an RMF data set')

        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
        data.set_rmf(rmf, resp_id)
        # Set units of source dataset from channel to energy
        if data.units == 'channel':
            data._set_initial_quantity()

    def unpack_rmf(self, arg):
        """Create a RMF data structure.

        Parameters
        ----------
        arg
           Identify the RMF: a file name, or a data structure
           representing the data to use, as used by the I/O backend in
           use by Sherpa: a ``RMFCrateDataset`` for crates, as used by
           CIAO, or a list of AstroPy HDU objects.

        Returns
        -------
        rmf : a `sherpa.astro.instrument.RMF1D` instance

        See Also
        --------
        get_rmf : Return the RMF associated with a PHA data set.
        load_arf : Load a RMF from a file and add it to a PHA data set.
        load_bkg_rmf : Load a RMF from a file and add it to the background of a PHA data set.
        load_multi_rmfs : Load multiple RMFs for a PHA data set.
        load_pha : Load a file as a PHA data set.
        load_rmf : Load a RMF from a file and add it to a PHA data set.
        set_full_model : Define the convolved model expression for a data set.

        Notes
        -----
        The `minimum_energy` setting of the `ogip` section of the
        Sherpa configuration file determines the behavior when an
        RMF with a minimum energy of 0 is read in. The default is
        to replace the 0 by the value 1e-10, which will also cause
        a warning message to be displayed.

        Examples
        --------

        >>> rmf1 = unpack_rmf("rmf1.fits")
        >>> rmf2 = unpack_rmf("rmf2.fits")

        Read in a RMF using Crates:

        >>> acr = pycrates.read_rmf("src.rmf")
        >>> rmf = unpack_rmf(acr)

        Read in a RMF using AstroPy:

        >>> hdus = astropy.io.fits.open("src.rmf")
        >>> rmf = unpack_rmf(hdus)

        """
        return sherpa.astro.instrument.RMF1D(sherpa.astro.io.read_rmf(arg))

    # DOC-TODO: add an example of a grating/multiple response
    # DOC-TODO: how to describe I/O backend support?
    def load_rmf(self, id, arg=None, resp_id=None, bkg_id=None):
        """Load a RMF from a file and add it to a PHA data set.

        Load in the redistribution matrix function for a PHA data set,
        or its background. The `load_bkg_rmf` function can be used for
        setting most background RMFs.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        arg
           Identify the RMF: a file name, or a data structure
           representing the data to use, as used by the I/O
           backend in use by Sherpa: a ``RMFCrateDataset`` for
           crates, as used by CIAO, or an AstroPy ``HDUList`` object.
        resp_id : int or str, optional
           The identifier for the RMF within this data set, if there
           are multiple responses.
        bkg_id : int or str, optional
           Set this to identify the RMF as being for use with the
           background.

        See Also
        --------
        get_rmf : Return the RMF associated with a PHA data set.
        load_bkg_rmf : Load a RMF from a file and add it to the background of a PHA data set.
        load_arf : Load an ARF from a file and add it to a PHA data set.
        load_multi_rmfs : Load multiple RMFs for a PHA data set.
        load_pha : Load a file as a PHA data set.
        set_full_model : Define the convolved model expression for a data set.
        set_rmf : Load a RMF from a file and add it to a PHA data set.
        unpack_rmf : Read in a RMF from a file.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `arg` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `arg` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        If a PHA data set has an associated RMF - either from when the
        data was loaded or explicitly with the `set_rmf` function -
        then the model fit to the data will include the effect of the
        RMF when the model is created with `set_model` or
        `set_source`. In this case the `get_source` function returns
        the user model, and `get_model` the model that is fit to the
        data (i.e. it includes any response information; that is the
        ARF and RMF, if set). To include the RMF explicitly, use
        `set_full_model`.

        The `minimum_energy` setting of the `ogip` section of the
        Sherpa configuration file determines the behavior when an
        RMF with a minimum energy of 0 is read in. The default is
        to replace the 0 by the value 1e-10, which will also cause
        a warning message to be displayed.

        Examples
        --------

        Use the contents of the file 'src.rmf' as the RMF for the
        default data set.

        >>> load_rmf('src.rmf')

        Read in a RMF from the file 'bkg.rmf' and set it as the
        RMF for the background model of data set "core":

        >>> load_rmf('core', 'bkg.rmf', bkg_id=1)

        """
        if arg is None:
            id, arg = arg, id
        self.set_rmf(id, self.unpack_rmf(arg), resp_id, bkg_id)

    def get_bkg_rmf(self, id=None):
        """Return the background RMF associated with a PHA data set.

        This is for the case when there is only one background
        component and one background response. If this does not hold,
        use `get_rmf` and use the ``bkg_id`` and ``resp_id`` arguments.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.

        Returns
        -------
        rmf : a `sherpa.astro.instrument.RMF1D` instance
           This is a reference to the RMF, rather than a copy, so that
           changing the fields of the object will change the values in
           the data set.

        See Also
        --------
        fake_pha : Simulate a PHA data set from a model.
        load_bkg_rmf : Load a RMF from a file and add it to the background of a PHA data set.
        load_pha : Load a file as a PHA data set.
        set_full_model : Define the convolved model expression for a data set.
        set_arf : Set the ARF for use by a PHA data set.
        set_rmf : Set the RMF for use by a PHA data set.
        unpack_rmf : Read in a RMF from a file.

        Examples
        --------

        Copy the RMF from the default data set to data set 2,
        as the first component:

        >>> rmf1 = get_bkg_arf()
        >>> set_rmf(2, arf1, bkg_id=1)

        """
        bkg_id = self._get_pha_data(id).default_background_id
        resp_id = self._get_pha_data(id).primary_response_id
        return self.get_rmf(id, resp_id, bkg_id)

    # DOC-TODO: how to describe I/O backend support?
    def load_bkg_rmf(self, id, arg=None):
        """Load a RMF from a file and add it to the background of a
        PHA data set.

        Load in the RMF to the background of the given data set. It
        is only for use when there is only one background component,
        and one response, for the source. For multiple backgrounds
        or responses, use `load_rmf`.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        arg
           Identify the RMF: a file name, or a data structure
           representing the data to use, as used by the I/O
           backend in use by Sherpa: a ``RMFCrateDataset`` for
           crates, as used by CIAO, or an AstroPy ``HDUList`` object.

        See Also
        --------
        load_rmf : Load a RMF from a file and add it to a PHA data set.
        load_bkg_arf : Load an ARF from a file and add it to the background of a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `arg` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `arg` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        The `minimum_energy` setting of the `ogip` section of the
        Sherpa configuration file determines the behavior when an
        RMF with a minimum energy of 0 is read in. The default is
        to replace the 0 by the value 1e-10, which will also cause
        a warning message to be displayed.

        Examples
        --------

        Use the contents of the file 'bkg.rmf' as the RMF for the
        background of the default data set.

        >>> load_bkg_rmf('bkg.rmf')

        Set 'core_bkg.rmf' as the RMF for the background of data set
        'core':

        >>> load_bkg_arf('core', 'core_bkg.rmf')

        """
        if arg is None:
            id, arg = arg, id
        bkg_id = self._get_pha_data(id).default_background_id
        resp_id = self._get_pha_data(id).primary_response_id
        self.set_rmf(id, self.unpack_rmf(arg), resp_id, bkg_id)

    def load_multi_rmfs(self, id, filenames, resp_ids=None):
        """Load multiple RMFs for a PHA data set.

        A grating observation - such as a Chandra LETGS data set - may
        require multiple responses if the detector has insufficient energy
        resolution to sort the photons into orders. In this case, the
        extracted spectrum will contain the signal from more than one
        diffraction orders.

        This function lets the multiple RMFs for such a data set be loaded
        with one command. The `load_rmf` function can instead be used
        to load them in individually.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        filenames : iterable of str
           An array of file names.
        resp_ids : iterable of int or str
           The identifiers for the RMF within this data set.
           The length should match the filenames argument.

        See Also
        --------
        load_rmf : Load a RMF from a file and add it to a PHA data set.
        load_multi_arfs : Load multiple ARFs for a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with two arguments, they are assumed to be
        ``filenames`` and ``resp_ids``, and three positional arguments
        means `id`, ``filenames``, and ``resp_ids``.

        The `minimum_energy` setting of the `ogip` section of the
        Sherpa configuration file determines the behavior when an
        RMF with a minimum energy of 0 is read in. The default is
        to replace the 0 by the value 1e-10, which will also cause
        a warning message to be displayed.

        Examples
        --------

        Load three ARFs into the default data set, using response ids of
        1, 2, and 3 for the LETG/HRC-S orders 1, 2, and 3 respectively:

        >>> arfs = ['leg_p1.rmf', 'leg_p2.rmf', 'leg_p3.rmf']
        >>> load_multi_rmfs(rmfs, [1, 2, 3])

        Load in the RMFs to the data set with the identifier
        'lowstate':

        >>> load_multi_rmfs('lowstate', rmfs, [1, 2, 3])

        """
# if type(filenames) not in (list, tuple):
#             raise ArgumentError('Filenames must be contained in a list')
# if type(resp_ids) not in (list, tuple):
#             raise ArgumentError('Response IDs must be contained in a list')

        if resp_ids is None:
            id, filenames, resp_ids = resp_ids, id, filenames

        filenames = list(filenames)
        resp_ids = list(resp_ids)

        if len(filenames) != len(resp_ids):
            raise ArgumentErr('multirsp')

        for filename, resp_id in zip(filenames, resp_ids):
            self.load_rmf(id, filename, resp_id)

    def get_bkg(self, id=None, bkg_id=None):
        """Return the background for a PHA data set.

        Function to return the background for a PHA data set.
        The object returned by the call can be used to query and
        change properties of the background.

        Parameters
        ----------
        id : int or str, optional
           The data set. If not given then the default
           identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           The identifier for this background, which is needed if
           there are multiple background estimates for the source.

        Returns
        -------
        data : a sherpa.astro.data.DataPHA object

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.
        sherpa.utils.err.IdentifierErr
           If no data set is associated with this identifier.

        See Also
        --------
        get_data : Return the data set by identifier.
        load_bkg : Load the backgreound from a file and add it to a PHA data set.
        set_bkg : Set the background for a PHA data set.

        Examples
        --------

        >>> bg = get_bkg()

        >>> bg = get_bkg('flare', 2)

        """
        data = self._get_pha_data(id)
        bkg = data.get_background(bkg_id)
        if bkg is None:
            raise IdentifierErr('getitem', 'background data set',
                                data._fix_background_id(bkg_id),
                                'in PHA data set %s has not been set' %
                                str(self._fix_id(id)))
        return bkg

    def set_bkg(self, id, bkg=None, bkg_id=None):
        """Set the background for a PHA data set.

        The background can either be fit with a model - using
        `set_bkg_model` - or removed from the data before fitting,
        using `subtract`.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        bkg
           A PHA data set, such as returned by `get_data` or
           `unpack_pha`.
        bkg_id : int or str, optional
           The identifier for this background, which is needed if
           there are multiple background estimates for the source.

        See Also
        --------
        get_bkg : Return the background for a PHA data set.
        load_bkg : Load the background from a file and add it to a PHA data set.
        load_pha : Load a file as a PHA data set.
        set_bkg_model : Set the background model expression for a data set.
        subtract : Subtract the background estimate from a data set.
        unpack_pha : Create a PHA data structure.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `bkg` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `bkg` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        If the background has no grouping of quality arrays then they
        are copied from the source region. If the background has no
        response information (ARF or RMF) then the response is copied
        from the source region.

        Examples
        --------

        Copy the background from the default data set to data set 2:

        >>> bkg1 = get_bkg()
        >>> set_bkg(2, bkg1)

        Read in the PHA data from the file 'bkg.pi' and set it as the
        second background component of data set "core":

        >>> bkg = unpack_pha('bkg.pi')
        >>> set_bkg('core', bkg, bkg_id=2)

        """
        if bkg is None:
            id, bkg = bkg, id
        data = self._get_pha_data(id)
        _check_type(bkg, sherpa.astro.data.DataPHA, 'bkg', 'a PHA data set')
        data.set_background(bkg, bkg_id)

    def list_bkg_ids(self, id=None):
        """List all the background identifiers for a data set.

        A PHA data set can contain multiple background datasets, each
        identified by an integer or string. This function returns a
        list of these identifiers for a data set.

        Parameters
        ----------
        id : int or str, optional
           The data set to query. If not given then the default
           identifier is used, as returned by `get_default_id`.

        Returns
        -------
        ids : array of int or str
           The identifiers for the backround data sets for the data
           set. In many cases this will just be ``[1]``.

        See Also
        --------
        list_response_ids : List all the response identifiers of a data set.
        load_bkg : Load the background of a PHA data set.

        """
        return list(self._get_pha_data(id)._backgrounds.keys())

    def list_response_ids(self, id=None, bkg_id=None):
        """List all the response identifiers of a data set.

        A PHA data set can contain multiple responses, that is,
        pairs of ARF and RMF, each of which has an identifier.
        This function returns a list of these identifiers
        for a data set.

        Parameters
        ----------
        id : int or str, optional
           The data set to query. If not given then the default
           identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Set this to identify the background component to query.

        Returns
        -------
        ids : array of int or str
           The identifiers for the response information for the data
           set. In many cases this will just be ``[1]``.

        See Also
        --------
        list_bkg_ids : List all the background identifiers for a data set.
        load_arf : Load an ARF from a file and add it to a PHA data set.
        load_rmf : Load a RMF from a file and add it to a PHA data set.

        """
        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)

        return list(data._responses.keys())

    # DOC-TODO: docs need to be added to sherpa.astro.data.set_analysis
    # DOC-TODO: should the arguments be renamed to better match optional
    # nature of the routine (e.g. can call set_analysis('energy'))?
    def set_analysis(self, id, quantity=None, type='rate', factor=0):
        """Set the units used when fitting and displaying spectral data.

        The set_analysis command sets the units for spectral
        analysis. Note that in order to change the units of a data set
        from 'channel' to 'energy' or 'wavelength', the appropriate
        ARF and RMF instrument response files must be loaded for that
        data set. The ``type`` and ``factor`` arguments control how
        the data is plotted.

        Parameters
        ----------
        id : int or str
           If only one argument is given then this is taken to be the
           quantity argument (in which case, the change is made to
           all data sets). If multiple arguments are given then this
           is the identifier for the data set to change.
        quantity : { 'channel', 'chan', 'bin', 'energy', 'ener', 'wavelength', 'wave' }
           The units to use for the analysis.
        type : { 'rate', 'counts' }, optional
           The units to use on the Y axis of plots. The default
           is 'rate'.
        factor : int, optional
           The Y axis of plots is multiplied by Energy^factor or
           Wavelength^factor before display. The default is 0.

        Raises
        ------
        sherpa.utils.err.IdentifierErr
           If the `id` argument is not recognized.

        See Also
        --------
        get_analysis : Return the analysis setting for a data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `quantity` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `quantity` parameters,
        respectively.

        Examples
        --------

        Set all loaded data sets to use wavelength for any future
        fitting or display.

        >>> set_analysis('wave')

        Set the data set with an identifier of 2 to use energy
        units.

        >>> set_analysis(2, 'energy')

        Set data set 1 to use channel units. Plots will use a Y
        axis of count/bin rather than the default count/s/bin.

        >>> set_analysis(1, 'bin', 'counts')

        Set data set 1 to use energy units. Plots of this data set
        will display keV on the X axis and counts keV (i.e.
        counts/keV * keV^2) in the Y axis.

        >>> set_analysis(1, 'energy', 'counts', 2)

        """
        if quantity is None:
            id, quantity = quantity, id

        _check_type(quantity, string_types, 'quantity', 'a string')
        _check_type(type, string_types, 'type', 'a string')

        ids = self.list_data_ids()
        if id is not None:
            ids = [id]

        for id in ids:
            self._get_pha_data(id).set_analysis(quantity, type, factor)

    def get_analysis(self, id=None):
        """Return the units used when fitting spectral data.

        Parameters
        ----------
        id : int or str, optional
           The data set to query. If not given then the default
           identifier is used, as returned by `get_default_id`.

        Returns
        -------
        setting : { 'channel', 'energy', 'wavelength' }
           The analysis setting for the data set.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the `id` argument is not recognized.

        See Also
        --------
        get_default_id : Return the default data set identifier.
        set_analysis : Change the analysis setting.

        Examples
        --------

        Display the analysis setting for the default data set:

        >>> print(get_analysis())

        Check whether the data set labelled 'SgrA' is using the
        wavelength setting:

        >>> is_wave = get_analysis('SgrA') == 'wavelength'

        """
        return self._get_pha_data(id).get_analysis()

    # DOC-TODO: docs need to be added to sherpa.astro.data.set_coord
    # DOC-TODO: how best to document the wcssubs support?
    def set_coord(self, id, coord=None):
        """Set the coordinate system to use for image analysis.

        The default coordinate system - that is, the mapping between
        pixel position and coordinate value, for images (2D data sets)
        is 'logical'. This function can change this setting, so that
        model parameters can be fit using other systems. This setting
        is also used by the `notice2d` and `ignore2d` series of
        commands.

        Parameters
        ----------
        id : int or str
           The data set to change. If not given then the default
           identifier is used, as returned by `get_default_id`.
        coord : { 'logical', 'image', 'physical', 'world', 'wcs' }
           The coordinate system to use. The 'image' option is the
           same as 'logical', and 'wcs' the same as 'world'.

        See Also
        --------
        get_coord : Get the coordinate system used for image analysis.
        guess : Estimate the parameter values and ranges given the loaded data.
        ignore2d : Exclude a spatial region from an image.
        notice2d : Include a spatial region of an image.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `coord` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `coord` parameters,
        respectively.

        Any limits or values already set for model parameters, such as
        those made by `guess`, may need to be changed after changing
        the coordinate system.

        The 'logical' system is one in which the center of the
        lower-left pixel has coordinates ``(1, 1)`` and the center of the
        top-right pixel has coordinates ``(nx, ny)``, for a ``nx``
        (columns) by ``ny`` (rows) pixel image. The pixels have a side
        of length 1, so the first pixel covers the range ``x=0.5`` to
        ``x=1.5`` and ``y=0.5`` to ``y=1.5``.

        The 'physical' and 'world' coordinate systems rely on FITS
        World Coordinate System (WCS) standard [1]_. The 'physical'
        system refers to a linear transformation, with possible
        offset, of the 'logical' system. The 'world' system refers to
        the mapping to a celestial coordinate system.

        References
        ----------

        .. [1] http://fits.gsfc.nasa.gov/fits_wcs.html

        Examples
        --------

        Change the coordinate system of the default data set to
        the world system ('wcs' is a synonym for 'world').

        >>> set_coord('wcs')

        Change the data set with the id of 'm82' to use the
        physical coordinate system.

        >>> set_coord('m82', 'physical')

        """
        if coord is None:
            id, coord = coord, id

        _check_type(coord, string_types, 'coord', 'a string')

        ids = self.list_data_ids()
        if id is not None:
            ids = [id]

        if len(ids) == 0:
            raise IdentifierErr('nodatasets')

        for id in ids:
            self._get_img_data(id).set_coord(coord)

    # DOC-TODO: docs need to be added to sherpa.astro.data.get_coord
    def get_coord(self, id=None):
        """Get the coordinate system used for image analysis.

        Parameters
        ----------
        id : int or str, optional
           The data set to query. If not given then the default
           identifier is used, as returned by `get_default_id`.

        Returns
        -------
        coord : { 'logical', 'physical', 'world' }

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain image data.
        sherpa.utils.err.IdentifierErr
           If the `id` argument is not recognized.

        See Also
        --------
        get_default_id : Return the default data set identifier.
        set_coord : Set the coordinate system to use for image analysis.

        """
        return self._get_img_data(id).coord

    def ignore_bad(self, id=None, bkg_id=None):
        """Exclude channels marked as bad in a PHA data set.

        Ignore any bin in the PHA data set which has a quality value
        that is larger than zero.

        Parameters
        ----------
        id : int or str, optional
           The data set to change. If not given then the default
           identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           The identifier for the background (the default of ``None``
           uses the first component).

        Raises
        ------
        sherpa.utils.err.DataErr
           If the data set has no quality array.

        See Also
        --------
        ignore : Exclude data from the fit.
        notice : Include data in the fit.
        set_quality : Apply a set of quality flags to a PHA data set.

        Notes
        -----
        The `load_pha` command - and others that create a PHA data set
        - do not exclude these bad-quality bins automatically.

        If the data set has been grouped, then calling `ignore_bad`
        will remove any filter applied to the data set. If this
        happens a warning message will be displayed.

        Examples
        --------

        Remove any bins that are marked bad in the default data set:

        >>> load_pha('src.pi')
        >>> ignore_bad()

        The data set 'jet' is grouped, and a filter applied. After
        ignoring the bad-quality points, the filter has been removed
        and will need to be re-applied:

        >>> group_counts('jet', 20)
        >>> notice_id('jet', 0.5, 7)
        >>> get_filter('jet')
        '0.496399998665:7.212399959564'
        >>> ignore_bad('jet')
        WARNING: filtering grouped data with quality flags, previous filters deleted
        >>> get_filter('jet')
        '0.001460000058:14.950400352478'

        """
        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
        data.ignore_bad()

    def _notice_warning(self):
        quantities = numpy.asarray([data.get_analysis()
                                    for data in self._data.values()
                                    if isinstance(data,
                                                  sherpa.astro.data.DataPHA)])

        if len(quantities) > 1 and not (quantities == quantities[0]).all():
            warning("not all PHA datasets have equal analysis quantities")

    def notice(self, lo=None, hi=None, **kwargs):

        if lo is not None or hi is not None:
            self._notice_warning()
        sherpa.ui.utils.Session.notice(self, lo, hi, **kwargs)

    notice.__doc__ = sherpa.ui.utils.Session.notice.__doc__

    def ignore(self, lo=None, hi=None, **kwargs):

        if lo is not None or hi is not None:
            self._notice_warning()
        sherpa.ui.utils.Session.ignore(self, lo, hi, **kwargs)

    ignore.__doc__ = sherpa.ui.utils.Session.ignore.__doc__

    # DOC-TODO: how best to document the region support?
    # DOC-TODO: I have not mentioned the support for radii in arcsec/minutes/degrees
    # or sexagessimal formats. Is this supported here?
    def notice2d(self, val=None):
        """Include a spatial region of all data sets.

        Select a spatial region to include in the fit. The filter is
        applied to all data sets.

        Parameters
        ----------
        val : str, optional
           A region specification as a string or the name of a file
           containing a region filter. The coordinates system of the
           filter is taken from the coordinate setting of the data
           sets (`set_coord`). If ``None``, then all points are
           included.

        See Also
        --------
        ignore2d : Exclude a spatial region from all data sets.
        ignore2d_id : Exclude a spatial region from a data set.
        ignore2d_image : Select the region to exclude from the image viewer.
        notice2d_id : Include a spatial region of a data set.
        notice2d_image : Select the region to include from the image viewer.
        set_coord : Set the coordinate system to use for image analysis.

        Notes
        -----
        The region syntax support is provided by the CIAO region
        library [1]_, and supports the following shapes (the
        capitalized parts of the name indicate the minimum length of
        the name that is supported):

        =========  ===================================================
        Name       Arguments
        =========  ===================================================
        RECTangle  (xmin,ymin,xmax,ymax)
        BOX        (xcenter,ycenter,width,height)
        BOX        (xcenter,ycenter,width,height,angle)
        ROTBOX     (xcenter,ycenter,width,height,angle)
        CIRcle     (xcenter,ycenter,radius)
        ANNULUS    (xcenter,ycenter,iradius,oradius)
        ELLipse    (xcenter,ycenter,xradius,yradius,angle)
        SECTor     (xcenter,ycenter,minangle,maxangle)
        PIE        (xcenter,ycenter,iradius,oradius,minangle,maxangle)
        POLYgon    (x1,y1,x2,y2,x3,y3,...)
        POInt      (xcenter,ycenter)
        REGION     (file)
        FIELD      ()
        =========  ===================================================

        Angles are measured in degrees from the X axis, with a
        positive value indicating a counter-clockwise direction.

        Only simple polygons are supported, which means that a polygon
        can not intersect itself. The last point does not need to
        equal the first point (i.e. polygons are automatically closed
        if necessary).

        The shapes can be combined using AND (intersection), OR
        (union), or NOT (negation):

        intersection::

          shape1()*shape2()
          shape1()&shape2()

        union::

          shape1()+shape2()
          shape1()|shape2()
          shape1()shape2()

        negation::

          !shape1()
          shape1()-shape2()
          shape1()*!shape1()

        The precedence uses the same rules as the mathematical
        operators ``+`` and ``*`` (with ``-`` replaced by ``*!``),
        so that::

          circle(0,0,10)+rect(10,-10,20,10)-circle(10,0,10)

        means that the second circle is only excluded from the
        rectangle, and not the first circle. To remove it from both
        shapes requires writing::

          circle(0,0,10)-circle(10,0,10)+rect(10,-10,20,10)-circle(10,0,10)

        A point is included if the center of the pixel lies within
        the region. The comparison is done using the selected
        coordinate system for the image, so a pixel may not
        have a width and height of 1.

        The REGION specifier is only supported when using CIAO.
        Unfortunately you can not combine region shapes using this
        syntax. That is ``region(s1.reg)+region(s2.reg)`` is not
        supported.

        References
        ----------

        .. [1] http://cxc.harvard.edu/ciao/ahelp/dmregions.html

        Examples
        --------

        Include the data points that lie within a circle centered
        at 4324.5,3827.5 with a radius of 300:

        >>> set_coord('physical')
        >>> notice2d('circle(4324.5,3827.5,430)')

        Read in the filter from the file ``ds9.reg``, using either:

        >>> notice2d('ds9.reg')

        or, when using CIAO,

        >>> notice2d('region(ds9.reg)')

        Select those points that lie both within the rotated box and
        the annulus (i.e. an intersection of the two shapes):

        >>> notice2d('rotbox(100,200,50,40,45)*annulus(120,190,20,60)')

        Select those points that lie within the rotated box or the
        annulus (i.e. a union of the two shapes):

        >>> notice2d('rotbox(100,200,50,40,45)+annulus(120,190,20,60)')

        All existing spatial filters are removed:

        >>> notice2d()

        """
        for d in self._data.values():
            _check_type(d, sherpa.astro.data.DataIMG, 'img',
                        'a image data set')
            d.notice2d(val, False)

    def ignore2d(self, val=None):
        """Exclude a spatial region from all data sets.

        Select a spatial region to exclude in the fit. The filter is
        applied to all data sets.

        Parameters
        ----------
        val : str, optional
           A region specification as a string or the name of a file
           containing a region filter. The coordinates system of the
           filter is taken from the coordinate setting of the data
           sets (`set_coord`). If ``None``, then all points are
           included.

        See Also
        --------
        ignore2d_id : Exclude a spatial region from a data set.
        ignore2d_image : Select the region to exclude from the image viewer.
        notice2d : Include a spatial region from all data sets.
        notice2d_id : Include a spatial region of a data set.
        notice2d_image : Select the region to include from the image viewer.
        set_coord : Set the coordinate system to use for image analysis.

        Notes
        -----
        The region syntax is described in the `notice2d` function.

        Examples
        --------

        Exclude points that fall within the two regions:

        >>> ignore2d('ellipse(200,300,40,30,-34)')
        >>> ignore2d('box(40,100,30,40)')

        Use a region file called 'reg.fits', by using either:

        >>> ignore2d('reg.fits')

        or

        >>> ignore2d('region(reg.fits)')

        Exclude all points.

        >>> ignore2d()

        """
        for d in self._data.values():
            _check_type(d, sherpa.astro.data.DataIMG, 'img',
                        'a image data set')
            d.notice2d(val, True)

    def notice2d_id(self, ids, val=None):
        """Include a spatial region of a data set.

        Select a spatial region to include in the fit. The filter is
        applied to the given data set, or sets.

        Parameters
        ----------
        ids : int or str, or array of int or str
           The data set, or sets, to use.
        val : str, optional
           A region specification as a string or the name of a file
           containing a region filter. The coordinates system of the
           filter is taken from the coordinate setting of the data
           sets (`set_coord`). If ``None``, then all points are
           included.

        See Also
        --------
        ignore2d : Exclude a spatial region from all data sets.
        ignore2d_id : Exclude a spatial region from a data set.
        ignore2d_image : Select the region to exclude from the image viewer.
        notice2d : Include a spatial region of all data sets.
        notice2d_image : Select the region to include from the image viewer.
        set_coord : Set the coordinate system to use for image analysis.

        Notes
        -----
        The region syntax is described in the `notice2d` function.

        Examples
        --------

        Select all the pixels in the default data set:

        >>> notice2d_id(1)

        Select all the pixels in data sets 'i1' and 'i2':

        >>> notice2d_id(['i1', 'i2'])

        Apply the filter to the 'img' data set:

        >>> notice2d_id('img', 'annulus(4324.2,3982.2,40.2,104.3)')

        Use the regions in the file `srcs.reg` for data set 1:

        >>> notice2d_id(1, 'srcs.reg')

        or

        >>> notice2d_id(1, 'region(srcs.reg)')

        """
        if self._valid_id(ids):
            ids = (ids,)
        else:
            try:
                ids = tuple(ids)
            except TypeError:
                raise ArgumentTypeErr('badarg', 'ids',
                                      'an identifier or list of identifiers') from None

        for id in ids:
            _check_type(self.get_data(id), sherpa.astro.data.DataIMG,
                        'img', 'a image data set')
            self.get_data(id).notice2d(val, False)

    def ignore2d_id(self, ids, val=None):
        """Exclude a spatial region from a data set.

        Select a spatial region to exclude in the fit. The filter is
        applied to the given data set, or sets.

        Parameters
        ----------
        ids : int or str, or array of int or str
           The data set, or sets, to use.
        val : str, optional
           A region specification as a string or the name of a file
           containing a region filter. The coordinates system of the
           filter is taken from the coordinate setting of the data
           sets (`set_coord`). If ``None``, then all points are
           included.

        See Also
        --------
        ignore2d : Exclude a spatial region from all data sets.
        ignore2d_image : Select the region to exclude from the image viewer.
        notice2d : Include a spatial region of all data sets.
        notice2d_id : Include a spatial region from a data set.
        notice2d_image : Select the region to include from the image viewer.
        set_coord : Set the coordinate system to use for image analysis.

        Notes
        -----
        The region syntax is described in the `notice2d` function.

        Examples
        --------

        Ignore the pixels within the rectangle from data set 1:

        >>> ignore2d_id(1, 'rect(10,10,20,290)')

        Ignore the spatial region in the file `srcs.reg`:

        >>> ignore2d_id(1, 'srcs.reg')

        or

        >>> ignore2d_id(1, 'region(srcs.reg)')

        """
        if self._valid_id(ids):
            ids = (ids,)
        else:
            try:
                ids = tuple(ids)
            except TypeError:
                raise ArgumentTypeErr('badarg', 'ids',
                                      'an identifier or list of identifiers') from None

        for id in ids:
            _check_type(self.get_data(id), sherpa.astro.data.DataIMG,
                        'img', 'a image data set')
            self.get_data(id).notice2d(val, True)

    def notice2d_image(self, ids=None):
        """Include pixels using the region defined in the image viewer.

        Include points that lie within the region defined in the image
        viewer.

        Parameters
        ----------
        ids : int or str, or sequence of int or str, optional
           The data set, or sets, to use. If ``None`` (the default)
           then the default identifier is used, as returned by
           `get_default_id`.

        See Also
        --------
        ignore2d : Exclude a spatial region from an image.
        ignore2d_image : Exclude pixels using the region defined in the image viewer.
        notice2d : Include a spatial region of an image.
        set_coord : Set the coordinate system to use for image analysis.

        Notes
        -----
        The region definition is converted into the coordinate system
        relevant to the data set before it is applied.

        Examples
        --------

        Use the region in the image viewer to include points from the
        default data set.

        >>> notice2d_image()

        Include points in the data set labelled "2".

        >>> notice2d_image(2)

        Include points in data sets "src" and "bg".

        >>> notice2d_image(["src", "bg"])

        """
        if ids is None:
            ids = self._default_id
        if self._valid_id(ids):
            ids = (ids,)
        else:
            try:
                ids = tuple(ids)
            except TypeError:
                raise ArgumentTypeErr('badarg', 'ids',
                                      'an identifier or list of identifiers') from None

        for id in ids:
            _check_type(self.get_data(id), sherpa.astro.data.DataIMG,
                        'img', 'a image data set')
            coord = self.get_coord(id)
            if coord == 'logical':
                coord = 'image'
            elif coord == 'world':
                coord = 'wcs'
            regions = self.image_getregion(coord).replace(';', '')
            self.notice2d_id(id, regions)

    def ignore2d_image(self, ids=None):
        """Exclude pixels using the region defined in the image viewer.

        Exclude points that lie within the region defined in the image
        viewer.

        Parameters
        ----------
        ids : int or str, or sequence of int or str, optional
           The data set, or sets, to ignore. If ``None`` (the default)
           then the default identifier is used, as returned by
           `get_default_id`.

        See Also
        --------
        ignore2d : Exclude a spatial region from an image.
        notice2d : Include a spatial region of an image.
        notice2d_image : Include pixels using the region defined in the image viewer.
        set_coord : Set the coordinate system to use for image analysis.

        Notes
        -----
        The region definition is converted into the coordinate system
        relevant to the data set before it is applied.

        Examples
        --------

        Use the region in the image viewer to ignore points from the
        default data set.

        >>> ignore2d_image()

        Ignore points in the data set labelled "2".

        >>> ignore2d_image(2)

        Ignore points in data sets "src" and "bg".

        >>> ignore2d_image(["src", "bg"])

        """
        if ids is None:
            ids = self._default_id
        if self._valid_id(ids):
            ids = (ids,)
        else:
            try:
                ids = tuple(ids)
            except TypeError:
                raise ArgumentTypeErr('badarg', 'ids',
                                      'an identifier or list of identifiers') from None

        for id in ids:
            _check_type(self.get_data(id), sherpa.astro.data.DataIMG,
                        'img', 'a image data set')
            coord = self.get_coord(id)
            if coord == 'logical':
                coord = 'image'
            elif coord == 'world':
                coord = 'wcs'
            regions = self.image_getregion(coord).replace(';', '')
            self.ignore2d_id(id, regions)

    # DOC-TODO: how best to include datastack support? How is it handled here?
    def load_bkg(self, id, arg=None, use_errors=False, bkg_id=None):
        """Load the background from a file and add it to a PHA data set.

        This will load the PHA data and any response information - so
        ARF and RMF - and add it as a background component to the
        PHA data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        arg
           Identify the data to read: a file name, or a data structure
           representing the data to use, as used by the I/O backend in
           use by Sherpa: a ``PHACrateDataset`` for crates, as used by
           CIAO, or a list of AstroPy HDU objects.
        use_errors : bool, optional
           If ``True`` then the statistical errors are taken from the
           input data, rather than calculated by Sherpa from the
           count values. The default is ``False``.
        bkg_id : int or str, optional
           The identifier for the background (the default of ``None``
           uses the first component).

        See Also
        --------
        load_bkg_arf : Load an ARF from a file and add it to the background of a PHA data set.
        load_bkg_rmf : Load a RMF from a file and add it to the background of a PHA data set.
        load_pha : Load a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `arg` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `arg` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Examples
        --------

        Load a source and background data set:

        >>> load_pha('src.pi')
        read ARF file src.arf
        read RMF file src.rmf
        >>> load_bkg('src_bkg.pi')

        Read in the background via Crates:

        >>> bpha = pycrates.read_pha('src_bkg.pi')
        >>> load_bkg(bpha)

        Create the data set from the data read in by AstroPy:

        >>> bhdus = astropy.io.fits.open('src_bkg.pi')
        >>> load_bkg(bhdus)

        """
        if arg is None:
            id, arg = arg, id

        bkgsets = self.unpack_bkg(arg, use_errors)

        if numpy.iterable(bkgsets):
            for bkgid, bkg in enumerate(bkgsets):
                self.set_bkg(id, bkg, bkgid + 1)
        else:
            self.set_bkg(id, bkgsets, bkg_id)

    def group(self, id=None, bkg_id=None):
        """Turn on the grouping for a PHA data set.

        A PHA data set can be grouped either because it contains
        grouping information [1]_, which is automatically applied when
        the data is read in with `load_pha` or `load_data`, or because
        the `group` set of routines has been used to dynamically
        re-group the data. The `ungroup` function removes this
        grouping (however it was created). The `group` function
        re-applies this grouping. The grouping scheme can be
        changed dynamically, using the ``group_xxx`` series of
        routines.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        bkg_id : int or str, optional
           Set to group the background associated with the data set.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        fit : Fit one or more data sets.
        group_adapt : Adaptively group to a minimum number of counts.
        group_adapt_snr : Adaptively group to a minimum signal-to-noise ratio.
        group_bins : Group into a fixed number of bins.
        group_counts : Group into a minimum number of counts per bin.
        group_snr : Group into a minimum signal-to-noise ratio.
        group_width : Group into a fixed bin width.
        set_grouping : Apply a set of grouping flags to a PHA data set.
        set_quality : Apply a set of quality flags to a PHA data set.
        ungroup : Turn off the grouping for a PHA data set.

        Notes
        -----
        PHA data is often grouped to improve the signal to noise of
        the data, by decreasing the number of bins, so that a
        chi-square statistic can be used when fitting the data.  After
        calling `group`, anything that uses the data set - such as a
        plot, fit, or error analysis - will use the grouped data
        values. Models should be re-fit if `group` is called; the
        increase in the signal of the bins may mean that a chi-square
        statistic can now be used.

        The grouping is implemented by separate arrays to the main
        data - the information is stored in the ``grouping`` and
        ``quality`` arrays of the PHA data set - so that a data set can
        be grouped and ungrouped many times, without losing
        information. The `group` command does not create this
        information; this is either created by modifying the PHA file
        before it is read in, or by using the ``group_xxx`` routines
        once the data has been loaded.

        The ``grouped`` field of a PHA data set is set to ``True`` when
        the data is grouped.

        References
        ----------

        .. [1] Arnaud., K. & George, I., "The OGIP Spectral File
               Format",
               http://heasarc.gsfc.nasa.gov/docs/heasarc/ofwg/docs/spectra/ogip_92_007/ogip_92_007.html

        Examples
        --------

        Group the data in the default data set:

        >>> group()
        >>> get_data().grouped
        True

        Group the first background component of the 'core' data set:

        >>> group('core', bkg_id=1)
        >>> get_bkg('core', bkg_id=1).grouped
        True

        The data is fit using the ungrouped data, and then plots of
        the data and best-fit, and the residuals, are created. The
        first plot uses the ungrouped data, and the second plot uses
        the grouped data.

        >>> ungroup()
        >>> fit()
        >>> plot_fit_resid()
        >>> group()
        >>> plot_fit_resid()

        """
        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)

        if bkg_id is None:
            # First, group backgrounds associated with the
            # data set ID; report if background(s) already grouped.
            for bid in data.background_ids:
                try:
                    self.group(id, bid)
                except DataErr as e:
                    info(str(e))

            # Now check if data is already grouped, and send error message
            # if so
        if not data.grouped:
            data.group()

    def set_grouping(self, id, val=None, bkg_id=None):
        """Apply a set of grouping flags to a PHA data set.

        A group is indicated by a sequence of flag values starting
        with ``1`` and then ``-1`` for all the channels in the group,
        following [1]_.  Setting the grouping column automatically
        turns on the grouping flag for that data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        val : array of int
           This must be an array of grouping values of the same length
           as the data array.
        bkg_id : int or str, optional
           Set to group the background associated with the data set.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        fit : Fit one or more data sets.
        get_grouping : Return the grouping flags for a PHA data set.
        group : Turn on the grouping for a PHA data set.
        group_adapt : Adaptively group to a minimum number of counts.
        group_adapt_snr : Adaptively group to a minimum signal-to-noise ratio.
        group_bins : Group into a fixed number of bins.
        group_counts : Group into a minimum number of counts per bin.
        group_snr : Group into a minimum signal-to-noise ratio.
        group_width : Group into a fixed bin width.
        load_grouping : Load the grouping scheme from a file and add to a PHA data set.
        set_quality : Apply a set of quality flags to a PHA data set.
        ungroup : Turn off the grouping for a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `val` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `val` parameters,
        respectively.

        The meaning of the grouping column is taken from [1]_, which says
        that +1 indicates the start of a bin, -1 if the channel is part
        of group, and 0 if the data grouping is undefined for all channels.

        References
        ----------

        .. [1] "The OGIP Spectral File Format", https://heasarc.gsfc.nasa.gov/docs/heasarc/ofwg/docs/spectra/ogip_92_007/ogip_92_007.html

        Examples
        --------

        Copy the grouping array from data set 2 into the default data
        set:

        >>> grp = get_grouping(2)
        >>> set_grouping(grp)

        Copy the grouping from data set "src1" to the source and the
        first background data set of "src2":

        >>> grp = get_grouping("src1")
        >>> set_grouping("src2", grp)
        >>> set_grouping("src2", grp, bkg_id=1)

        """
        if val is None:
            id, val = val, id

        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)

        if val is None:
            data.grouping = None
        else:
            if(type(val) in (numpy.ndarray,) and
               issubclass(val.dtype.type, numpy.integer)):
                data.grouping = numpy.asarray(val)
            else:
                data.grouping = numpy.asarray(val, SherpaInt)

    def get_grouping(self, id=None, bkg_id=None):
        """Return the grouping array for a PHA data set.

        The function returns the grouping value for each channel in
        the PHA data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        bkg_id : int or str, optional
           Set if the grouping flags should be taken from a background
           associated with the data set.

        Returns
        -------
        grouping : ndarray or ``None``
           A value of ``1`` indicates the start of a new group, and ``-1``
           indicates that the bin is part of the group. This array is
           not filtered - that is, there is one element for each channel
           in the PHA data set.  Changes to the elements of this array will
           change the values in the dataset (it is a reference to the values
           used to define the quality, not a copy).

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        fit : Fit one or more data sets.
        get_quality : Return the quality array for a PHA data set.
        ignore_bad : Exclude channels marked as bad in a PHA data set.
        load_grouping: Load the grouping scheme from a file and add to a PHA data set.
        set_grouping : Apply a set of grouping flags to a PHA data set.

        Notes
        -----
        The meaning of the grouping column is taken from [1]_, which says
        that +1 indicates the start of a bin, -1 if the channel is part
        of group, and 0 if the data grouping is undefined for all channels.

        References
        ----------

        .. [1] "The OGIP Spectral File Format", https://heasarc.gsfc.nasa.gov/docs/heasarc/ofwg/docs/spectra/ogip_92_007/ogip_92_007.html

        Examples
        --------

        Copy the grouping array from the default data set to data set 2:

        >>> grp1 = get_grouping()
        >>> set_grouping(2, grp1)

        Return the grouping array of the background component labelled
        2 for the 'histate' data set:

        >>> grp = get_grouping('histate', bkg_id=2)

        """

        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)

        return data.grouping

    def set_quality(self, id, val=None, bkg_id=None):
        """Apply a set of quality flags to a PHA data set.

        A quality value of 0 indicates a good channel,
        otherwise (values >=1) the channel is considered bad and can be
        excluded using the `ignore_bad` function, as discussed
        in [1]_.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        val : array of int
           This must be an array of quality values of the same length
           as the data array.
        bkg_id : int or str, optional
           Set if the quality values should be associated with the
           background associated with the data set.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        fit : Fit one or more data sets.
        get_quality : Return the quality array for a PHA data set.
        ignore_bad : Exclude channels marked as bad in a PHA data set.
        load_quality : Load the quality array from a file and add to a PHA data set.
        set_grouping : Apply a set of grouping flags to a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `val` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `val` parameters,
        respectively.

        The meaning of the quality column is taken from [1]_, which says
        that 0 indicates a "good" channel, 1 and 2 are for channels that
        are identified as "bad" or "dubious" (respectively) by software,
        5 indicates a "bad" channel set by the user, and values of 3 or 4
        are not used.

        References
        ----------

        .. [1] "The OGIP Spectral File Format", https://heasarc.gsfc.nasa.gov/docs/heasarc/ofwg/docs/spectra/ogip_92_007/ogip_92_007.html

        Examples
        --------

        Copy the quality array from data set 2 into the default data
        set, and then ensure that any 'bad' channels are ignored:

        >>> qual = get_data(2).quality
        >>> set_quality(qual)
        >>> ignore_bad()

        Copy the quality array from data set "src1" to the source and
        background data sets of "src2":

        >>> qual = get_data("src1").quality
        >>> set_quality("src2", qual)
        >>> set_quality("src2", qual, bkg_id=1)

        """
        if val is None:
            id, val = val, id

        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)

        if val is None:
            data.quality = None
        else:
            if(type(val) in (numpy.ndarray,) and
               issubclass(val.dtype.type, numpy.integer)):
                data.quality = numpy.asarray(val)
            else:
                data.quality = numpy.asarray(val, SherpaInt)

    # DOC TODO: Need to document that routines like get_quality return
    # a reference to the data - so can change the data structure
    # - and not a copy

    # DOC-TODO: explain that many of these can be done with
    # direct object access
    # get_data().exposure [= ...]

    def get_quality(self, id=None, bkg_id=None):
        """Return the quality flags for a PHA data set.

        The function returns the quality value for each channel in
        the PHA data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        bkg_id : int or str, optional
           Set if the quality flags should be taken from a background
           associated with the data set.

        Returns
        -------
        qual : ndarray or ``None``
           The quality value for each channel in the PHA data set.
           This array is not grouped or filtered - that is, there
           is one element for each channel in the PHA data set. Changes
           to the elements of this array will change the values in the
           dataset (is is a reference to the values used to define the
           quality, not a copy).

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        fit : Fit one or more data sets.
        get_grouping : Return the grouping array for a PHA data set.
        get_indep : Return the independent axes of a data set.
        ignore_bad : Exclude channels marked as bad in a PHA data set.
        load_quality : Load the quality array from a file and add to a PHA data set.
        set_quality : Apply a set of quality flags to a PHA data set.

        Notes
        -----
        The meaning of the quality column is taken from [1]_, which says
        that 0 indicates a "good" channel, 1 and 2 are for channels that
        are identified as "bad" or "dubious" (respectively) by software,
        5 indicates a "bad" channel set by the user, and values of 3 or 4
        are not used.

        References
        ----------

        .. [1] "The OGIP Spectral File Format", https://heasarc.gsfc.nasa.gov/docs/heasarc/ofwg/docs/spectra/ogip_92_007/ogip_92_007.html

        Examples
        --------

        Copy the quality array from the default data set to data set 2:

        >>> qual1 = get_quality()
        >>> set_quality(2, qual1)

        Return the quality array of the background component labelled
        2 for the 'histate' data set:

        >>> qual = get_quality('histate', bkg_id=2)

        Change the quality setting for all channels below 30 in the
        default data set to 5 (considered bad by the user):

        >>> chans, = get_indep()
        >>> qual = get_quality()
        >>> qual[chans < 30] = 5

        """

        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)

        return data.quality

    def ungroup(self, id=None, bkg_id=None):
        """Turn off the grouping for a PHA data set.

        A PHA data set can be grouped either because it contains
        grouping information [1]_, which is automatically applied when
        the data is read in with `load_pha` or `load_data`, or because
        the ``group_xxx`` set of routines has been used to dynamically
        re-group the data. The `ungroup` function removes this
        grouping (however it was created).

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        bkg_id : int or str, optional
           Set to ungroup the background associated with the data set.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        fit : Fit one or more data sets.
        group : Turn on the grouping for a PHA data set.

        Notes
        -----
        PHA data is often grouped to improve the signal to noise of
        the data, by decreasing the number of bins, so that a
        chi-square statistic can be used when fitting the data.  After
        calling `ungroup`, anything that uses the data set - such as a
        plot, fit, or error analysis - will use the original data
        values. Models should be re-fit if `ungroup` is called; this
        may require a change of statistic depending on the counts per
        channel in the spectrum.

        The grouping is implemented by separate arrays to the main
        data - the information is stored in the ``grouping`` and
        ``quality`` arrays of the PHA data set - so that a data set
        can be grouped and ungrouped many times, without losing
        information.

        The ``grouped`` field of a PHA data set is set to ``False`` when
        the data is not grouped.

        If subtracting the background estimate from a data set, the
        grouping applied to the source data set is used for both
        source and background data sets.

        References
        ----------

        .. [1] Arnaud., K. & George, I., "The OGIP Spectral File
               Format",
               http://heasarc.gsfc.nasa.gov/docs/heasarc/ofwg/docs/spectra/ogip_92_007/ogip_92_007.html

        Examples
        --------

        Ungroup the data in the default data set:

        >>> ungroup()
        >>> get_data().grouped
        False

        Ungroup the first background component of the 'core' data set:

        >>> ungroup('core', bkg_id=1)
        >>> get_bkg('core', bkg_id=1).grouped
        False

        """
        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)

        if bkg_id is None:
            # First, ungroup backgrounds associated with the
            # data set ID; report if background(s) already ungrouped.
            for bid in data.background_ids:
                try:
                    self.ungroup(id, bid)
                except DataErr as e:
                    info(str(e))

            # Now check if data is already ungrouped, and send error message
            # if so
        if data.grouped:
            data.ungroup()

    # DOC-TODO: need to document somewhere that this ignores existing
    # quality flags and how to use tabStops to include
    # this information
    # DOC-TODO: how to set the quality if using tabstops to indicate
    # "bad" channels, rather than ones to ignore

    def group_bins(self, id, num=None, bkg_id=None, tabStops=None):
        """Group into a fixed number of bins.

        Combine the data so that there `num` equal-width bins (or
        groups). The binning scheme is applied to all the channels,
        but any existing filter - created by the `ignore` or `notice`
        set of functions - is re-applied after the data has been
        grouped.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        num : int
           The number of bins in the grouped data set. Each bin
           will contain the same number of channels.
        bkg_id : int or str, optional
           Set to group the background associated with the data set.
           When ``bkg_id`` is None (which is the default), the
           grouping is applied to all the associated background
           data sets as well as the source data set.
        tabStops : array of int or bool, optional
           If set, indicate one or more ranges of channels that should
           not be included in the grouped output. The array should
           match the number of channels in the data set and non-zero or
           ``True`` means that the channel should be ignored from the
           grouping (use 0 or ``False`` otherwise).

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        group_adapt : Adaptively group to a minimum number of counts.
        group_adapt_snr : Adaptively group to a minimum signal-to-noise ratio.
        group_counts : Group into a minimum number of counts per bin.
        group_snr : Group into a minimum signal-to-noise ratio.
        group_width : Group into a fixed bin width.
        set_grouping : Apply a set of grouping flags to a PHA data set.
        set_quality : Apply a set of quality flags to a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `num` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `num` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Unlike `group`, it is possible to call `group_bins` multiple
        times on the same data set without needing to call `ungroup`.

        Since the bin width is an integer number of channels, it is
        likely that some channels will be "left over". This is even
        more likely when the ``tabStops`` parameter is set. If this
        happens, a warning message will be displayed to the screen and
        the quality value for these channels will be set to 2. This
        information can be found with the `get_quality` command.

        Examples
        --------

        Group the default data set so that there are 50 bins.

        >>> group_bins(50)

        Group the 'jet' data set to 50 bins and plot the result,
        then re-bin to 100 bins and overplot the data:

        >>> group_bins('jet', 50)
        >>> plot_data('jet')
        >>> group_bins('jet', 100)
        >>> plot_data('jet', overplot=True)

        The grouping is applied to the full data set, and then
        the filter - in this case defined over the range 0.5
        to 8 keV - will be applied. This means that the
        noticed data range will likely contain less than
        50 bins.

        >>> set_analysis('energy')
        >>> notice(0.5, 8)
        >>> group_bins(50)
        >>> plot_data()

        Do not group any channels numbered less than 20 or
        800 or more. Since there are 780 channels to be
        grouped, the width of each bin will be 20 channels
        and there are no "left over" channels:

        >>> notice()
        >>> channels = get_data().channel
        >>> ign = (channels <= 20) | (channels >= 800)
        >>> group_bins(39, tabStops=ign)
        >>> plot_data()

        """
        if num is None:
            id, num = num, id

        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
        data.group_bins(num, tabStops)

    # DOC-TODO: should num= be renamed val= to better match
    # underlying code/differ from group_bins?
    def group_width(self, id, num=None, bkg_id=None, tabStops=None):
        """Group into a fixed bin width.

        Combine the data so that each bin contains `num` channels.
        The binning scheme is applied to all the channels, but any
        existing filter - created by the `ignore` or `notice` set of
        functions - is re-applied after the data has been grouped.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        num : int
           The number of channels to combine into a group.
        bkg_id : int or str, optional
           Set to group the background associated with the data set.
           When ``bkg_id`` is None (which is the default), the
           grouping is applied to all the associated background
           data sets as well as the source data set.
        tabStops : array of int or bool, optional
           If set, indicate one or more ranges of channels that should
           not be included in the grouped output. The array should
           match the number of channels in the data set and non-zero or
           ``True`` means that the channel should be ignored from the
           grouping (use 0 or ``False`` otherwise).

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        group_adapt : Adaptively group to a minimum number of counts.
        group_adapt_snr : Adaptively group to a minimum signal-to-noise ratio.
        group_bins : Group into a fixed number of bins.
        group_counts : Group into a minimum number of counts per bin.
        group_snr : Group into a minimum signal-to-noise ratio.
        set_grouping : Apply a set of grouping flags to a PHA data set.
        set_quality : Apply a set of quality flags to a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `num` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `num` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Unlike `group`, it is possible to call `group_width` multiple
        times on the same data set without needing to call `ungroup`.

        Unless the requested bin width is a factor of the number of
        channels (and no ``tabStops`` parameter is given), then some
        channels will be "left over". If this happens, a warning
        message will be displayed to the screen and the quality value
        for these channels will be set to 2. This information can be
        found with the `get_quality` command.

        Examples
        --------

        Group the default data set so that each bin contains 20
        channels:

        >>> group_width(20)

        Plot two versions of the 'jet' data set: the first uses
        20 channels per group and the second is 50 channels per
        group:

        >>> group_width('jet', 20)
        >>> plot_data('jet')
        >>> group_width('jet', 50)
        >>> plot_data('jet', overplot=True)

        The grouping is applied to the full data set, and then
        the filter - in this case defined over the range 0.5
        to 8 keV - will be applied.

        >>> set_analysis('energy')
        >>> notice(0.5, 8)
        >>> group_width(50)
        >>> plot_data()

        The grouping is not applied to channels 101 to
        149, inclusive:

        >>> notice()
        >>> channels = get_data().channel
        >>> ign = (channels > 100) & (channels < 150)
        >>> group_width(40, tabStops=ign)
        >>> plot_data()

        """
        if num is None:
            id, num = num, id

        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
        data.group_width(num, tabStops)

    def group_counts(self, id, num=None, bkg_id=None,
                     maxLength=None, tabStops=None):
        """Group into a minimum number of counts per bin.

        Combine the data so that each bin contains `num` or more
        counts. The binning scheme is applied to all the channels, but
        any existing filter - created by the `ignore` or `notice` set
        of functions - is re-applied after the data has been grouped.
        The background is *not* included in this calculation; the
        calculation is done on the raw data even if `subtract` has
        been called on this data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        num : int
           The number of channels to combine into a group.
        bkg_id : int or str, optional
           Set to group the background associated with the data set.
           When ``bkg_id`` is None (which is the default), the
           grouping is applied to all the associated background
           data sets as well as the source data set.
        maxLength : int, optional
           The maximum number of channels that can be combined into a
           single group.
        tabStops : array of int or bool, optional
           If set, indicate one or more ranges of channels that should
           not be included in the grouped output. The array should
           match the number of channels in the data set and non-zero or
           ``True`` means that the channel should be ignored from the
           grouping (use 0 or ``False`` otherwise).

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        group_adapt : Adaptively group to a minimum number of counts.
        group_adapt_snr : Adaptively group to a minimum signal-to-noise ratio.
        group_bins : Group into a fixed number of bins.
        group_snr : Group into a minimum signal-to-noise ratio.
        group_width : Group into a fixed bin width.
        set_grouping : Apply a set of grouping flags to a PHA data set.
        set_quality : Apply a set of quality flags to a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `num` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `num` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Unlike `group`, it is possible to call `group_counts` multiple
        times on the same data set without needing to call `ungroup`.

        If channels can not be placed into a "valid" group, then a
        warning message will be displayed to the screen and the
        quality value for these channels will be set to 2. This
        information can be found with the `get_quality` command.

        Examples
        --------

        Group the default data set so that each bin contains at
        least 20 counts:

        >>> group_counts(20)

        Plot two versions of the 'jet' data set: the first uses
        20 counts per group and the second is 50:

        >>> group_counts('jet', 20)
        >>> plot_data('jet')
        >>> group_counts('jet', 50)
        >>> plot_data('jet', overplot=True)

        The grouping is applied to the full data set, and then
        the filter - in this case defined over the range 0.5
        to 8 keV - will be applied.

        >>> set_analysis('energy')
        >>> notice(0.5, 8)
        >>> group_counts(30)
        >>> plot_data()

        If a channel has more than 30 counts then do not group,
        otherwise group channels so that they contain at least 40
        counts. The `group_adapt` and `group_adapt_snr` functions
        provide similar functionality to this example.  A maximum
        length of 10 channels is enforced, to avoid bins getting too
        large when the signal is low.

        >>> notice()
        >>> counts = get_data().counts
        >>> ign = counts > 30
        >>> group_counts(40, tabStops=ign, maxLength=10)

        """
        if num is None:
            id, num = num, id

        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
        data.group_counts(num, maxLength, tabStops)

    # DOC-TODO: check the Poisson stats claim; I'm guessing it means
    #           gaussian (i.e. sqrt(n))
    def group_snr(self, id, snr=None, bkg_id=None,
                  maxLength=None, tabStops=None, errorCol=None):
        """Group into a minimum signal-to-noise ratio.

        Combine the data so that each bin has a signal-to-noise ratio
        of at least `snr`. The binning scheme is applied to all the
        channels, but any existing filter - created by the `ignore` or
        `notice` set of functions - is re-applied after the data has
        been grouped.  The background is *not* included in this
        calculation; the calculation is done on the raw data even if
        `subtract` has been called on this data set.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        snr : number
           The minimum signal-to-noise ratio that must be reached
           to form a group of channels.
        bkg_id : int or str, optional
           Set to group the background associated with the data set.
           When ``bkg_id`` is None (which is the default), the
           grouping is applied to all the associated background
           data sets as well as the source data set.
        maxLength : int, optional
           The maximum number of channels that can be combined into a
           single group.
        tabStops : array of int or bool, optional
           If set, indicate one or more ranges of channels that should
           not be included in the grouped output. The array should
           match the number of channels in the data set and non-zero or
           ``True`` means that the channel should be ignored from the
           grouping (use 0 or ``False`` otherwise).
        errorCol : array of num, optional
           If set, the error to use for each channel when calculating
           the signal-to-noise ratio. If not given then Poisson
           statistics is assumed. A warning is displayed for each
           zero-valued error estimate.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        group_adapt : Adaptively group to a minimum number of counts.
        group_adapt_snr : Adaptively group to a minimum signal-to-noise ratio.
        group_bins : Group into a fixed number of bins.
        group_counts : Group into a minimum number of counts per bin.
        group_width : Group into a fixed bin width.
        set_grouping : Apply a set of grouping flags to a PHA data set.
        set_quality : Apply a set of quality flags to a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `snr` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `snr` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Unlike `group`, it is possible to call `group_snr` multiple
        times on the same data set without needing to call `ungroup`.

        If channels can not be placed into a "valid" group, then a
        warning message will be displayed to the screen and the
        quality value for these channels will be set to 2. This
        information can be found with the `get_quality` command.

        Examples
        --------

        Group the default data set so that each bin has a
        signal-to-noise ratio of at least 5:

        >>> group_snr(20)

        Plot two versions of the 'jet' data set: the first uses
        a signal-to-noise ratio of 3 and the second 5:

        >>> group_snr('jet', 3)
        >>> plot_data('jet')
        >>> group_snr('jet', 5)
        >>> plot_data('jet', overplot=True)

        """
        if snr is None:
            id, snr = snr, id
        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
        data.group_snr(snr, maxLength, tabStops, errorCol)

    def group_adapt(self, id, min=None, bkg_id=None,
                    maxLength=None, tabStops=None):
        """Adaptively group to a minimum number of counts.

        Combine the data so that each bin contains `min` or more
        counts. The difference to `group_counts` is that this
        algorithm starts with the bins with the largest signal, in
        order to avoid over-grouping bright features, rather than at
        the first channel of the data. The adaptive nature means that
        low-count regions between bright features may not end up in
        groups with the minimum number of counts.  The binning scheme
        is applied to all the channels, but any existing filter -
        created by the `ignore` or `notice` set of functions - is
        re-applied after the data has been grouped.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        min : int
           The number of channels to combine into a group.
        bkg_id : int or str, optional
           Set to group the background associated with the data set.
           When ``bkg_id`` is ``None`` (which is the default), the
           grouping is applied to all the associated background
           data sets as well as the source data set.
        maxLength : int, optional
           The maximum number of channels that can be combined into a
           single group.
        tabStops : array of int or bool, optional
           If set, indicate one or more ranges of channels that should
           not be included in the grouped output. The array should
           match the number of channels in the data set and non-zero or
           ``True`` means that the channel should be ignored from the
           grouping (use 0 or ``False`` otherwise).

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        group_adapt_snr : Adaptively group to a minimum signal-to-noise ratio.
        group_bins : Group into a fixed number of bins.
        group_counts : Group into a minimum number of counts per bin.
        group_snr : Group into a minimum signal-to-noise ratio.
        group_width : Group into a fixed bin width.
        set_grouping : Apply a set of grouping flags to a PHA data set.
        set_quality : Apply a set of quality flags to a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `min` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `min` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Unlike `group`, it is possible to call `group_adapt` multiple
        times on the same data set without needing to call `ungroup`.

        If channels can not be placed into a "valid" group, then a
        warning message will be displayed to the screen and the
        quality value for these channels will be set to 2. This
        information can be found with the `get_quality` command.

        Examples
        --------

        Group the default data set so that each bin contains at
        least 20 counts:

        >>> group_adapt(20)

        Plot two versions of the 'jet' data set: the first uses
        an adaptive scheme of 20 counts per bin, the second
        the `group_counts` method:

        >>> group_adapt('jet', 20)
        >>> plot_data('jet')
        >>> group_counts('jet', 20)
        >>> plot_data('jet', overplot=True)

        """
        if min is None:
            id, min = min, id
        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
        data.group_adapt(min, maxLength, tabStops)

    # DOC-TODO: shouldn't this be snr=None rather than min=None
    def group_adapt_snr(self, id, min=None, bkg_id=None,
                        maxLength=None, tabStops=None, errorCol=None):
        """Adaptively group to a minimum signal-to-noise ratio.

        Combine the data so that each bin has a signal-to-noise ratio
        of at least `num`. The difference to `group_snr` is that this
        algorithm starts with the bins with the largest signal, in
        order to avoid over-grouping bright features, rather than at
        the first channel of the data. The adaptive nature means that
        low-count regions between bright features may not end up in
        groups with the minimum number of counts.  The binning scheme
        is applied to all the channels, but any existing filter -
        created by the `ignore` or `notice` set of functions - is
        re-applied after the data has been grouped.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.
        num : number
           The minimum signal-to-noise ratio that must be reached
           to form a group of channels.
        bkg_id : int or str, optional
           Set to group the background associated with the data set.
           When ``bkg_id`` is ``None`` (which is the default), the
           grouping is applied to all the associated background
           data sets as well as the source data set.
        maxLength : int, optional
           The maximum number of channels that can be combined into a
           single group.
        tabStops : array of int or bool, optional
           If set, indicate one or more ranges of channels that should
           not be included in the grouped output. The array should
           match the number of channels in the data set and non-zero or
           ``True`` means that the channel should be ignored from the
           grouping (use 0 or ``False`` otherwise).
        errorCol : array of num, optional
           If set, the error to use for each channel when calculating
           the signal-to-noise ratio. If not given then Poisson
           statistics is assumed. A warning is displayed for each
           zero-valued error estimate.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        group_adapt : Adaptively group to a minimum number of counts.
        group_bins : Group into a fixed number of bins.
        group_counts : Group into a minimum number of counts per bin.
        group_snr : Group into a minimum signal-to-noise ratio.
        group_width : Group into a fixed bin width.
        set_grouping : Apply a set of grouping flags to a PHA data set.
        set_quality : Apply a set of quality flags to a PHA data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `num` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `num` parameters,
        respectively. The remaining parameters are expected to be
        given as named arguments.

        Unlike `group`, it is possible to call `group_adapt_snr`
        multiple times on the same data set without needing to call
        `ungroup`.

        If channels can not be placed into a "valid" group, then a
        warning message will be displayed to the screen and the
        quality value for these channels will be set to 2. This
        information can be found with the `get_quality` command.

        Examples
        --------

        Group the default data set so that each bin contains
        a signal-to-noise ratio of at least 5:

        >>> group_adapt_snr(5)

        Plot two versions of the 'jet' data set: the first uses an
        adaptive scheme and the second the non-adaptive version:

        >>> group_adapt_snr('jet', 4)
        >>> plot_data('jet')
        >>> group_snr('jet', 4)
        >>> plot_data('jet', overplot=True)

        """
        if min is None:
            id, min = min, id
        data = self._get_pha_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
        data.group_adapt_snr(min, maxLength, tabStops, errorCol)

    def subtract(self, id=None):
        """Subtract the background estimate from a data set.

        The ``subtract`` function performs a channel-by-channel
        subtraction of the background estimate from the data. After
        this command, anything that uses the data set - such as a
        plot, fit, or error analysis - will use the subtracted
        data. Models should be re-fit if ``subtract`` is called.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        fit : Fit one or more data sets.
        unsubtract : Undo any background subtraction for the data set.

        Notes
        -----
        Unlike X-Spec [1]_, Sherpa does not automatically subtract
        the background estimate from the data.

        Background subtraction can only be performed when data and
        background are of the same length.  If the data and background
        are ungrouped, both must have same number of channels.  If
        they are grouped, data and background can start with different
        numbers of channels, but must have the same number of groups
        after grouping.

        The equation for the subtraction is::

           src_counts - bg_counts * (src_exposure * src_backscal)
                                    -----------------------------
                                     (bg_exposure * bg_backscal)

        where src_exposure and bg_exposure are the source and
        background exposure times, and src_backscal and bg_backscal
        are the source and background backscales.  The backscale, read
        from the ``BACKSCAL`` header keyword of the PHA file [2]_, is
        the ratio of data extraction area to total detector area.

        The ``subtracted`` field of a dataset is set to ``True`` when
        the background is subtracted.

        References
        ----------

        .. [1] https://heasarc.gsfc.nasa.gov/xanadu/xspec/manual/XspecSpectralFitting.html

        .. [2] https://heasarc.gsfc.nasa.gov/docs/heasarc/ofwg/docs/spectra/ogip_92_007/node5.html

        Examples
        --------

        Background subtract the default data set.

        >>> subtract()
        >>> get_data().subtracted
        True

        Remove the background from the data set labelled 'src':

        >>> subtract('src')
        >>> get_data('src').subtracted
        True

        Overplot the background-subtracted data on the original
        data for the default data set:

        >>> plot_data()
        >>> subtract()
        >>> plot_data(overplot=True)

        """
        if not self._get_pha_data(id).subtracted:
            self._get_pha_data(id).subtract()

    def unsubtract(self, id=None):
        """Undo any background subtraction for the data set.

        The `unsubtract` function undoes any changes made by
        `subtract`. After this command, anything that uses the data
        set - such as a plot, fit, or error analysis - will use the
        original data values. Models should be re-fit if `subtract` is
        called.

        Parameters
        ----------
        id : int or str, optional
           The identifier for the data set to use. If not given then
           the default identifier is used, as returned by
           `get_default_id`.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain a PHA data set.

        See Also
        --------
        fit : Fit one or more data sets.
        subtract : Subtract the background estimate from a data set.

        Notes
        -----
        The ``subtracted`` field of a PHA data set is set to ``False``
        when the background is not subtracted.

        Examples
        --------

        Remove the background subtraction from the default data set.

        >>> subtract()
        >>> get_data().subtracted
        False

        Remove the background subtraction from the data set labelled
        'src':

        >>> subtract('src')
        >>> get_data('src').subtracted
        False

        """
        if self._get_pha_data(id).subtracted:
            self._get_pha_data(id).unsubtract()

    def fake_pha(self, id, arf, rmf, exposure, backscal=None, areascal=None,
                 grouping=None, grouped=False, quality=None, bkg=None):
        """Simulate a PHA data set from a model.

        The function creates a simulated PHA data set based on a source
        model, instrument response (given as an ARF and RMF), and exposure
        time, along with a Poisson noise term. A background component can
        be included.

        Parameters
        ----------
        id : int or str
           The identifier for the data set to create. If it already
           exists then it is assumed to contain a PHA data set and the
           counts will be over-written.
        arf : filename or ARF object or list of filenames
           The name of the ARF, or an ARF data object (e.g.  as
           returned by `get_arf` or `unpack_arf`). A list of filenames
           can be passed in for instruments that require multile ARFs.
           Set this to `None` to use any arf that is already set for
           the data set given by id.
        rmf : filename or RMF object or list of filenames
           The name of the RMF, or an RMF data object (e.g.  as
           returned by `get_arf` or `unpack_arf`).  A list of filenames
           can be passed in for instruments that require multile RMFs.
           Set this to `None` to use any arf that is already set for
           the data set given by id.
        exposure : number
           The exposure time, in seconds.
        backscal : number, optional
           The 'BACKSCAL' value for the data set.
        areascal : number, optional
           The 'AREASCAL' value for the data set.
        grouping : array, optional
           The grouping array for the data (see `set_grouping`).
        grouped : bool, optional
           Should the simulated data be grouped (see `group`)?  The
           default is ``False``. This value is only used if the
           `grouping` parameter is set.
        quality : array, optional
           The quality array for the data (see `set_quality`).
        bkg : optional
           If left empty, then only the source emission is simulated.
           If set to a PHA data object, then the counts from this data
           set are scaled appropriately and added to the simulated
           source signal. To use background model, set ``bkg="model"`. In that
           case a background dataset with ``bkg_id=1`` has to be set before
           calling ``fake_pha``. That background dataset needs to include
           the data itself (not used in this function), the background model,
           and the response.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set already exists and does not contain PHA
           data.

        See Also
        --------
        fake : Simulate a data set.
        get_arf : Return the ARF associated with a PHA data set.
        get_rmf : Return the RMF associated with a PHA data set.
        get_dep : Return the dependent axis of a data set.
        load_arrays : Create a data set from array values.
        set_model : Set the source model expression for a data set.

        Notes
        -----
        A model expression is created by using the supplied ARF and RMF
        to convolve the source expression for the dataset (the return
        value of `get_source` for the supplied `id` parameter). This
        expresion is evaluated for each channel to create the expectation
        values, which is then passed to a Poisson random number generator
        to determine the observed number of counts per channel. Any
        background component is scaled by appropriate terms (exposure
        time, area scaling, and the backscal value) before it is passed to
        a Poisson random number generator. The simulated background is
        added to the simulated data.

        Examples
        --------
        Estimate the signal from a 5000 second observation using the
        ARF and RMF from "src.arf" and "src.rmf" respectively:

        >>> set_source(1, xsphabs.gal * xsapec.clus)
        >>> gal.nh = 0.12
        >>> clus.kt, clus.abundanc = 4.5, 0.3
        >>> clus.redshift = 0.187
        >>> clus.norm = 1.2e-3
        >>> fake_pha(1, 'src.arf', 'src.rmf', 5000)

        Simulate a 1 mega second observation for the data and model
        from the default data set. The simulated data will include an
        estimated background component based on scaling the existing
        background observations for the source. The simulated data
        set, which has the same grouping as the default set, for
        easier comparison, is created with the 'sim' label and then
        written out to the file 'sim.pi':

        >>> arf = get_arf()
        >>> rmf = get_rmf()
        >>> bkg = get_bkg()
        >>> bscal = get_backscal()
        >>> grp = get_grouping()
        >>> qual = get_quality()
        >>> texp = 1e6
        >>> set_source('sim', get_source())
        >>> fake_pha('sim', arf, rmf, texp, backscal=bscal, bkg=bkg,
        ...          grouping=grp, quality=qual, grouped=True)
        >>> save_pha('sim', 'sim.pi')

        Sometimes, the background dataset is noisy because there are not
        enough photons in the background region. In this case, the background
        model can be used to generate the photons that the background
        contributes to the source spectrum. To do this, a background model
        must be passed in. This model is then convolved with the ARF and RMF
        (which must be set before) of the default background data set:

        >>> set_bkg_source('sim', 'const1d.con1')
        >>> load_arf('sim', 'bkg.arf.fits', bkg_id=1)
        >>> load_rmf('sim', 'bkg_rmf.fits', bkg_id=1)
        >>> fake_pha('sim', arf, rmf, texp, backscal=bscal, bkg='model',
        ...          grouping=grp, quality=qual, grouped=True)
        >>> save_pha('sim', 'sim.pi')
        """
        id = self._fix_id(id)

        if id in self._data:
            d = self._get_pha_data(id)
        else:
            d = sherpa.astro.data.DataPHA('', None, None)
            self.set_data(id, d)

        if rmf is None and len(d.response_ids) == 0:
            raise DataErr('normffake', id)

        if type(rmf) in (str, numpy.string_):
            if os.path.isfile(rmf):
                rmf = self.unpack_rmf(rmf)
            else:
                raise IOErr("filenotfound", rmf)

        if type(arf) in (str, numpy.string_):
            if os.path.isfile(arf):
                arf = self.unpack_arf(arf)
            else:
                raise IOErr("filenotfound", arf)

        if not (rmf is None and arf is None):
            for resp_id in d.response_ids:
                d.delete_response(resp_id)

        # Get one rmf for testing the channel number
        # This would be a lot simpler if I could just raise the
        # incombatiblersp error on the OO layer (that happens, but the id
        # is not in the error messaage).
        if rmf is None:
            rmf0 = d.get_rmf()
        elif numpy.iterable(rmf):
            rmf0 = self.unpack_rmf(rmf[0])
        else:
            rmf0 = rmf

        if d.channel is None:
            d.channel = sao_arange(1, rmf0.detchans)

        else:
            if len(d.channel) != rmf0.detchans:
                raise DataErr('incompatibleresp', rmf.name, str(id))

        # at this point, we can be sure that arf is not a string, because
        # if it was, it would have gone through load_arf already above.
        if not (rmf is None and arf is None):
            if numpy.iterable(arf):
                self.load_multi_arfs(id, arf, range(len(arf)))
            else:
                self.set_arf(id, arf)

            if numpy.iterable(rmf):
                self.load_multi_rmfs(id, rmf, range(len(rmf)))
            else:
                self.set_rmf(id, rmf)

        d.exposure = exposure

        if backscal is not None:
            d.backscal = backscal

        if areascal is not None:
            d.areascal = areascal

        if quality is not None:
            d.quality = quality

        if grouping is not None:
            d.grouping = grouping

        if d.grouping is not None:
            if sherpa.utils.bool_cast(grouped):
                d.group()
            else:
                d.ungroup()

        # Update background here.  bkg contains a new background;
        # delete the old background (if any) and add the new background
        # to the simulated data set, BEFORE simulating data, and BEFORE
        # adding scaled background counts to the simulated data.
        bkg_models = {}
        if bkg is not None:
            if bkg == 'model':
                bkg_models = {1: self.get_bkg_source(id)}
            else:
                for bkg_id in d.background_ids:
                    d.delete_background(bkg_id)
                self.set_bkg(id, bkg)

        # Calculate the source model, and take a Poisson draw based on
        # the source model.  That becomes the simulated data.
        m = self.get_model(id)

        fake.fake_pha(d, m, is_source=False, add_bkgs=bkg is not None,
                      id=str(id), bkg_models=bkg_models)
        d.name = 'faked'


    ###########################################################################
    # PSF
    ###########################################################################
    def load_psf(self, modelname, filename_or_model, *args, **kwargs):
        kernel = filename_or_model
        if isinstance(filename_or_model, string_types):
            try:
                kernel = self._eval_model_expression(filename_or_model)
            except:
                kernel = self.unpack_data(filename_or_model,
                                          *args, **kwargs)

        psf = sherpa.astro.instrument.PSFModel(modelname, kernel)
        if isinstance(kernel, sherpa.models.Model):
            self.freeze(kernel)
        self._add_model_component(psf)
        self._psf_models.append(psf)

    load_psf.__doc__ = sherpa.ui.utils.Session.load_psf.__doc__

    ###########################################################################
    # Models
    ###########################################################################

    # DOC-NOTE: also in sherpa.utils
    def set_full_model(self, id, model=None):
        """Define the convolved model expression for a data set.

        The model expression created by `set_model` can be modified by
        "instrumental effects", such as PSF, ARF and RMF for PHA data
        sets, or a pile up model. These can be set automatically - for
        example, the ARF and RMF can be set up when the source data is
        loaded - or explicitly with calls to routines like `set_psf`,
        `set_arf`, `set_rmf`, and `set_pileup_model`. The
        `set_full_model` function is for when this is not sufficient,
        and full control is needed. Examples of when this would be
        needed include: if different PSF models should be applied to
        different source components; some source components need to
        include the ARF and RMF but some do not.

        Parameters
        ----------
        id : int or str, optional
           The data set containing the source expression. If not given
           then the default identifier is used, as returned by
           `get_default_id`.
        model : str or sherpa.models.Model object
           This defines the model used to fit the data. It can be a
           Python expression or a string version of it.

        See Also
        --------
        fit : Fit one or more data sets.
        set_bkg_full_model : Define the convolved background model expression for a PHA data set.
        set_pileup_model : Include a model of the Chandra ACIS pile up when fitting PHA data.
        set_psf : Add a PSF model to a data set.
        set_model : Set the source model expression for a data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `model` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `model` parameters,
        respectively.

        Some functions - such as `plot_source` and `calc_energy_flux`
        - may not work for model expressions created by
        `set_full_model`.

        Examples
        --------

        Extract the response - the combined RMF and ARF - for a PHA
        data set - and apply it to a model (`xsphabs` * `xsapec`) and
        then include a `powlaw1d` component that only includes the
        RMF and a gaussian that has no instrumental response:

        >>> rsp = get_response()
        >>> rmf = get_rmf()
        >>> smodel = xsphabs.galabs * xsapec.emiss
        >>> bmodel = powlaw1d.pbgnd
        >>> set_full_model(rsp(smodel) + rmf(bmodel) + gauss1d.iline)

        Apply different PSFs to different components, as well as an
        unconvolved component:

        >>> load_psf("psf1", "psf1.fits")
        >>> load_psf("psf2", "psf2.fits")
        >>> smodel = psf1(gauss2d.src1) + psf2(beta2d.src2) + const2d.bgnd
        >>> set_full_model("src", smodel)

        """
        sherpa.ui.utils.Session.set_full_model(self, id, model)

        if model is None:
            id, model = model, id

        data = self.get_data(id)
        if isinstance(data, sherpa.astro.data.DataPHA):
            model = self.get_model(id)

            if data._responses:

                instruments = (sherpa.astro.instrument.RSPModel,
                               sherpa.astro.instrument.RMFModel,
                               sherpa.astro.instrument.ARFModel,
                               sherpa.astro.instrument.MultiResponseSumModel,
                               sherpa.astro.instrument.PileupRMFModel)

                do_warning = True
                # if type(model) in instruments:
                # if isinstance(model, instruments):
                if sherpa.ui.utils._is_subclass(type(model), instruments):
                    do_warning = False
                for part in model:
                    # if type(part) in instruments:
                    # if isinstance(part, instruments):
                    if sherpa.ui.utils._is_subclass(type(part), instruments):
                        do_warning = False
                if do_warning:
                    warning("PHA source model '%s' \ndoes not" %
                            model.name +
                            " have an associated instrument model; " +
                            "consider using \nset_source() instead of" +
                            " set_full_model() to include associated " +
                            "\ninstrument automatically")

    set_full_model.__doc__ = sherpa.ui.utils.Session.set_full_model.__doc__

    def _add_convolution_models(self, id, data, model, is_source):
        """Add in "hidden" components to the model expression.

        This includes PSF and pileup models and, for PHA data sets,
        it adds in any background terms and the response function.

        Notes
        -----
        If a background is added to a PHA data set using a vector,
        rather than scalar, value, the code has to convert from
        the model evaluation grid (e.g. keV or Angstroms) to the
        scale array, which will be in channels. The only way to do
        this is to apply the instrument response to the background
        model separately from the source model, which will fail if
        the instrument model is not linear, such as the jdpileup
        model.
        """

        id = self._fix_id(id)

        # Add any convolution components from the sherpa.ui layer
        model = super()._add_convolution_models(id, data, model, is_source)

        # If we don't need to deal with DataPHA issues we can return
        if not isinstance(data, sherpa.astro.data.DataPHA) or not is_source:
            return model

        return sherpa.astro.background.add_response(self, id, data, model)

    def _get_response(self, id, pha):
        """Calculate the response for the dataset.

        Parameter
        ---------
        id : int or str
            The identifier (this is required to be valid).
        pha : sherpa.astro.data.DataPHA
            The dataset

        Returns
        -------
        response
           The return value depends on whether an ARF, RMF, or pile up
           model has been associated with the data set.

        """
        pileup_model = self._pileup_models.get(id)
        return pha.get_full_response(pileup_model)

    def get_response(self, id=None, bkg_id=None):
        """Return the response information applied to a PHA data set.

        For a PHA data set, the source model - created by `set_model`
        - is modified by a model representing the instrumental effects
        - such as the effective area of the mirror, the energy
        resolution of the detector, and any model of pile up - which
        is collectively known as the instrument response. The
        `get_response` function returns the instrument response model.

        Parameters
        ----------
        id : int or str, optional
           The data set containing the instrument response. If not given
           then the default identifier is used, as returned by
           `get_default_id`.
        bkg_id : int or str, optional
           If given, return the response for the given background
           component, rather than the source.

        Returns
        -------
        response
           The return value depends on whether an ARF, RMF, or pile up
           model has been associated with the data set.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.

        See Also
        --------
        get_arf : Return the ARF associated with a PHA data set.
        get_pileup_model : Return the pile up model for a data set.
        get_rmf : Return the RMF associated with a PHA data set.
        set_bkg_full_model : Define the convolved background model expression for a PHA data set.
        set_full_model : Define the convolved model expression for a data set.

        Examples
        --------

        Create an empty PHA data set, load in an ARF and RMF, and then
        retrieve the response. The response is then used to model the
        instrument response applied to a `powlaw1d` model component,
        along with a constant component (`bgnd`) that does not
        "pass through" the instrument response:

        >>> dataspace1d(1, 1024, 1, dstype=DataPHA)
        >>> load_arf('src.arf')
        >>> load_rmf('src.rmf')
        >>> rsp = get_response()
        >>> set_full_model(rsp(powlaw1d.pl) + const1d.bgnd)

        """
        id = self._fix_id(id)
        if bkg_id is not None:
            pha = self.get_bkg(id, bkg_id)
        else:
            pha = self._get_pha_data(id)

        return self._get_response(id, pha)

    def get_pileup_model(self, id=None):
        """Return the pile up model for a data set.

        Return the pile up model set by a call to `set_pileup_model`.

        Parameters
        ----------
        id : int or str, optional
           The data set containing the source expression. If not given
           then the default identifier is used, as returned by
           `get_default_id`.

        Returns
        -------
        model : a `sherpa.astro.models.JDPileup` instance

        Raises
        ------
        sherpa.utils.err.IdentifierErr
           If no pile up model has been set for the data set.

        See Also
        --------
        delete_pileup_model : Delete the pile up model for a data set.
        fit : Fit one or more data sets.
        get_model : Return the model expression for a data set.
        get_source : Return the source model expression for a data set.
        sherpa.astro.models.JDPileup : The ACIS pile up model.
        list_pileup_model_ids : List of all the data sets with a pile up model.
        set_pileup_model : Include a model of the Chandra ACIS pile up when fitting PHA data.

        Examples
        --------

        >>> jdp1 = get_pileup_model()
        >>> jdp2 = get_pileup_model(2)

        """
        return self._get_item(id, self._pileup_models, 'pileup model',
                              'has not been set')

    def delete_pileup_model(self, id=None):
        """Delete the pile up model for a data set.

        Remove the pile up model applied to a source model.

        .. versionadded:: 4.12.2

        Parameters
        ----------
        id : int or str, optional
           The data set. If not given then the
           default identifier is used, as returned by `get_default_id`.

        See Also
        --------
        get_pileup_model : Return the pile up model for a data set.
        list_pileup_model_ids : List of all the data sets with a pile up model.
        set_pileup_model : Add a pile up model to a data set.

        Examples
        --------

        >>> delete_pileup_model()

        >>> delete_pileup_model('core')

        """
        id = self._fix_id(id)
        self._pileup_models.pop(id, None)

    def list_pileup_model_ids(self):
        """List of all the data sets with a pile up model.

        .. versionadded:: 4.12.2

        Returns
        -------
        ids : list of int or str
           The identifiers for all the data sets which have a pile up
           model set by `set_pileup_model`.

        See Also
        --------
        list_data_ids : List the identifiers for the loaded data sets.
        list_model_ids : List of all the data sets with a source expression.
        set_pileup_model : Add a pile up model to a data set.

        """
        keys = list(self._pileup_models.keys())
        return sorted(keys, key=str)

    # DOC-NOTE: should this be made a general function, since it
    # presumably does not care about pileup, just adds the
    # given model into the expression? Or is it PHA specific?
    def set_pileup_model(self, id, model=None):
        """Include a model of the Chandra ACIS pile up when fitting PHA data.

        Chandra observations of bright sources can be affected by
        pileup, so that there is a non-linear correlation between
        the source model and the predicted counts. This process can
        be modelled by including the `jdpileup` model for a
        data set, using the `set_pileup_model`.

        Parameters
        ----------
        id : int or str, optional
           The data set containing the source expression. If not given
           then the default identifier is used, as returned by
           `get_default_id`.
        model : an instance of the `sherpa.astro.models.JDPileup` class

        See Also
        --------
        delete_pileup_model : Delete the pile up model for a data set.
        fit : Fit one or more data sets.
        get_pileup_model : Return the pile up model for a data set.
        sherpa.models.model.JDPileup : The ACIS pile up model.
        list_pileup_model_ids : List of all the data sets with a pile up model.
        set_full_model : Define the convolved model expression for a data set.
        set_model : Set the source model expression for a data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `model` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `model` parameters,
        respectively.

        This is a generic function, and can be used to model other
        non-linear detector effects, but at present the only available
        model is for the ACIS pile up provided by the jdpileup model.

        Examples
        --------

        Plot up the model (an xsphabs model multiplied by a powlaw1d
        component) and then overplot the same expression but including
        the effects of pile up in the Chandra ACIS instrument:

        >>> load_pha('src.pi')
        >>> set_source(xsphabs.gal * powlaw1d.pl)
        >>> plot_model()
        >>> set_pileup_model(jdpileup.jpd)
        >>> plot_model(overplot=True)

        """
        if model is None:
            id, model = model, id
        if isinstance(model, string_types):
            model = self._eval_model_expression(model)
        self._set_item(id, model, self._pileup_models, sherpa.models.Model,
                       'model', 'a model object or model expression string')

    def get_bkg_source(self, id=None, bkg_id=None):
        """Return the model expression for the background of a PHA data set.

        This returns the model expression created by `set_bkg_model`
        or `set_bkg_source`. It does not include any instrument
        response.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.

        Returns
        -------
        model : a sherpa.models.Model object
           This can contain multiple model components. Changing
           attributes of this model changes the model used by the data
           set.

        See Also
        --------
        delete_bkg_model : Delete the background model expression for a data set.
        get_bkg_model : Return the model expression for the background of a PHA data set.
        list_model_ids : List of all the data sets with a source expression.
        set_bkg_model : Set the background model expression for a PHA data set.
        show_bkg_model : Display the background model expression for a data set.

        Examples
        --------

        Return the background model expression for the default data
        set:

        >>> bkg = get_bkg_source()
        >>> len(bkg.pars)
        2

        """
        id = self._fix_id(id)
        bkg_id = self._fix_background_id(id, bkg_id)

        model = self._background_sources.get(id, {}).get(bkg_id)
        if model is None:
            raise ModelErr('nobkg', bkg_id, id)

        return model

    def get_bkg_model(self, id=None, bkg_id=None):
        """Return the model expression for the background of a PHA data set.

        This returns the model expression for the background of a data
        set, including the instrument response (e.g. ARF and RMF),
        whether created automatically or explicitly, with
        ``set_bkg_full_model``.

        Parameters
        ----------
        id : int or str, optional
           The data set to use. If not given then the default
           identifier is used, as returned by ``get_default_id``.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.

        Returns
        -------
        instance
           This can contain multiple model components and any
           instrument response. Changing attributes of this model
           changes the model used by the data set.

        See Also
        --------
        delete_bkg_model : Delete the background model expression for a data set.
        get_bkg_source : Return the model expression for the background of a PHA data set.
        list_model_ids : List of all the data sets with a source expression.
        set_bkg_model : Set the background model expression for a PHA data set.
        set_bkg_full_model : Define the convolved background model expression for a PHA data set.
        show_bkg_model : Display the background model expression for a data set.

        Examples
        --------

        Return the background model expression for the default data
        set, including any instrument response:

        >>> bkg = get_bkg_model()

        """
        id = self._fix_id(id)
        bkg_id = self._fix_background_id(id, bkg_id)

        mdl = self._background_models.get(id, {}).get(bkg_id)

        if mdl is None:
            is_source = True
            src = self._background_sources.get(id, {}).get(bkg_id)
        else:
            is_source = False
            src = mdl

        if src is None:
            raise ModelErr('nobkg', bkg_id, id)

        if not is_source:
            return src

        # The background response is set by the DataPHA.set_background
        # method (copying one over, if it does not exist), which means
        # that the only way to get to this point is if the user has
        # explicitly deleted the background response. In this case
        # we error out.
        #
        bkg = self.get_bkg(id, bkg_id)
        if len(bkg.response_ids) == 0:
            raise DataErr('nobrsp', str(id), str(bkg_id))

        resp = sherpa.astro.instrument.Response1D(bkg)
        return resp(src)

    def set_bkg_full_model(self, id, model=None, bkg_id=None):
        """Define the convolved background model expression for a PHA data set.

        Set a model expression for a background data set in the same
        way that `set_full_model` does for a source.  This is for when
        the background is being fitted simultaneously to the source,
        rather than subtracted from it.

        Parameters
        ----------
        id : int or str, optional
           The data set containing the source expression. If not given
           then the default identifier is used, as returned by
           `get_default_id`.
        model : str or sherpa.models.Model object
           This defines the model used to fit the data. It can be a
           Python expression or a string version of it.
        bkg_id : int or str, optional
           The identifier for the background of the data set, in
           cases where multiple backgrounds are provided.

        See Also
        --------
        fit : Fit one or more data sets.
        set_full_model : Define the convolved model expression for a data set.
        set_pileup_model : Include a model of the Chandra ACIS pile up when fitting PHA data.
        set_psf : Add a PSF model to a data set.
        set_model : Set the source model expression for a data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `model` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `model` parameters,
        respectively.

        Some functions - such as `plot_bkg_source` - may not work for
        model expressions created by `set_bkg_full_model`.

        Examples
        --------

        The background is fit by two power laws - one that is passed
        through the instrument response (``gbgnd``) and one that is not
        (``pbgnd``). The source is modelled by ``xsphabs * galabs``,
        together with the background model, scaled by the ratio of
        area and time. Note that the background component in the
        source expression uses the source response rather than
        background response.

        >>> rsp = get_response()
        >>> bresp = get_response(bkg_id=1)
        >>> bscale = get_bkg_scale()
        >>> smodel = xsphabs.galabs * xsapec.emiss
        >>> bmdl = brsp(powlaw1d.gbdng) + powlaw1d.pbgnd
        >>> smdl = rsp(smodel) + bscale*(rsp(gbgnd) + pbgnd)
        >>> set_full_model(smdl)
        >>> set_bkg_full_model(bmdl)

        """
        if model is None:
            id, model = model, id

        id = self._fix_id(id)
        bkg_id = self._fix_background_id(id, bkg_id)

        if isinstance(model, string_types):
            model = self._eval_model_expression(model)
        _check_type(model, sherpa.models.Model, 'model',
                    'a model object or model expression string')

        self._background_models.setdefault(id, {})[bkg_id] = model

        data = self.get_bkg(id, bkg_id)
        if data.units != 'channel' and data._responses:

            instruments = (sherpa.astro.instrument.RSPModel,
                           sherpa.astro.instrument.RMFModel,
                           sherpa.astro.instrument.ARFModel,
                           sherpa.astro.instrument.MultiResponseSumModel,
                           sherpa.astro.instrument.PileupRMFModel)

            do_warning = True
            # if type(model) in instruments:
            # if isinstance(model, instruments):
            if sherpa.ui.utils._is_subclass(type(model), instruments):
                do_warning = False
            for part in model:
                # if type(part) in instruments:
                # if isinstance(part, instruments):
                if sherpa.ui.utils._is_subclass(type(part), instruments):
                    do_warning = False
            if do_warning:
                self.delete_bkg_model(id, bkg_id)
                raise TypeError("PHA background source model '%s' \n" % model.name +
                                " does not have an associated instrument model;" +
                                " consider using\n set_bkg_source() instead of" +
                                " set_bkg_model() to include associated\n instrument" +
                                " automatically")

        self._runparamprompt(model.pars)

    # DOC-TODO: should probably explain more about how backgrounds are fit?
    def set_bkg_model(self, id, model=None, bkg_id=None):
        """Set the background model expression for a PHA data set.

        The background emission can be fit by a model, defined by the
        `set_bkg_model` call, rather than subtracted from the data.
        If the background is subtracted then the background model is
        ignored when fitting the data.

        Parameters
        ----------
        id : int or str, optional
           The data set containing the source expression. If not given
           then the default identifier is used, as returned by
           `get_default_id`.
        model : str or sherpa.models.Model object
           This defines the model used to fit the data. It can be a
           Python expression or a string version of it.
        bkg_id : int or str, optional
           The identifier for the background of the data set, in
           cases where multiple backgrounds are provided.

        See Also
        --------
        delete_model : Delete the model expression from a data set.
        fit : Fit one or more data sets.
        integrate1d : Integrate 1D source expressions.
        set_model : Set the model expression for a data set.
        set_bkg_full_model : Define the convolved background model expression for a PHA data set.
        show_bkg_model : Display the background model expression for a data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `model` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `model` parameters,
        respectively.

        The emission defined by the background model expression is
        included in the fit to the source dataset, scaling by exposure
        time and area size (given by the ratio of the background to
        source BACKSCAL values). That is, if ``src_model`` and
        ``bkg_model`` represent the source and background model
        expressions set by calls to `set_model` and `set_bkg_model`
        respectively, the source data is fit by::

           src_model + scale * bkg_model

        where ``scale`` is the scaling factor.

        PHA data sets will automatically apply the instrumental
        response (ARF and RMF) to the background expression. For some
        cases this is not useful - for example, when different
        responses should be applied to different model components - in
        which case `set_bkg_full_model` should be used instead.

        Examples
        --------

        The background is model by a gaussian line (``gauss1d`` model
        component called ``bline``) together with an absorbed polynomial
        (the ``bgnd`` component). The absorbing component (``gal``) is
        also used in the source expression.

        >>> set_model(xsphabs.gal*powlaw1d.pl)
        >>> set_bkg_model(gauss1d.bline + gal*polynom1d.bgnd)

        In this example, the default data set has two background
        estimates, so models are set for both components. The same
        model is applied to both, except that the relative
        normalisations are allowed to vary (by inclusion of the
        ``scale`` component).

        >>> bmodel = xsphabs.gabs * powlaw1d.pl
        >>> set_bkg_model(2, bmodel)
        >>> set_bkg_model(2, bmodel * const1d.scale, bkg_id=2)

        """
        if model is None:
            id, model = model, id

        id = self._fix_id(id)
        bkg_id = self._fix_background_id(id, bkg_id)

        if isinstance(model, string_types):
            model = self._eval_model_expression(model)
        _check_type(model, sherpa.models.Model, 'model',
                    'a model object or model expression string')

        self._background_sources.setdefault(id, {})[bkg_id] = model

        self._runparamprompt(model.pars)

        # Delete any previous model set with set_full_bkg_model()
        bkg_mdl = self._background_models.get(id, {}).pop(bkg_id, None)
        if bkg_mdl is not None:
            warning("Clearing background convolved model\n'%s'\n" %
                    (bkg_mdl.name) + "for dataset %s background %s" %
                    (str(id), str(bkg_id)))

    set_bkg_source = set_bkg_model

    def delete_bkg_model(self, id=None, bkg_id=None):
        """Delete the background model expression for a data set.

        This removes the model expression, created by `set_bkg_model`,
        for the background component of a data set. It does not delete
        the components of the expression, or remove the models for any
        other background components or the source of the data set.

        Parameters
        ----------
        id : int or str, optional
           The data set containing the source expression. If not given
           then the default identifier is used, as returned by
           `get_default_id`.
        bkg_id : int or string, optional
           The identifier for the background component to use.

        See Also
        --------
        clean : Clear all stored session data.
        delete_model : Delete the model expression for a data set.
        get_default_id : Return the default data set identifier.
        list_bkg_ids : List all the background identifiers for a data set.
        set_model : Set the source model expression for a data set.
        show_model : Display the source model expression for a data set.

        Examples
        --------

        Remove the background model expression for the default data set:

        >>> delete_bkg_model()

        Remove the model expression for the background component
        labelled 'down' for the data set with the identifier 'src':

        >>> delete_bkg_model('src', 'down')

        """
        id = self._fix_id(id)
        bkg_id = self._fix_background_id(id, bkg_id)

        # remove dependency of having a loaded PHA dataset at the time
        # of bkg model init.
        #  bkg_id = self._get_pha_data(id)._fix_background_id(bkg_id)
        self._background_models.get(id, {}).pop(bkg_id, None)
        self._background_sources.get(id, {}).pop(bkg_id, None)

    def _read_user_model(self, filename, *args, **kwargs):
        x = None
        y = None
        try:
            data = self.unpack_ascii(filename, *args, **kwargs)
            x = data.get_x()
            y = data.get_y()

        # we have to check for the case of a *single* column in an ascii file
        # extract the single array from the read and bypass the dataset
        except TypeError:
            y = sherpa.astro.io.backend.get_ascii_data(filename, *args,
                                                       **kwargs)[1].pop()
        except:
            try:
                data = self.unpack_table(filename, *args, **kwargs)
                x = data.get_x()
                y = data.get_y()

            # we have to check for the case of a *single* column in a
            # fits table
            # extract the single array from the read and bypass the dataset
            except TypeError:
                y = sherpa.astro.io.backend.get_table_data(filename, *args,
                                                           **kwargs)[1].pop()
            except:
                # unpack_data doesn't include a call to try
                # getting data from image, so try that here.
                data = self.unpack_image(filename, *args, **kwargs)
                # x = data.get_x()
                y = data.get_y()

        return (x, y)

    def load_xstable_model(self, modelname, filename, etable=False):
        """Load a XSPEC table model.

        Create an additive ('atable', [1]_), multiplicative
        ('mtable', [2]_), or exponential ('etable', [3]_) XSPEC
        table model component. These models may have multiple model
        parameters.

        .. versionchanged:: 4.14.0
           The etable argument has been added to allow exponential table
           models to be used.

        Parameters
        ----------
        modelname : str
           The identifier for this model component.
        filename : str
           The name of the FITS file containing the data, which should
           match the XSPEC table model definition [4]_.
        etable : bool, optional
           Set if this is an etable (as there's no way to determine this
           from the file itself). Defaults to False.

        Raises
        ------
        sherpa.utils.err.ImportErr
           If XSPEC support is not enabled.

        See Also
        --------
        load_conv : Load a 1D convolution model.
        load_psf : Create a PSF model
        load_template_model : Load a set of templates and use it as a model component.
        load_table_model : Load tabular or image data and use it as a model component.
        set_model : Set the source model expression for a data set.
        set_full_model : Define the convolved model expression for a data set.

        Notes
        -----
        NASA's HEASARC site contains a link to community-provided
        XSPEC table models [5]_.

        References
        ----------

        .. [1] http://heasarc.gsfc.nasa.gov/docs/xanadu/xspec/manual/XSmodelAtable.html

        .. [2] http://heasarc.gsfc.nasa.gov/docs/xanadu/xspec/manual/XSmodelMtable.html

        .. [3] http://heasarc.gsfc.nasa.gov/docs/xanadu/xspec/manual/XSmodelEtable.html

        .. [4] http://heasarc.gsfc.nasa.gov/docs/heasarc/ofwg/docs/general/ogip_92_009/ogip_92_009.html

        .. [5] https://heasarc.gsfc.nasa.gov/xanadu/xspec/newmodels.html

        Examples
        --------

        Load in the XSPEC table model from the file 'bbrefl_1xsolar.fits'
        and create a model component labelled 'xtbl', which is then
        used in a source expression:

        >>> load_xstable_model('xtbl', 'bbrefl_1xsolar.fits')
        >>> set_source(xsphabs.gal * xtbl)
        >>> print(xtbl)

        Load in an XSPEC etable model:

        >>> load_xstable_model('etbl', 'etable.mod', etable=True)

        """

        try:
            from sherpa.astro import xspec
        except ImportError as exc:
            # TODO: what is the best error to raise here?
            raise ImportErr('notsupported', 'XSPEC') from exc

        tablemodel = xspec.read_xstable_model(modelname, filename, etable=etable)
        self._tbl_models.append(tablemodel)
        self._add_model_component(tablemodel)

    # also in sherpa.utils
    # DOC-NOTE: can filename be a crate/hdulist?
    # DOC-TODO: how to describe the supported args/kwargs (not just for this function)?
    def load_table_model(self, modelname, filename,
                         method=sherpa.utils.linear_interp, *args, **kwargs):
        # pylint: disable=W1113
        """Load tabular or image data and use it as a model component.

        .. note:: Deprecated in Sherpa 4.9
                  The new `load_xstable_model` routine should be used for
                  loading XSPEC table model files. Support for these files
                  will be removed from `load_table_model` in the next
                  release.

        A table model is defined on a grid of points which is
        interpolated onto the independent axis of the data set.  The
        model will have at least one parameter (the amplitude, or
        scaling factor to multiply the data by), but may have more
        (if X-Spec table models are used).

        Parameters
        ----------
        modelname : str
           The identifier for this table model.
        filename : str
           The name of the file containing the data, which should
           contain two columns, which are the x and y values for
           the data, or be an image.
        method : func
           The interpolation method to use to map the input data onto
           the coordinate grid of the data set. Linear,
           nearest-neighbor, and polynomial schemes are provided in
           the sherpa.utils module.
        args
           Arguments for reading in the data.
        kwargs
           Keyword arguments for reading in the data.

        See Also
        --------
        load_conv : Load a 1D convolution model.
        load_psf : Create a PSF model
        load_template_model : Load a set of templates and use it as a model component.
        load_xstable_model : Load a XSPEC table model.
        set_model : Set the source model expression for a data set.
        set_full_model : Define the convolved model expression for a data set.

        Notes
        -----
        Examples of interpolation schemes provided by `sherpa.utils`
        are: `linear_interp`, `nearest_interp`, `neville`, and
        `neville2d`.

        Examples
        --------

        Load in the data from filt.fits and use it to multiply
        the source model (a power law and a gaussian). Allow
        the amplitude for the table model to vary between 1
        and 1e6, starting at 1e3.

        >>> load_table_model('filt', 'filt.fits')
        >>> set_source(filt * (powlaw1d.pl + gauss1d.gline))
        >>> set_par(filt.ampl, 1e3, min=1, max=1e6)

        Load in an image ("broad.img") and use the pixel values as a
        model component for data set "img":

        >>> load_table_model('emap', 'broad.img')
        >>> set_source('img', emap * gauss2d)

        """
        tablemodel = TableModel(modelname)
        # interpolation method
        tablemodel.method = method
        tablemodel.filename = filename

        try:
            if not sherpa.utils.is_binary_file(filename):
                # TODO: use a Sherpa exception
                raise Exception("Not a FITS file")

            self.load_xstable_model(modelname, filename)
            warnings.warn('Use load_xstable_model to load XSPEC table models',
                          DeprecationWarning)
            return

        except Exception:
            x = None
            y = None
            try:
                x, y = self._read_user_model(filename, *args, **kwargs)
            except:
                # Fall back to reading plain ASCII, if no other
                # more sophisticated I/O backend loaded (such as
                # pyfits or crates) SMD 05/29/13
                data = sherpa.io.read_data(filename, ncols=2)
                x = data.x
                y = data.y
            tablemodel.load(x, y)

        self._tbl_models.append(tablemodel)
        self._add_model_component(tablemodel)

    # ## also in sherpa.utils
    # DOC-TODO: how to describe *args/**kwargs
    # DOC-TODO: how is the _y value used if set
    def load_user_model(self, func, modelname, filename=None, *args, **kwargs):
        # pylint: disable=W1113
        """Create a user-defined model.

        Assign a name to a function; this name can then be used as any
        other name of a model component, either in a source expression
        - such as with `set_model` - or to change a parameter
        value. The `add_user_pars` function should be called after
        `load_user_model` to set up the parameter names and
        defaults.

        Parameters
        ----------
        func : func
           The function that evaluates the model.
        modelname : str
           The name to use to refer to the model component.
        filename : str, optional
           Set this to include data from this file in the model. The
           file should contain two columns, and the second column is
           stored in the ``_y`` attribute of the model.
        args
           Arguments for reading in the data from `filename`, if set.
           See `load_table` and `load_image` for more information.
        kwargs
           Keyword arguments for reading in the data from `filename`,
           if set. See `load_table` and `load_image` for more information.

        See Also
        --------
        add_model : Create a user-defined model class.
        add_user_pars : Add parameter information to a user model.
        load_image : Load an image as a data set.
        load_table : Load a FITS binary file as a data set.
        load_table_model : Load tabular data and use it as a model component.
        load_template_model : Load a set of templates and use it as a model component.
        set_model : Set the source model expression for a data set.

        Notes
        -----
        The `load_user_model` function is designed to make it easy to
        add a model, but the interface is not the same as the existing
        models (such as having to call both `load_user_model` and
        `add_user_pars` for each new instance).  The `add_model`
        function is used to add a model as a Python class, which is
        more work to set up, but then acts the same way as the
        existing models.

        The function used for the model depends on the dimensions of
        the data. For a 1D model, the signature is::

           def func1d(pars, x, xhi=None):

        where, if xhi is not None, then the dataset is binned and the
        x argument is the low edge of each bin. The pars argument is
        the parameter array - the names, defaults, and limits can be
        set with `add_user_pars` - and should not be changed.  The
        return value is an array the same size as x.

        For 2D models, the signature is::

           def func2d(pars, x0, x1, x0hi=None, x1hi=None):

        There is no way using this interface to indicate that the
        model is for 1D or 2D data.

        Examples
        --------

        Create a two-parameter model of the form "y = mx + c",
        where the intercept is the first parameter and the slope the
        second, set the parameter names and default values, then
        use it in a source expression:

        >>> def func1d(pars, x, xhi=None):
        ...     if xhi is not None:
        ...         x = (x + xhi)/2
        ...     return x * pars[1] + pars[0]
        ...
        >>> load_user_model(func1d, "myfunc")
        >>> add_user_pars(myfunc, ["c", "m"], [0, 1])
        >>> set_source(myfunc + gauss1d.gline)

        """
        usermodel = sherpa.models.UserModel(modelname)
        usermodel.calc = func
        usermodel._file = filename
        if filename is not None:
            _, usermodel._y = self._read_user_model(filename, *args, **kwargs)

        self._add_model_component(usermodel)

    ###########################################################################
    # Fitting
    ###########################################################################

    # TODO: change bkg_ids default to None or some other "less-dangerous" value
    def _add_extra_data_and_models(self, ids, datasets, models, bkg_ids={}):
        for id, d in zip(ids, datasets):
            if isinstance(d, sherpa.astro.data.DataPHA):
                bkg_models = self._background_models.get(id, {})
                bkg_srcs = self._background_sources.get(id, {})
                if d.subtracted:
                    if (bkg_models or bkg_srcs):
                        warning(('data set %r is background-subtracted; ' +
                                 'background models will be ignored') % id)
                elif not (bkg_models or bkg_srcs):
                    if d.background_ids and self._current_stat.name != 'wstat':
                        warning(('data set %r has associated backgrounds, ' +
                                 'but they have not been subtracted, ' +
                                 'nor have background models been set') % id)
                else:
                    bkg_ids[id] = []
                    for bkg_id in d.background_ids:

                        if not (bkg_id in bkg_models or bkg_id in bkg_srcs):
                            raise ModelErr('nobkg', bkg_id, id)

                        bkg = d.get_background(bkg_id)
                        datasets.append(bkg)

                        bkg_data = d
                        if len(bkg.response_ids) != 0:
                            bkg_data = bkg

                        bkg_model = bkg_models.get(bkg_id, None)
                        bkg_src = bkg_srcs.get(bkg_id, None)
                        if bkg_model is None and bkg_src is not None:
                            resp = sherpa.astro.instrument.Response1D(bkg_data)
                            bkg_model = resp(bkg_src)
                        models.append(bkg_model)
                        bkg_ids[id].append(bkg_id)

    def _prepare_bkg_fit(self, id, otherids=()):

        # prep data ids for fitting
        ids = self._get_fit_ids(id, otherids)

        # Gather up lists of data objects and models to fit
        # to them.  Add to lists *only* if there actually is
        # a model to fit.  E.g., if data sets 1 and 2 exist,
        # but only data set 1 has a model, then "fit all" is
        # understood to mean "fit 1".  If both data sets have
        # models, then "fit all" means "fit 1 and 2 together".
        datasets = []
        models = []
        fit_to_ids = []
        for i in ids:

            # get PHA data and associated background models by id
            data = self._get_pha_data(i)
            bkg_models = self._background_models.get(i, {})
            bkg_sources = self._background_sources.get(i, {})

            for bi in data.background_ids:
                mod = None
                ds = self.get_bkg(i, bi)
                if bi in bkg_models or bi in bkg_sources:
                    mod = self.get_bkg_model(i, bi)

                if mod is not None:
                    datasets.append(ds)
                    models.append(mod)

            fit_to_ids.append(i)

        # If no data sets have models assigned to them, stop now.
        if len(models) < 1:
            raise IdentifierErr("nomodels")

        return fit_to_ids, datasets, models

    def _get_bkg_fit(self, id, otherids=(), estmethod=None, numcores=1):

        fit_to_ids, datasets, models = self._prepare_bkg_fit(id, otherids)

        # Do not add backgrounds to backgrounds.
        # self._add_extra_data_and_models(fit_to_ids, datasets, models)

        fit_to_ids = tuple(fit_to_ids)

        f = self._get_fit_obj(datasets, models, estmethod, numcores)

        return fit_to_ids, f

    # also in sherpa.utils
    # DOC-TODO: existing docs suggest that bkg_only can be set, but looking
    # at the code it is always set to False.
    #
    def fit(self, id=None, *otherids, **kwargs):
        # pylint: disable=W1113
        """Fit a model to one or more data sets.

        Use forward fitting to find the best-fit model to one or more
        data sets, given the chosen statistic and optimization
        method. The fit proceeds until the results converge or the
        number of iterations exceeds the maximum value (these values
        can be changed with `set_method_opt`). An iterative scheme can
        be added using `set_iter_method` to try and improve the
        fit. The final fit results are displayed to the screen and can
        be retrieved with `get_fit_results`.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then
           all data sets with an associated model are fit simultaneously.
        *otherids : sequence of int or str, optional
           Other data sets to use in the calculation.
        outfile : str, optional
           If set, then the fit results will be written to a file with
           this name. The file contains the per-iteration fit results.
        clobber : bool, optional
           This flag controls whether an existing file can be
           overwritten (``True``) or if it raises an exception (``False``,
           the default setting).

        Raises
        ------
        sherpa.utils.err.FitErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        conf : Estimate the confidence intervals using the confidence method.
        contour_fit : Contour the fit to a data set.
        covar : Estimate the confidence intervals using the confidence method.
        fit_bkg : Fit a model to one or more background PHA data sets.
        freeze : Fix model parameters so they are not changed by a fit.
        get_fit_results : Return the results of the last fit.
        plot_fit : Plot the fit results (data, model) for a data set.
        image_fit : Display the data, model, and residuals for a data set in the image viewer.
        set_stat : Set the statistical method.
        set_method : Change the optimization method.
        set_method_opt : Change an option of the current optimization method.
        set_bkg_full_model : Define the convolved background model expression for a PHA data set.
        set_bkg_model : Set the background model expression for a PHA data set.
        set_full_model : Define the convolved model expression for a data set.
        set_iter_method : Set the iterative-fitting scheme used in the fit.
        set_model : Set the model expression for a data set.
        show_fit : Summarize the fit results.
        thaw : Allow model parameters to be varied during a fit.

        Notes
        -----
        For PHA data sets with background components, the function
        will fit any background components for which a background
        model has been created (rather than being subtracted). The
        `fit_bkg` function can be used to fit models to just the
        background data.

        Examples
        --------

        Simultaneously fit all data sets with models and then
        store the results in the variable fres:

        >>> fit()
        >>> fres = get_fit_results()

        Fit just the data set 'img':

        >>> fit('img')

        Simultaneously fit data sets 1, 2, and 3:

        >>> fit(1, 2, 3)

        Fit data set 'jet' and write the fit results to the text file
        'jet.fit', over-writing it if it already exists:

        >>> fit('jet', outfile='jet.fit', clobber=True)

        """
        kwargs['bkg_only'] = False
        self._fit(id, *otherids, **kwargs)

    def fit_bkg(self, id=None, *otherids, **kwargs):
        # pylint: disable=W1113
        """Fit a model to one or more background PHA data sets.

        Fit only the backgound components of PHA data sets.  This can
        be used to find the best-fit background parameters, which can
        then be frozen before fitting the data, or to ensure that
        these parameters are well defined before performing a
        simultaneous source and background fit.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the background data. If not
           given then all data sets with an associated background
           model are fit simultaneously.
        *otherids : sequence of int or str, optional
           Other data sets to use in the calculation.
        outfile : str, optional
           If set, then the fit results will be written to a file with
           this name. The file contains the per-iteration fit results.
        clobber : bool, optional
           This flag controls whether an existing file can be
           overwritten (``True``) or if it raises an exception (``False``,
           the default setting).

        Raises
        ------
        sherpa.utils.err.FitErr
           If `filename` already exists and `clobber` is ``False``.

        See Also
        --------
        conf : Estimate the confidence intervals using the confidence method.
        contour_fit : Contour the fit to a data set.
        covar : Estimate the confidence intervals using the confidence method.
        fit : Fit a model to one or more data sets.
        freeze : Fix model parameters so they are not changed by a fit.
        get_fit_results : Return the results of the last fit.
        plot_fit : Plot the fit results (data, model) for a data set.
        image_fit : Display the data, model, and residuals for a data set in the image viewer.
        set_stat : Set the statistical method.
        set_method : Change the optimization method.
        set_method_opt : Change an option of the current optimization method.
        set_bkg_full_model : Define the convolved background model expression for a PHA data set.
        set_bkg_model : Set the background model expression for a PHA data set.
        set_full_model : Define the convolved model expression for a data set.
        set_iter_method : Set the iterative-fitting scheme used in the fit.
        set_model : Set the model expression for a data set.
        show_bkg_source : Display the background model expression for a data set.
        show_bkg_model : Display the background model expression used to fit a data set.
        show_fit : Summarize the fit results.
        thaw : Allow model parameters to be varied during a fit.

        Notes
        -----
        This is only for PHA data sets where the background is being
        modelled, rather than subtracted from the data.

        Examples
        --------

        Simultaneously fit all background data sets with models and
        then store the results in the variable fres:

        >>> fit_bkg()
        >>> fres = get_fit_results()

        Fit the background for data sets 1 and 2, then do a
        simultaneous fit to the source and background data sets:

        >>> fit_bkg(1,2)
        >>> fit(1,2)

        """
        kwargs['bkg_only'] = True
        self._fit(id, *otherids, **kwargs)

    def _fit(self, id=None, *otherids, **kwargs):
        # pylint: disable=W1113
        ids = f = None
        fit_bkg = False

        if 'bkg_only' in kwargs and kwargs.pop('bkg_only'):
            fit_bkg = True

        # validate the kwds to f.fit() so user typos do not
        # result in regular fit
        # valid_keys = sherpa.utils.get_keyword_names(sherpa.fit.Fit.fit)
        valid_keys = ('outfile', 'clobber', 'filter_nan', 'cache', 'numcores')
        for key in kwargs.keys():
            if key not in valid_keys:
                raise TypeError("unknown keyword argument: '%s'" % key)

        numcores = kwargs.get('numcores', 1)

        if fit_bkg:
            ids, f = self._get_bkg_fit(id, otherids, numcores=numcores)
        else:
            ids, f = self._get_fit(id, otherids, numcores=numcores)

        if 'filter_nan' in kwargs and kwargs.pop('filter_nan'):
            for i in ids:
                self.get_data(i).mask = self.get_data(
                    i).mask & numpy.isfinite(self.get_data(i).get_x())

        res = f.fit(**kwargs)
        res.datasets = ids
        self._fit_results = res
        info(res.format())

    def _get_stat_info(self):

        ids, datasets, models = self._prepare_fit(None)

        extra_ids = {}
        self._add_extra_data_and_models(ids, datasets, models, extra_ids)

        output = []
        nids = len(ids)
        if len(datasets) > 1:
            bkg_datasets = datasets[nids:]
            bkg_models = models[nids:]
            jj = 0
            for id, d, m in zip(ids, datasets[:nids], models[:nids]):
                f = sherpa.fit.Fit(d, m, self._current_stat)

                statinfo = f.calc_stat_info()
                statinfo.name = 'Dataset %s' % (str(id))
                statinfo.ids = (id,)

                output.append(statinfo)

                bkg_ids = extra_ids.get(id, ())
                nbkg_ids = len(bkg_ids)
                idx_lo = jj * nbkg_ids
                idx_hi = idx_lo + nbkg_ids
                for bkg_id, bkg, bkg_mdl in zip(bkg_ids,
                                                bkg_datasets[idx_lo:idx_hi],
                                                bkg_models[idx_lo:idx_hi]):

                    bkg_f = sherpa.fit.Fit(bkg, bkg_mdl, self._current_stat)

                    statinfo = bkg_f.calc_stat_info()
                    statinfo.name = ("Background %s for Dataset %s" %
                                     (str(bkg_id), str(id)))
                    statinfo.ids = (id,)
                    statinfo.bkg_ids = (bkg_id,)

                    output.append(statinfo)

                jj += 1

        f = self._get_fit_obj(datasets, models, None)
        statinfo = f.calc_stat_info()
        if len(ids) == 1:
            statinfo.name = 'Dataset %s' % str(ids)
        else:
            statinfo.name = 'Datasets %s' % str(ids).strip("()")
        statinfo.ids = ids
        output.append(statinfo)

        return output

    ###########################################################################
    # Plotting
    ###########################################################################

    def get_data_plot(self, id=None, recalc=True):
        try:
            d = self.get_data(id)
        except IdentifierErr:
            return super().get_data_plot(id, recalc=recalc)

        if isinstance(d, sherpa.astro.data.DataPHA):
            plotobj = self._dataphaplot
            if recalc:
                plotobj.prepare(d, self.get_stat())
            return plotobj

        return super().get_data_plot(id, recalc=recalc)

    get_data_plot.__doc__ = sherpa.ui.utils.Session.get_data_plot.__doc__

    def get_model_plot(self, id=None, recalc=True):
        try:
            d = self.get_data(id)
        except IdentifierErr:
            return super().get_model_plot(id, recalc=recalc)

        if isinstance(d, sherpa.astro.data.DataPHA):
            plotobj = self._modelhisto
            if recalc:
                plotobj.prepare(d, self.get_model(id), self.get_stat())
            return plotobj

        return super().get_model_plot(id, recalc=recalc)

    get_model_plot.__doc__ = sherpa.ui.utils.Session.get_model_plot.__doc__

    # also in sherpa.utils, but without the lo/hi arguments
    def get_source_plot(self, id=None, lo=None, hi=None, recalc=True):
        """Return the data used by plot_source.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        lo : number, optional
           The low value to plot (only used for PHA data sets).
        hi : number, optional
           The high value to plot (only use for PHA data sets).
        recalc : bool, optional
           If ``False`` then the results from the last call to
           `plot_source` (or `get_source_plot`) are returned,
           otherwise the data is re-generated.

        Returns
        -------
        instance
           An object representing the data used to create the plot by
           `plot_source`. The return value depends on the data
           set (e.g. PHA, 1D binned, 1D un-binned). If ``lo`` or ``hi``
           were set then the ``mask`` attribute of the object can be
           used to apply the filter to the ``xlo``, ``xhi``, and ``y``
           attributes.

        See Also
        --------
        get_model_plot : Return the data used by plot_model.
        plot_model : Plot the model for a data set.
        plot_source : Plot the source expression for a data set.

        Examples
        --------

        Retrieve the source plot information for the default data
        set and then display it:

        >>> splot = get_source_plot()
        >>> print(splot)

        Return the plot data for data set 2, and then use it to create
        a plot:

        >>> s2 = get_source_plot(2)
        >>> s2.plot()

        Retrieve the source plots for the 0.5 to 7 range of the
        'jet' and 'core' data sets and display them on the same plot:

        >>> splot1 = get_source_plot(id='jet', lo=0.5, hi=7)
        >>> splot2 = get_source_plot(id='core', lo=0.5, hi=7)
        >>> splot1.plot()
        >>> splot2.overplot()

        Access the plot data (for a PHA data set) and select only the
        bins corresponding to the 2-7 keV range defined in the call:

        >>> splot = get_source_plot(lo=2, hi=7)
        >>> xlo = splot.xlo[splot.mask]
        >>> xhi = splot.xhi[splot.mask]
        >>> y = splot.y[splot.mask]

        For a PHA data set, the units on both the X and Y axes of the
        plot are controlled by the `set_analysis` command. In this
        case the Y axis will be in units of photon/s/cm^2/keV x Energy
        and the X axis in keV:

        >>> set_analysis('energy', factor=1)
        >>> splot = get_source_plot()
        >>> print(splot)

        """

        try:
            d = self.get_data(id)
        except IdentifierErr as ie:
            if recalc:
                raise ie
            d = None

        if isinstance(d, sherpa.astro.data.DataPHA):
            plotobj = self._astrosourceplot
            if recalc:
                plotobj.prepare(d, self.get_source(id), lo=lo, hi=hi)
            return plotobj

        return super().get_source_plot(id, recalc=recalc)

    def get_fit_plot(self, id=None, recalc=True):

        plotobj = self._fitplot
        if not recalc:
            return plotobj

        d = self.get_data(id)
        if isinstance(d, sherpa.astro.data.DataPHA):

            dataobj = self.get_data_plot(id, recalc=recalc)

            # We don't use get_model_plot as that uses the ungrouped data
            #    modelobj = self.get_model_plot(id)
            # but we do want to use a histogram plot, not _modelplot.
            # modelobj = self._modelplot

            # Should this object be stored in self? There's
            # no way to get it by API (apart from get_fit_plot).
            #
            modelobj = sherpa.astro.plot.ModelPHAHistogram()
            modelobj.prepare(d, self.get_model(id),
                             self.get_stat())

            plotobj.prepare(dataobj, modelobj)
            return plotobj

        return super().get_fit_plot(id, recalc=recalc)

    get_fit_plot.__doc__ = sherpa.ui.utils.Session.get_fit_plot.__doc__

    def get_model_component_plot(self, id, model=None, recalc=True):
        """Return the data used to create the model-component plot.

        For PHA data, the response model is automatically added by the
        routine unless the model contains a response.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        model : str or sherpa.models.model.Model instance
           The component to use (the name, if a string).
        recalc : bool, optional
           If ``False`` then the results from the last call to
           `plot_model_component` (or `get_model_component_plot`)
           are returned, otherwise the data is re-generated.

        Returns
        -------
        instance
           An object representing the data used to create the plot by
           `plot_model_component`. The return value depends on the
           data set (e.g. PHA, 1D binned, or 1D un-binned).

        See Also
        --------
        get_model_plot : Return the data used to create the model plot.
        plot_model : Plot the model for a data set.
        plot_model_component : Plot a component of the model for a data set.

        Notes
        -----
        The function does not follow the normal Python standards for
        parameter use, since it is designed for easy interactive use.
        When called with a single un-named argument, it is taken to be
        the `model` parameter. If given two un-named arguments, then
        they are interpreted as the `id` and `model` parameters,
        respectively.

        Examples
        --------

        Return the plot data for the ``pl`` component used in the
        default data set:

        >>> cplot = get_model_component_plot(pl)

        Return the full source model (``fplot``) and then for the
        components ``gal * pl`` and ``gal * gline``, for the data set
        'jet':

        >>> fmodel = xsphabs.gal * (powlaw1d.pl + gauss1d.gline)
        >>> set_source('jet', fmodel)
        >>> fit('jet')
        >>> fplot = get_model_plot('jet')
        >>> plot1 = get_model_component_plot('jet', pl*gal)
        >>> plot2 = get_model_component_plot('jet', gline*gal)

        For PHA data sets the response is automatically added, but it
        can also be manually specified. In the following plot1 and
        plot2 contain the same data:

        >>> plot1 = get_model_component_plot(pl)
        >>> rsp = get_response()
        >>> plot2 = get_model_component_plot(rsp(pl))

        """
        if model is None:
            id, model = model, id
        model = self._check_model(model)

        try:
            d = self.get_data(id)
        except IdentifierErr as ie:
            if recalc:
                raise ie
            d = None

        if isinstance(d, sherpa.astro.data.DataPHA):
            plotobj = self._astrocompmdlplot
            if recalc:
                if not has_pha_response(model):
                    try:
                        rsp = self.get_response(id)  # TODO: bkg_id?
                        model = rsp(model)
                    except DataErr:
                        # no response
                        pass

                plotobj.prepare(d, model, self.get_stat())
            return plotobj

        return super().get_model_component_plot(id, model=model, recalc=recalc)

    # copy doc string from sherpa.utils
    def get_source_component_plot(self, id, model=None, recalc=True):
        if model is None:
            id, model = model, id
        model = self._check_model(model)

        try:
            d = self.get_data(id)
        except IdentifierErr as ie:
            if recalc:
                raise ie
            d = None

        if isinstance(d, sherpa.astro.data.DataPHA):
            plotobj = self._astrocompsrcplot
            if recalc:
                plotobj.prepare(d, model, self.get_stat())
            return plotobj

        return super().get_source_component_plot(id, model=model, recalc=recalc)

    get_source_component_plot.__doc__ = sherpa.ui.utils.Session.get_source_component_plot.__doc__

    def get_pvalue_plot(self, null_model=None, alt_model=None, conv_model=None,
                        id=1, otherids=(), num=500, bins=25, numcores=None,
                        recalc=False):

        if recalc and conv_model is None and \
           isinstance(self.get_data(id), sherpa.astro.data.DataPHA):
            conv_model = self.get_response(id)

        return super().get_pvalue_plot(null_model=null_model, alt_model=alt_model,
                                       conv_model=conv_model, id=id, otherids=otherids,
                                       num=num, bins=bins, numcores=numcores,
                                       recalc=recalc)

    get_pvalue_plot.__doc__ = sherpa.ui.utils.Session.get_pvalue_plot.__doc__

    def get_order_plot(self, id=None, orders=None, recalc=True):
        """Return the data used by plot_order.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        orders : optional
           Which response to use. The argument can be a scalar or
           array, in which case multiple curves will be displayed.
           The default is to use all orders.
        recalc : bool, optional
           If ``False`` then the results from the last call to
           `plot_order` (or `get_order_plot`) are returned, otherwise
           the data is re-generated.

        Returns
        -------
        data : a `sherpa.astro.plot.OrderPlot` instance
           An object representing the data used to create the plot by
           `plot_order`.

        See Also
        --------
        get_default_id : Return the default data set identifier.
        plot_order : Plot the model for a data set convolved by the given response.

        Examples
        --------

        Retrieve the plot information for order 1 of the default data set
        and then display it:

        >>> oplot = get_order_plot(orders=1)
        >>> print(oplot)

        Return the plot data for orders 1 and 2 of data set 'jet', plot the
        first and then overplot the second:

        >>> plots = get_order_plot('jet', orders=[1, 2])
        >>> plots[0].plot()
        >>> plots[1].overplot()

        """

        plotobj = self._orderplot
        if recalc:
            plotobj.prepare(self._get_pha_data(id),
                            self.get_model(id), orders=orders)
        return plotobj

    def get_arf_plot(self, id=None, resp_id=None, recalc=True):
        """Return the data used by plot_arf.

        Parameters
        ----------
        id : int or str, optional
           The data set with an ARF. If not given then the default
           identifier is used, as returned by `get_default_id`.
        resp_id : int or str, optional
           Which ARF to use in the case that multiple ARFs are
           associated with a data set. The default is ``None``,
           which means the first one.
        recalc : bool, optional
           If ``False`` then the results from the last call to
           `plot_arf` (or `get_arf_plot`) are returned, otherwise
           the data is re-generated.

        Returns
        -------
        arf_plot : a `sherpa.astro.plot.ARFPlot` instance

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.

        See Also
        --------
        plot : Create one or more plot types.
        plot_arf : Plot the ARF associated with a data set.

        Examples
        --------

        Return the ARF plot data for the default data set:

        >>> aplot = get_arf_plot()
        >>> aplot.y.max()
        676.95794677734375

        Return the ARF data for the second response of the
        data set labelled 'histate', and then plot it:

        >>> aplot = get_arf_plot('histate', 2)
        >>> aplot.plot()

        """

        plotobj = self._arfplot
        if not recalc:
            return plotobj

        id = self._fix_id(id)
        arf = self._get_pha_data(id).get_arf(resp_id)
        if arf is None:
            raise DataErr('noarf', id)

        plotobj.prepare(arf, self._get_pha_data(id))
        return plotobj

    def get_bkg_fit_plot(self, id=None, bkg_id=None, recalc=True):
        """Return the data used by plot_bkg_fit.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        recalc : bool, optional
           If ``False`` then the results from the last call to
           `plot_bkg_fit` (or `get_bkg_fit_plot`) are returned,
           otherwise the data is re-generated.

        Returns
        -------
        model : a `sherpa.astro.plot.BkgFitPlot` instance
           An object representing the data used to create the plot by
           `plot_bkg_fit`.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_plot : Return the data used by plot_bkg.
        get_bkg_model_plot : Return the data used by plot_bkg_model.
        plot_bkg_fit : Plot the fit results (data, model) for the background of a PHA data set.

        Examples
        --------

        Create the data needed to create the "fit plot" for the background
        of the default data set and display it:

        >>> bplot = get_bkg_fit_plot()
        >>> print(bplot)

        Return the plot data for data set 2, and then use it to create
        a plot:

        >>> b2 = get_bkg_fit_plot(2)
        >>> b2.plot()

        The fit plot consists of a combination of a data plot and a
        model plot, which are captured in the `dataplot` and `modelplot`
        attributes of the return value. These can be used to display
        the plots individually, such as:

        >>> b2.dataplot.plot()
        >>> b2.modelplot.plot()

        or, to combine the two:

        >>> b2.dataplot.plot()
        >>> b2.modelplot.overplot()

        Return the plot data for the second background component to the
        "jet" data set:

        >>> bplot = get_bkg_fit_plot('jet', bkg_id=2)

        """

        plotobj = self._bkgfitplot
        if not recalc:
            return plotobj

        dataobj = self.get_bkg_plot(id, bkg_id, recalc=recalc)

        # We don't use get_bkg_model_plot as that uses the ungrouped data
        # modelobj = self.get_bkg_model_plot(id, bkg_id, recalc=recalc)

        modelobj = self._bkgmodelplot
        modelobj.prepare(self.get_bkg(id, bkg_id),
                         self.get_bkg_model(id, bkg_id),
                         self.get_stat())

        plotobj.prepare(dataobj, modelobj)
        return plotobj

    def get_bkg_model_plot(self, id=None, bkg_id=None, recalc=True):
        """Return the data used by plot_bkg_model.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        recalc : bool, optional
           If ``False`` then the results from the last call to
           `plot_bkg_model` (or `get_bkg_model_plot`) are returned,
           otherwise the data is re-generated.

        Returns
        -------
        model : a `sherpa.astro.plot.BkgModelHistogram` instance
           An object representing the data used to create the plot by
           `plot_bkg_model`.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_source_plot : Return the data used by plot_bkg_source.
        plot_bkg_model : Plot the model for the background of a PHA data set.
        plot_bkg_source : Plot the model expression for the background of a PHA data set.

        Examples
        --------

        >>> bplot = get_bkg_model_plot()
        >>> print(bplot)

        >>> get_bkg_model_plot('jet', bkg_id=1).plot()
        >>> get_bkg_model_plot('jet', bkg_id=2).overplot()

        """

        plotobj = self._bkgmodelhisto
        if recalc:
            plotobj.prepare(self.get_bkg(id, bkg_id),
                            self.get_bkg_model(id, bkg_id),
                            self.get_stat())
        return plotobj

    def get_bkg_plot(self, id=None, bkg_id=None, recalc=True):
        """Return the data used by plot_bkg.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        recalc : bool, optional
           If ``False`` then the results from the last call to
           `plot_bkg` (or `get_bkg_plot`) are returned, otherwise
           the data is re-generated.

        Returns
        -------
        data : a `sherpa.astro.plot.BkgDataPlot` instance
           An object representing the data used to create the plot by
           `plot_data`. The relationship between the returned values
           and the values in the data set depend on the analysis,
           filtering, and grouping settings of the data set.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.

        See Also
        --------
        get_default_id : Return the default data set identifier.
        plot_bkg : Plot the background values for a PHA data set.

        Examples
        --------

        Create the data needed to create the "data plot" for the background
        of the default data set and display it:

        >>> bplot = get_bkg_plot()
        >>> print(bplot)

        Return the plot data for data set 2, and then use it to create
        a plot:

        >>> b2 = get_bkg_plot(2)
        >>> b2.plot()

        Return the plot data for the second background component to the
        "jet" data set:

        >>> bplot = get_bkg_plot('jet', bkg_id=2)

        """

        plotobj = self._bkgdataplot
        if recalc:
            plotobj.prepare(self.get_bkg(id, bkg_id),
                            self.get_stat())
        return plotobj

    def get_bkg_source_plot(self, id=None, lo=None, hi=None,
                            bkg_id=None, recalc=True):
        """Return the data used by plot_bkg_source.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        lo : number, optional
           The low value to plot.
        hi : number, optional
           The high value to plot.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        recalc : bool, optional
           If ``False`` then the results from the last call to
           `plot_bkg_source` (or `get_bkg_source_plot`) are returned,
           otherwise the data is re-generated.

        Returns
        -------
        source : a `sherpa.astro.plot.BkgSourcePlot` instance
           An object representing the data used to create the plot by
           `plot_bkg_source`.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_model_plot : Return the data used by plot_bkg_model.
        plot_bkg_model : Plot the model for the background of a PHA data set.
        plot_bkg_source : Plot the model expression for the background of a PHA data set.

        Examples
        --------

        Retrieve the source plot information for the background of
        the default data set and display it:

        >>> splot = get_bkg_source_plot()
        >>> print(splot)

        Return the background plot data for data set 2, and then use it
        to create a plot:

        >>> s2 = get_bkg_source_plot(2)
        >>> s2.plot()

        Create a plot of the first two background components of the
        'histate' data set, overplotting the second on the first:

        >>> b1 = get_bkg_source_plot('histate', bkg_id=1)
        >>> b2 = get_bkg_source_plot('histate', bkg_id=2)
        >>> b1.plot()
        >>> b2.overplot()

        Retrieve the background source plots for the 0.5 to 7 range of the
        'jet' and 'core' data sets and display them on the same plot:

        >>> splot1 = get_bkg_source_plot(id='jet', lo=0.5, hi=7)
        >>> splot2 = get_bkg_source_plot(id='core', lo=0.5, hi=7)
        >>> splot1.plot()
        >>> splot2.overplot()

        For a PHA data set, the units on both the X and Y axes of the
        plot are controlled by the `set_analysis` command. In this
        case the Y axis will be in units of photons/s/cm^2 and the X
        axis in keV:

        >>> set_analysis('energy', factor=1)
        >>> splot = get_bkg_source_plot()
        >>> print(splot)

        """

        plotobj = self._bkgsourceplot
        if recalc:
            plotobj.prepare(self.get_bkg(id, bkg_id),
                            self.get_bkg_source(id, bkg_id),
                            lo=lo, hi=hi)
        return plotobj

    def get_bkg_resid_plot(self, id=None, bkg_id=None, recalc=True):
        """Return the data used by plot_bkg_resid.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        recalc : bool, optional
           If ``False`` then the results from the last call to
           `plot_bkg_resid` (or `get_bkg_resid_plot`) are returned,
           otherwise the data is re-generated.

        Returns
        -------
        resid : a `sherpa.astro.plot.BkgResidPlot` instance
           An object representing the data used to create the plot by
           `plot_bkg_resid`.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_chisqr_plot : Return the data used by plot_bkg_chisqr.
        get_bkg_delchi_plot : Return the data used by plot_bkg_delchi.
        get_bkg_ratio_plot : Return the data used by plot_bkg_ratio.
        plot_bkg_resid : Plot the residual (data-model) values for the background of a PHA data set.

        Examples
        --------

        >>> bplot = get_bkg_resid_plot()
        >>> print(bplot)

        >>> get_bkg_resid_plot('jet', bkg_id=1).plot()
        >>> get_bkg_resid_plot('jet', bkg_id=2).overplot()

        """

        plotobj = self._bkgresidplot
        if recalc:
            plotobj.prepare(self.get_bkg(id, bkg_id),
                            self.get_bkg_model(id, bkg_id),
                            self.get_stat())
        return plotobj

    def get_bkg_ratio_plot(self, id=None, bkg_id=None, recalc=True):
        """Return the data used by plot_bkg_ratio.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        recalc : bool, optional
           If ``False`` then the results from the last call to
           `plot_bkg_ratio` (or `get_bkg_ratio_plot`) are returned,
           otherwise the data is re-generated.

        Returns
        -------
        ratio : a `sherpa.astro.plot.BkgRatioPlot` instance
           An object representing the data used to create the plot by
           `plot_bkg_ratio`.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_chisqr_plot : Return the data used by plot_bkg_chisqr.
        get_bkg_delchi_plot : Return the data used by plot_bkg_delchi.
        get_bkg_resid_plot : Return the data used by plot_bkg_resid.
        plot_bkg_ratio : Plot the ratio of data to model values for the background of a PHA data set.

        Examples
        --------

        >>> bplot = get_bkg_ratio_plot()
        >>> print(bplot)

        >>> get_bkg_ratio_plot('jet', bkg_id=1).plot()
        >>> get_bkg_ratio_plot('jet', bkg_id=2).overplot()

        """

        plotobj = self._bkgratioplot
        if recalc:
            plotobj.prepare(self.get_bkg(id, bkg_id),
                            self.get_bkg_model(id, bkg_id),
                            self.get_stat())
        return plotobj

    def get_bkg_delchi_plot(self, id=None, bkg_id=None, recalc=True):
        """Return the data used by plot_bkg_delchi.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        recalc : bool, optional
           If ``False`` then the results from the last call to
           `plot_bkg_delchi` (or `get_bkg_delchi_plot`) are returned,
           otherwise the data is re-generated.

        Returns
        -------
        delchi : a `sherpa.astro.plot.BkgDelchiPlot` instance
           An object representing the data used to create the plot by
           `plot_bkg_delchi`.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_chisqr_plot : Return the data used by plot_bkg_chisqr.
        get_bkg_ratio_plot : Return the data used by plot_bkg_ratio.
        get_bkg_resid_plot : Return the data used by plot_bkg_resid.
        plot_bkg_delchi : Plot the ratio of residuals to error for the background of a PHA data set.

        Examples
        --------

        >>> bplot = get_bkg_delchi_plot()
        >>> print(bplot)

        >>> get_bkg_delchi_plot('jet', bkg_id=1).plot()
        >>> get_bkg_delchi_plot('jet', bkg_id=2).overplot()


        """

        plotobj = self._bkgdelchiplot
        if recalc:
            plotobj.prepare(self.get_bkg(id, bkg_id),
                            self.get_bkg_model(id, bkg_id),
                            self.get_stat())
        return plotobj

    def get_bkg_chisqr_plot(self, id=None, bkg_id=None, recalc=True):
        """Return the data used by plot_bkg_chisqr.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        recalc : bool, optional
           If ``False`` then the results from the last call to
           `plot_bkg_chisqr` (or `get_bkg_chisqr_plot`) are returned,
           otherwise the data is re-generated.

        Returns
        -------
        chisqr : a `sherpa.astro.plot.BkgChisqrPlot` instance
           An object representing the data used to create the plot by
           `plot_bkg_chisqr`.

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_delchi_plot : Return the data used by plot_bkg_delchi.
        get_bkg_ratio_plot : Return the data used by plot_bkg_ratio.
        get_bkg_resid_plot : Return the data used by plot_bkg_resid.
        plot_bkg_chisqr : Plot the chi-squared value for each point of the background of a PHA data set.

        Examples
        --------

        >>> bplot = get_bkg_chisqr_plot()
        >>> print(bplot)

        >>> get_bkg_chisqr_plot('jet', bkg_id=1).plot()
        >>> get_bkg_chisqr_plot('jet', bkg_id=2).overplot()


        """

        plotobj = self._bkgchisqrplot
        if recalc:
            plotobj.prepare(self.get_bkg(id, bkg_id),
                            self.get_bkg_model(id, bkg_id),
                            self.get_stat())
        return plotobj

    def _prepare_energy_flux_plot(self, plot, lo, hi, id, num, bins,
                                  correlated, numcores, bkg_id,
                                  scales=None, model=None, otherids=(),
                                  clip='hard'):
        """Run sample_energy_flux and convert to a plot.
        """
        dist = self.sample_energy_flux(lo, hi, id=id, otherids=otherids,
                                       num=num, scales=scales, model=model,
                                       correlated=correlated, numcores=numcores,
                                       bkg_id=bkg_id, clip=clip)
        plot.prepare(dist, bins)
        return plot

    def _prepare_photon_flux_plot(self, plot, lo, hi, id, num, bins,
                                  correlated, numcores, bkg_id,
                                  scales=None, model=None, otherids=(),
                                  clip='hard'):
        """Run sample_photon_flux and convert to a plot.
        """
        dist = self.sample_photon_flux(lo, hi, id=id, otherids=otherids,
                                       num=num, scales=scales, model=model,
                                       correlated=correlated, numcores=numcores,
                                       bkg_id=bkg_id, clip=clip)
        plot.prepare(dist, bins)
        return plot

    def get_energy_flux_hist(self, lo=None, hi=None, id=None, num=7500, bins=75,
                             correlated=False, numcores=None, bkg_id=None,
                             scales=None, model=None, otherids=(), recalc=True,
                             clip='hard'):
        """Return the data displayed by plot_energy_flux.

        The get_energy_flux_hist() function calculates a histogram of
        simulated energy flux values representing the energy flux probability
        distribution for a model component, accounting for the errors on the
        model parameters.

        .. versionchanged:: 4.12.2
           The scales parameter is no longer ignored when set and the
           model and otherids parameters have been added. The clip
           argument has been added.

        Parameters
        ----------
        lo : number, optional
           The lower limit to use when summing up the signal. If not
           given then the lower value of the data grid is used.
        hi : optional
           The upper limit to use when summing up the signal. If not
           given then the upper value of the data grid is used.
        id : int or string, optional
           The identifier of the data set to use. If `None`, the
           default value, then all datasets with associated models are
           used to calculate the errors and the model evaluation is
           done using the default dataset.
        num : int, optional
           The number of samples to create. The default is 7500.
        bins : int, optional
           The number of bins to use for the histogram.
        correlated : bool, optional
           If ``True`` (the default is ``False``) then ``scales`` is the
           full covariance matrix, otherwise it is just a 1D array
           containing the variances of the parameters (the diagonal
           elements of the covariance matrix).
        numcores : optional
           The number of CPU cores to use. The default is to use all
           the cores on the machine.
        bkg_id : int or string, optional
           The identifier of the background component to use. This
           should only be set when the line to be measured is in the
           background model.
        scales : array, optional
           The scales used to define the normal distributions for the
           parameters. The size and shape of the array depends on the
           number of free parameters in the fit (n) and the value of
           the `correlated` parameter. When the parameter is `True`,
           scales must be given the covariance matrix for the free
           parameters (a n by n matrix that matches the parameter
           ordering used by Sherpa). For un-correlated parameters
           the covariance matrix can be used, or a one-dimensional
           array of n elements can be used, giving the width (specified
           as the sigma value of a normal distribution) for each
           parameter (e.g. the square root of the diagonal elements
           of the covariance matrix). If the scales parameter is not
           given then the covariance matrix is evaluated for the
           current model and best-fit parameters.
        model : model, optional
           The model to integrate. If left as `None` then the source
           model for the dataset will be used. This can be used to
           calculate the unabsorbed flux, as shown in the examples.
           The model must be part of the source expression.
        otherids : sequence of integer and string ids, optional
           The list of other datasets that should be included when
           calculating the errors to draw values from.
        recalc : bool, optional
           If ``True``, the default, then re-calculate the values rather
           than use the values from the last time the function was
           run.
        clip : {'hard', 'soft', 'none'}, optional
            What clipping strategy should be applied to the sampled
            parameters. The default ('hard') is to fix values at their
            hard limits if they exceed them. A value of 'soft' uses
            the soft limits instead, and 'none' applies no
            clipping.

        Returns
        -------
        hist : a `sherpa.astro.plot.EnergyFluxHistogram` instance
           An object representing the data used to create the plot by
           `plot_energy_flux`.

        See Also
        --------
        get_photon_flux_hist : Return the data displayed by plot_photon_flux.
        plot_energy_flux : Display the energy flux distribution.
        plot_photon_flux : Display the photon flux distribution.
        sample_energy_flux : Return the energy flux distribution of a model.
        sample_flux : Return the flux distribution of a model.
        sample_photon_flux : Return the photon flux distribution of a model.

        Examples
        --------

        Get the energy flux distribution for the range 0.5 to 7 for
        the default data set:

        >>> ehist = get_energy_flux_hist(0.5, 7, num=1000)
        >>> print(ehist)

        Compare the 0.5 to 2 energy flux distribution from the "core"
        data set to the values from the "jet" data set:

        >>> ehist1 = get_energy_flux_hist(0.5, 2, id='jet', num=1000)
        >>> ehist2 = get_energy_flux_hist(0.5, 2, id='core', num=1000)

        Compare the flux distribution for the full source expression
        (aflux) to that for just the pl component (uflux); this can be
        useful to calculate the unabsorbed flux distribution if the
        full source model contains an absorption component:

        >>> aflux = get_energy_flux_hist(0.5, 2, num=1000, bins=20)
        >>> uflux = get_energy_flux_hist(0.5, 2, model=pl, num=1000, bins=20)

        When there are multiple datasets loaded,
        `get_energy_flux_hist` uses all datasets to evaluate the
        errors when the `id` parameter is left at its default value of
        `None`. The `otherids` parameter is used, along with `id`, to
        specify exactly what datasets are used:

        >>> x = get_energy_flux_hist(2, 10, num=1000, bins=20, model=src)
        >>> y = get_energy_flux_hist(2, 10, num=1000, bins=20, model=src,
        ...                          id=1, otherids=(2, 3, 4))

        """
        if recalc:
            self._prepare_energy_flux_plot(self._energyfluxplot, lo, hi, id=id,
                                           num=num, bins=bins, correlated=correlated,
                                           scales=scales, model=model,
                                           otherids=otherids, clip=clip,
                                           numcores=numcores, bkg_id=bkg_id)
        return self._energyfluxplot

    def get_photon_flux_hist(self, lo=None, hi=None, id=None, num=7500, bins=75,
                             correlated=False, numcores=None, bkg_id=None,
                             scales=None, model=None, otherids=(), recalc=True,
                             clip='hard'):
        """Return the data displayed by plot_photon_flux.

        The get_photon_flux_hist() function calculates a histogram of
        simulated photon flux values representing the photon flux probability
        distribution for a model component, accounting for the errors on the
        model parameters.

        .. versionchanged:: 4.12.2
           The scales parameter is no longer ignored when set and the
           model and otherids parameters have been added.

        Parameters
        ----------
        lo : number, optional
           The lower limit to use when summing up the signal. If not
           given then the lower value of the data grid is used.
        hi : optional
           The upper limit to use when summing up the signal. If not
           given then the upper value of the data grid is used.
        id : int or string, optional
           The identifier of the data set to use. If `None`, the
           default value, then all datasets with associated models are
           used to calculate the errors and the model evaluation is
           done using the default dataset.
        num : int, optional
           The number of samples to create. The default is 7500.
        bins : int, optional
           The number of bins to use for the histogram.
        correlated : bool, optional
           If ``True`` (the default is ``False``) then ``scales`` is the
           full covariance matrix, otherwise it is just a 1D array
           containing the variances of the parameters (the diagonal
           elements of the covariance matrix).
        numcores : optional
           The number of CPU cores to use. The default is to use all
           the cores on the machine.
        bkg_id : int or string, optional
           The identifier of the background component to use. This
           should only be set when the line to be measured is in the
           background model.
        scales : array, optional
           The scales used to define the normal distributions for the
           parameters. The size and shape of the array depends on the
           number of free parameters in the fit (n) and the value of
           the `correlated` parameter. When the parameter is `True`,
           scales must be given the covariance matrix for the free
           parameters (a n by n matrix that matches the parameter
           ordering used by Sherpa). For un-correlated parameters
           the covariance matrix can be used, or a one-dimensional
           array of n elements can be used, giving the width (specified
           as the sigma value of a normal distribution) for each
           parameter (e.g. the square root of the diagonal elements
           of the covariance matrix). If the scales parameter is not
           given then the covariance matrix is evaluated for the
           current model and best-fit parameters.
        model : model, optional
           The model to integrate. If left as `None` then the source
           model for the dataset will be used. This can be used to
           calculate the unabsorbed flux, as shown in the examples.
           The model must be part of the source expression.
        otherids : sequence of integer and string ids, optional
           The list of other datasets that should be included when
           calculating the errors to draw values from.
        recalc : bool, optional
           If ``True``, the default, then re-calculate the values rather
           than use the values from the last time the function was
           run.
        clip : {'hard', 'soft', 'none'}, optional
            What clipping strategy should be applied to the sampled
            parameters. The default ('hard') is to fix values at their
            hard limits if they exceed them. A value of 'soft' uses
            the soft limits instead, and 'none' applies no
            clipping.

        Returns
        -------
        hist : a `sherpa.astro.plot.PhotonFluxHistogram` instance
           An object representing the data used to create the plot by
           `plot_photon_flux`.

        See Also
        --------
        get_energy_flux_hist : Return the data displayed by plot_energy_flux.
        plot_energy_flux : Display the energy flux distribution.
        plot_photon_flux : Display the photon flux distribution.
        sample_energy_flux : Return the energy flux distribution of a model.
        sample_flux : Return the flux distribution of a model.
        sample_photon_flux : Return the photon flux distribution of a model.

        Examples
        --------

        Get the photon flux distribution for the range 0.5 to 7 for
        the default data set:

        >>> phist = get_photon_flux_hist(0.5, 7, num=1000)
        >>> print(phist)

        Compare the 0.5 to 2 photon flux distribution from the "core"
        data set to the values from the "jet" data set:

        >>> phist1 = get_photon_flux_hist(0.5, 2, id='jet', num=1000)
        >>> phist2 = get_photon_flux_hist(0.5, 2, id='core', num=1000)

        Compare the flux distribution for the full source expression
        (aflux) to that for just the pl component (uflux); this can be
        useful to calculate the unabsorbed flux distribution if the
        full source model contains an absorption component:

        >>> aflux = get_photon_flux_hist(0.5, 2, num=1000, bins=20)
        >>> uflux = get_photon_flux_hist(0.5, 2, model=pl, num=1000, bins=20)

        When there are multiple datasets loaded,
        `get_photon_flux_hist` uses all datasets to evaluate the
        errors when the `id` parameter is left at its default value of
        `None`. The `otherids` parameter is used, along with `id`, to
        specify exactly what datasets are used:

        >>> x = get_photon_flux_hist(2, 10, num=1000, bins=20, model=src)
        >>> y = get_photon_flux_hist(2, 10, num=1000, bins=20, model=src,
        ...                          id=1, otherids=(2, 3, 4))

        """
        if recalc:
            self._prepare_photon_flux_plot(self._photonfluxplot, lo, hi, id=id,
                                           num=num, bins=bins, correlated=correlated,
                                           scales=scales, model=model,
                                           otherids=otherids, clip=clip,
                                           numcores=numcores, bkg_id=bkg_id)
        return self._photonfluxplot

    def plot_arf(self, id=None, resp_id=None, replot=False, overplot=False,
                 clearwindow=True, **kwargs):
        """Plot the ARF associated with a data set.

        Display the effective area curve from the ARF
        component of a PHA data set.

        Parameters
        ----------
        id : int or str, optional
           The data set with an ARF. If not given then the default
           identifier is used, as returned by `get_default_id`.
        resp_id : int or str, optional
           Which ARF to use in the case that multiple ARFs are
           associated with a data set. The default is ``None``,
           which means the first one.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_data`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.

        See Also
        --------
        get_arf_plot : Return the data used by plot_arf.
        plot : Create one or more plot types.

        Examples
        --------

        Plot the ARF for the default data set:

        >>> plot_arf()

        Plot the ARF from data set 1 and overplot
        the ARF from data set 2:

        >>> plot_arf(1)
        >>> plot_arf(2, overplot=True)

        Plot the ARFs labelled "arf1" and "arf2" for the
        "src" data set:

        >>> plot_arf("src", "arf1")
        >>> plot_arf("src", "arf2", overplot=True)

        The following example requires that the Matplotlib backend
        is selected, since this determines what extra keywords
        `plot_arf` accepts. The ARFs from the default and data set
        2 are drawn together, but the second curve is drawn with
        a dashed line.

        >>> plot_arf(ylog=True)
        >>> plot_arf(2, overplot=True, linestyle='dashed')

        """

        plotobj = self.get_arf_plot(id, resp_id, recalc=not replot)
        self._plot(plotobj, overplot=overplot, clearwindow=clearwindow,
                   **kwargs)

    # DOC-NOTE: also in sherpa.utils, but without the lo/hi arguments
    def plot_source(self, id=None, lo=None, hi=None, replot=False,
                    overplot=False, clearwindow=True, **kwargs):
        """Plot the source expression for a data set.

        This function plots the source model for a data set. This does
        not include any instrument response (e.g. a convolution
        created by `set_psf` or ARF and RMF automatically created for
        a PHA data set).

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        lo : number, optional
           The low value to plot (only used for PHA data sets).
        hi : number, optional
           The high value to plot (only use for PHA data sets).
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_source`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        See Also
        --------
        get_source_plot : Return the data used by plot_source.
        get_default_id : Return the default data set identifier.
        plot : Create one or more plot types.
        plot_model : Plot the model for a data set.
        set_analysis : Set the units used when fitting and displaying spectral data.
        set_xlinear : New plots will display a linear X axis.
        set_xlog : New plots will display a logarithmically-scaled X axis.
        set_ylinear : New plots will display a linear Y axis.
        set_ylog : New plots will display a logarithmically-scaled Y axis.

        Examples
        --------

        Plot the unconvolved source model for the default data set:

        >>> plot_source()

        Overplot the source model for data set 2 on data set 1:

        >>> plot_source(1)
        >>> plot_source(2, overplot=True)

        Restrict the plot to values between 0.5 and 7 for the
        independent axis:

        >>> plot_source(lo=0.5, hi=7)

        For a PHA data set, the units on both the X and Y axes of the
        plot are controlled by the `set_analysis` command. In this
        case the Y axis will be in units of photons/s/cm^2 and the X
        axis in keV:

        >>> set_analysis('energy', factor=1)
        >>> plot_source()

        """

        d = self.get_data(id)
        if isinstance(d, sherpa.astro.data.DataPHA):
            # Note: lo/hi arguments mean we can not just rely on superclass
            plotobj = self.get_source_plot(id, lo=lo, hi=hi, recalc=not replot)
            self._plot(plotobj, overplot=overplot, clearwindow=clearwindow,
                       **kwargs)
            return

        super().plot_source(id=id, replot=replot, overplot=overplot,
                            clearwindow=clearwindow, **kwargs)

    # DOC-TODO: is orders the same as resp_id?
    def plot_order(self, id=None, orders=None, replot=False, overplot=False,
                   clearwindow=True, **kwargs):
        """Plot the model for a data set convolved by the given response.

        Some data sets - such as grating PHA data - can have multiple
        responses. The `plot_order` function acts like `plot_model`,
        in that it displays the model after passing through a
        response, but allows the user to select which response to use.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        orders : optional
           Which response to use. The argument can be a scalar or
           array, in which case multiple curves will be displayed.
           The default is to use all orders.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_model`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        See Also
        --------
        get_order_plot : Return the data used by plot_order.
        plot : Create one or more plot types.
        plot_model : Plot the model for a data set.

        Examples
        --------

        Display the source model convolved by the first response
        for the default data set:

        >>> plot_order(orders=1)

        Plot the source convolved through the first and second
        responses for the second data set (separate curves for
        each response):

        >>> plot_order(2, orders=[1, 2])

        Add the orders plot to a model plot:

        >>> plot_model()
        >>> plot_order(orders=[2, 3], overplot=True)

        """

        plotobj = self.get_order_plot(id, orders=orders, recalc=not replot)
        self._plot(plotobj, overplot=overplot, clearwindow=clearwindow,
                   **kwargs)

    def plot_bkg(self, id=None, bkg_id=None, replot=False, overplot=False,
                 clearwindow=True, **kwargs):
        """Plot the background values for a PHA data set.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_bkg`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.

        See Also
        --------
        get_bkg_plot : Return the data used by plot_bkg.
        get_default_id : Return the default data set identifier.
        plot : Create one or more plot types.
        set_analysis : Set the units used when fitting and displaying spectral data.
        set_xlinear : New plots will display a linear X axis.
        set_xlog : New plots will display a logarithmically-scaled X axis.
        set_ylinear : New plots will display a linear Y axis.
        set_ylog : New plots will display a logarithmically-scaled Y axis.

        Examples
        --------

        Plot the background from the default data set:

        >>> plot_bkg()

        Overplot the background from the 'jet' data set on the
        data. There is no scaling for differences in aperture or
        exposure time:

        >>> plot_data('jet')
        >>> plot_bkg('jet', overplot=True)

        Compare the first two background components of data set 1:

        >>> plot_bkg(1, 1)
        >>> plot_bkg(1, 2, overplot=True)

        """

        plotobj = self.get_bkg_plot(id, bkg_id, recalc=not replot)
        self._plot(plotobj, overplot=overplot, clearwindow=clearwindow,
                   **kwargs)

    def plot_bkg_model(self, id=None, bkg_id=None, replot=False,
                       overplot=False, clearwindow=True, **kwargs):
        """Plot the model for the background of a PHA data set.

        This function plots the model for the background of a PHA data
        set, which includes any instrument response (the
        ARF and RMF).

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_bkg_model`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_model_plot : Return the data used by plot_bkg_model.
        plot_bkg_source : Plot the model expression for the background of a PHA data set.
        set_bkg_model : Set the background model expression for a PHA data set.

        Examples
        --------

        >>> plot_bkg_model()

        >>> plot_bkg('jet')
        >>> plot_bkg_model('jet', bkg_id=1, overplot=True)
        >>> plot_bkg_model('jet', bkg_id=2, overplot=True)

        """

        plotobj = self.get_bkg_model_plot(id, bkg_id, recalc=not replot)
        self._plot(plotobj, overplot=overplot, clearwindow=clearwindow,
                   **kwargs)

    def plot_bkg_resid(self, id=None, bkg_id=None, replot=False,
                       overplot=False, clearwindow=True, **kwargs):
        """Plot the residual (data-model) values for the background of a PHA data set.

        Display the residuals for the background of a PHA data set
        when it is being fit, rather than subtracted from the source.

        .. versionchanged:: 4.12.0
           The Y axis is now always drawn using a linear scale.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_bkg_resid`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_resid_plot : Return the data used by plot_bkg_resid.
        plot_bkg_chisqr : Plot the chi-squared value for each point of the background of a PHA data set.
        plot_bkg_delchi : Plot the ratio of residuals to error for the background of a PHA data set.
        plot_bkg_ratio : Plot the ratio of data to model values for the background of a PHA data set.
        set_bkg_model : Set the background model expression for a PHA data set.

        Notes
        -----
        The ylog setting is ignored, and the Y axis is drawn using a
        linear scale.

        Examples
        --------

        >>> plot_bkg_resid()

        >>> plot_bkg('jet')
        >>> plot_bkg_resid('jet', bkg_id=1, overplot=True)
        >>> plot_bkg_resid('jet', bkg_id=2, overplot=True)

        """

        plotobj = self.get_bkg_resid_plot(id, bkg_id, recalc=not replot)
        self._plot(plotobj, overplot=overplot, clearwindow=clearwindow,
                   **kwargs)

    def plot_bkg_ratio(self, id=None, bkg_id=None, replot=False,
                       overplot=False, clearwindow=True, **kwargs):
        """Plot the ratio of data to model values for the background of a PHA data set.

        Display the ratio of data to model values for the background
        of a PHA data set when it is being fit, rather than subtracted
        from the source.

        .. versionchanged:: 4.12.0
           The Y axis is now always drawn using a linear scale.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_bkg_ratio`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_ratio_plot : Return the data used by plot_bkg_ratio.
        plot_bkg_chisqr : Plot the chi-squared value for each point of the background of a PHA data set.
        plot_bkg_delchi : Plot the ratio of residuals to error for the background of a PHA data set.
        plot_bkg_resid : Plot the residual (data-model) values for the background of a PHA data set.
        set_bkg_model : Set the background model expression for a PHA data set.

        Notes
        -----
        The ylog setting is ignored, and the Y axis is drawn using a
        linear scale.

        Examples
        --------

        >>> plot_bkg_ratio()

        >>> plot_bkg_ratio('jet', bkg_id=1)
        >>> plot_bkg_ratio('jet', bkg_id=2, overplot=True)

        """

        plotobj = self.get_bkg_ratio_plot(id, bkg_id, recalc=not replot)
        self._plot(plotobj, overplot=overplot, clearwindow=clearwindow,
                   **kwargs)

    def plot_bkg_delchi(self, id=None, bkg_id=None, replot=False,
                        overplot=False, clearwindow=True, **kwargs):
        """Plot the ratio of residuals to error for the background of a PHA data set.

        Display the ratio of the residuals (data-model) to the error
        values for the background of a PHA data set when it is being
        fit, rather than subtracted from the source.

        .. versionchanged:: 4.12.0
           The Y axis is now always drawn using a linear scale.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_bkg_ratio`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_delchi_plot : Return the data used by plot_bkg_delchi.
        plot_bkg_chisqr : Plot the chi-squared value for each point of the background of a PHA data set.
        plot_bkg_ratio : Plot the ratio of data to model values for the background of a PHA data set.
        plot_bkg_resid : Plot the residual (data-model) values for the background of a PHA data set.
        set_bkg_model : Set the background model expression for a PHA data set.

        Notes
        -----
        The ylog setting is ignored, and the Y axis is drawn using a
        linear scale.

        Examples
        --------

        >>> plot_bkg_delchi()

        >>> plot_bkg_delchi('jet', bkg_id=1)
        >>> plot_bkg_delchi('jet', bkg_id=2, overplot=True)

        """

        plotobj = self.get_bkg_delchi_plot(id, bkg_id, recalc=not replot)
        self._plot(plotobj, overplot=overplot, clearwindow=clearwindow,
                   **kwargs)

    def plot_bkg_chisqr(self, id=None, bkg_id=None, replot=False,
                        overplot=False, clearwindow=True, **kwargs):
        """Plot the chi-squared value for each point of the background of a PHA data set.

        Display the square of the residuals (data-model) divided by
        the error values for the background of a PHA data set when it
        is being fit, rather than subtracted from the source.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_bkg_chisqr`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_chisqr_plot : Return the data used by plot_bkg_chisqr.
        plot_bkg_delchi : Plot the ratio of residuals to error for the background of a PHA data set.
        plot_bkg_ratio : Plot the ratio of data to model values for the background of a PHA data set.
        plot_bkg_resid : Plot the residual (data-model) values for the background of a PHA data set.
        set_bkg_model : Set the background model expression for a PHA data set.

        Examples
        --------

        >>> plot_bkg_chisqr()

        >>> plot_bkg_chisqr('jet', bkg_id=1)
        >>> plot_bkg_chisqr('jet', bkg_id=2, overplot=True)

        """

        plotobj = self.get_bkg_chisqr_plot(id, bkg_id, recalc=not replot)
        self._plot(plotobj, overplot=overplot, clearwindow=clearwindow,
                   **kwargs)

    def plot_bkg_fit(self, id=None, bkg_id=None, replot=False,
                     overplot=False, clearwindow=True, **kwargs):
        """Plot the fit results (data, model) for the background of a PHA data set.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_bkg_fit`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_fit_plot : Return the data used by plot_bkg_fit.
        plot : Create one or more plot types.
        plot_bkg : Plot the background values for a PHA data set.
        plot_bkg_model : Plot the model for the background of a PHA data set.
        plot_bkg_fit_delchi : Plot the fit results, and the residuals, for the background of a PHA data set.
        plot_bkg_fit_ratio : Plot the fit results, and the data/model ratio, for the background of a PHA data set.
        plot_bkg_fit_resid : Plot the fit results, and the residuals, for the background of a PHA data set.
        plot_fit : Plot the fit results (data, model) for a data set.
        set_analysis : Set the units used when fitting and displaying spectral data.

        Examples
        --------

        Plot the background fit to the default data set:

        >>> plot_bkg_fit()

        """

        plotobj = self.get_bkg_fit_plot(id, bkg_id, recalc=not replot)
        self._plot(plotobj, overplot=overplot, clearwindow=clearwindow,
                   **kwargs)

    def plot_bkg_source(self, id=None, lo=None, hi=None, bkg_id=None,
                        replot=False, overplot=False, clearwindow=True,
                        **kwargs):
        """Plot the model expression for the background of a PHA data set.

        This function plots the model for the background of a PHA data
        set. It does not include the instrument response (the ARF and
        RMF).

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        lo : number, optional
           The low value to plot.
        hi : number, optional
           The high value to plot.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_bkg_model`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_source_plot : Return the data used by plot_bkg_source.
        plot_bkg_model : Plot the model for the background of a PHA data set.
        set_bkg_model : Set the background model expression for a PHA data set.

        Examples
        --------

        >>> plot_bkg_source()

        >>> plot_bkg_source('jet', bkg_id=1)
        >>> plot_bkg_source('jet', bkg_id=2, overplot=True)

        """

        plotobj = self.get_bkg_source_plot(id, bkg_id=bkg_id, lo=lo, hi=hi,
                                           recalc=not replot)
        self._plot(plotobj, overplot=overplot, clearwindow=clearwindow,
                   **kwargs)

    def plot_energy_flux(self, lo=None, hi=None, id=None, num=7500, bins=75,
                         correlated=False, numcores=None, bkg_id=None,
                         scales=None, model=None, otherids=(),
                         recalc=True, clip='hard',
                         overplot=False, clearwindow=True,
                         **kwargs):
        """Display the energy flux distribution.

        For each iteration, draw the parameter values of the model
        from a normal distribution, evaluate the model, and sum the
        model over the given range (the flux). Plot up the
        distribution of this flux. The units for the flux are as
        returned by `calc_energy_flux`. The `sample_energy_flux` and
        `get_energy_flux_hist` functions return the data used to
        create this plot.

        .. versionchanged:: 4.12.2
           The scales parameter is no longer ignored when set and the
           model and otherids parameters have been added. The clip
           argument has been added.

        Parameters
        ----------
        lo : number, optional
           The lower limit to use when summing up the signal. If not
           given then the lower value of the data grid is used.
        hi : optional
           The upper limit to use when summing up the signal. If not
           given then the upper value of the data grid is used.
        id : int or string, optional
           The identifier of the data set to use. If `None`, the
           default value, then all datasets with associated models are
           used to calculate the errors and the model evaluation is
           done using the default dataset.
        num : int, optional
           The number of samples to create. The default is 7500.
        bins : int, optional
           The number of bins to use for the histogram.
        correlated : bool, optional
           If ``True`` (the default is ``False``) then ``scales`` is the
           full covariance matrix, otherwise it is just a 1D array
           containing the variances of the parameters (the diagonal
           elements of the covariance matrix).
        numcores : optional
           The number of CPU cores to use. The default is to use all
           the cores on the machine.
        bkg_id : int or string, optional
           The identifier of the background component to use. This
           should only be set when the line to be measured is in the
           background model.
        scales : array, optional
           The scales used to define the normal distributions for the
           parameters. The size and shape of the array depends on the
           number of free parameters in the fit (n) and the value of
           the `correlated` parameter. When the parameter is `True`,
           scales must be given the covariance matrix for the free
           parameters (a n by n matrix that matches the parameter
           ordering used by Sherpa). For un-correlated parameters
           the covariance matrix can be used, or a one-dimensional
           array of n elements can be used, giving the width (specified
           as the sigma value of a normal distribution) for each
           parameter (e.g. the square root of the diagonal elements
           of the covariance matrix). If the scales parameter is not
           given then the covariance matrix is evaluated for the
           current model and best-fit parameters.
        model : model, optional
           The model to integrate. If left as `None` then the source
           model for the dataset will be used. This can be used to
           calculate the unabsorbed flux, as shown in the examples.
           The model must be part of the source expression.
        otherids : sequence of integer and string ids, optional
           The list of other datasets that should be included when
           calculating the errors to draw values from.
        recalc : bool, optional
           If ``True``, the default, then re-calculate the values rather
           than use the values from the last time the function was
           run.
        clip : {'hard', 'soft', 'none'}, optional
            What clipping strategy should be applied to the sampled
            parameters. The default ('hard') is to fix values at their
            hard limits if they exceed them. A value of 'soft' uses
            the soft limits instead, and 'none' applies no
            clipping.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        See Also
        --------
        calc_photon_flux : Integrate the unconvolved source model over a pass band.
        calc_energy_flux : Integrate the unconvolved source model over a pass band.
        covar : Estimate the confidence intervals using the confidence method.
        get_energy_flux_hist : Return the data displayed by plot_energy_flux.
        get_photon_flux_hist : Return the data displayed by plot_photon_flux.
        plot_cdf : Plot the cumulative density function of an array.
        plot_pdf : Plot the probability density function of an array.
        plot_photon_flux : Display the photon flux distribution.
        plot_trace : Create a trace plot of row number versus value.
        sample_energy_flux : Return the energy flux distribution of a model.
        sample_flux : Return the flux distribution of a model.
        sample_photon_flux : Return the photon flux distribution of a model.

        Examples
        --------

        Plot the energy flux distribution for the range 0.5 to 7 for
        the default data set:

        >>> plot_energy_flux(0.5, 7, num=1000)

        Overplot the 0.5 to 2 energy flux distribution from the "core"
        data set on top of the values from the "jet" data set:

        >>> plot_energy_flux(0.5, 2, id="jet", num=1000)
        >>> plot_energy_flux(0.5, 2, id="core", num=1000, overplot=True)

        Overplot the flux distribution for just the pl component (which
        must be part of the source expression) on top of the full model.
        If the full model was xsphabs.gal * powlaw1d.pl then this will
        compare the unabsorbed to absorbed flux distributions:

        >>> plot_energy_flux(0.5, 2, num=1000, bins=20)
        >>> plot_energy_flux(0.5, 2, model=pl, num=1000, bins=20)

        If you have multiple datasets loaded, each with a model, then
        all datasets will be used to calculate the errors when the
        id parameter is not set. A single dataset can be used by
        specifying a dataset (in this example the overplot is just with
        dataset 1):

        >>> mdl = xsphabs.gal * xsapec.src
        >>> set_source(1, mdl)
        >>> set_source(2, mdl)
        ...
        >>> plot_energy_flux(0.5, 2, model=src num=1000, bins=20)
        >>> plot_energy_flux(0.5, 2, model=src num=1000, bins=20,
        ...                  id=1, overplot=True)

        If you have multiple datasets then you can use the otherids
        argument to specify exactly what set of data is used:

        >>> plot_energy_flux(0.5, 2, model=src num=1000, bins=20,
        ...                  id=1, otherids=(2, 3, 4))

        """
        efplot = self.get_energy_flux_hist(lo=lo, hi=hi, id=id, num=num, bins=bins,
                                           correlated=correlated, numcores=numcores,
                                           bkg_id=bkg_id, scales=scales, model=model,
                                           otherids=otherids, clip=clip, recalc=recalc)
        self._plot(efplot, overplot=overplot, clearwindow=clearwindow,
                   **kwargs)

    def plot_photon_flux(self, lo=None, hi=None, id=None, num=7500, bins=75,
                         correlated=False, numcores=None, bkg_id=None,
                         scales=None, model=None, otherids=(),
                         recalc=True, clip='hard',
                         overplot=False, clearwindow=True,
                         **kwargs):
        """Display the photon flux distribution.

        For each iteration, draw the parameter values of the model
        from a normal distribution, evaluate the model, and sum the
        model over the given range (the flux). Plot up the
        distribution of this flux. The units for the flux are as
        returned by `calc_photon_flux`. The `sample_photon_flux` and
        `get_photon_flux_hist` functions return the data used to
        create this plot.

        .. versionchanged:: 4.12.2
           The scales parameter is no longer ignored when set and the
           model and otherids parameters have been added. The clip
           argument has been added.

        Parameters
        ----------
        lo : number, optional
           The lower limit to use when summing up the signal. If not
           given then the lower value of the data grid is used.
        hi : optional
           The upper limit to use when summing up the signal. If not
           given then the upper value of the data grid is used.
        id : int or string, optional
           The identifier of the data set to use. If `None`, the
           default value, then all datasets with associated models are
           used to calculate the errors and the model evaluation is
           done using the default dataset.
        num : int, optional
           The number of samples to create. The default is 7500.
        bins : int, optional
           The number of bins to use for the histogram.
        correlated : bool, optional
           If ``True`` (the default is ``False``) then ``scales`` is the
           full covariance matrix, otherwise it is just a 1D array
           containing the variances of the parameters (the diagonal
           elements of the covariance matrix).
        numcores : optional
           The number of CPU cores to use. The default is to use all
           the cores on the machine.
        bkg_id : int or string, optional
           The identifier of the background component to use. This
           should only be set when the line to be measured is in the
           background model.
        scales : array, optional
           The scales used to define the normal distributions for the
           parameters. The size and shape of the array depends on the
           number of free parameters in the fit (n) and the value of
           the `correlated` parameter. When the parameter is `True`,
           scales must be given the covariance matrix for the free
           parameters (a n by n matrix that matches the parameter
           ordering used by Sherpa). For un-correlated parameters
           the covariance matrix can be used, or a one-dimensional
           array of n elements can be used, giving the width (specified
           as the sigma value of a normal distribution) for each
           parameter (e.g. the square root of the diagonal elements
           of the covariance matrix). If the scales parameter is not
           given then the covariance matrix is evaluated for the
           current model and best-fit parameters.
        model : model, optional
           The model to integrate. If left as `None` then the source
           model for the dataset will be used. This can be used to
           calculate the unabsorbed flux, as shown in the examples.
           The model must be part of the source expression.
        otherids : sequence of integer and string ids, optional
           The list of other datasets that should be included when
           calculating the errors to draw values from.
        recalc : bool, optional
           If ``True``, the default, then re-calculate the values rather
           than use the values from the last time the function was
           run.
        clip : {'hard', 'soft', 'none'}, optional
            What clipping strategy should be applied to the sampled
            parameters. The default ('hard') is to fix values at their
            hard limits if they exceed them. A value of 'soft' uses
            the soft limits instead, and 'none' applies no
            clipping.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        See Also
        --------
        calc_photon_flux : Integrate the unconvolved source model over a pass band.
        calc_energy_flux : Integrate the unconvolved source model over a pass band.
        covar : Estimate the confidence intervals using the confidence method.
        get_energy_flux_hist : Return the data displayed by plot_energy_flux.
        get_photon_flux_hist : Return the data displayed by plot_photon_flux.
        plot_cdf : Plot the cumulative density function of an array.
        plot_pdf : Plot the probability density function of an array.
        plot_energy_flux : Display the energy flux distribution.
        plot_trace : Create a trace plot of row number versus value.
        sample_energy_flux : Return the energy flux distribution of a model.
        sample_flux : Return the flux distribution of a model.
        sample_photon_flux : Return the photon flux distribution of a model.

        Examples
        --------

        Plot the photon flux distribution for the range 0.5 to 7 for
        the default data set:

        >>> plot_photon_flux(0.5, 7, num=1000)

        Overplot the 0.5 to 2 photon flux distribution from the "core"
        data set on top of the values from the "jet" data set:

        >>> plot_photon_flux(0.5, 2, id="jet", num=1000)
        >>> plot_photon_flux(0.5, 2, id="core", num=1000, overplot=True)

        Overplot the flux distribution for just the pl component (which
        must be part of the source expression) on top of the full model.
        If the full model was xsphabs.gal * powlaw1d.pl then this will
        compare the unabsorbed to absorbed flux distributions:

        >>> plot_photon_flux(0.5, 2, num=1000, bins=20)
        >>> plot_photon_flux(0.5, 2, model=pl, num=1000, bins=20)

        If you have multiple datasets loaded, each with a model, then
        all datasets will be used to calculate the errors when the
        id parameter is not set. A single dataset can be used by
        specifying a dataset (in this example the overplot is just with
        dataset 1):

        >>> mdl = xsphabs.gal * xsapec.src
        >>> set_source(1, mdl)
        >>> set_source(2, mdl)
        ...
        >>> plot_photon_flux(0.5, 2, model=src num=1000, bins=20)
        >>> plot_photon_flux(0.5, 2, model=src num=1000, bins=20,
        ...                  id=1, overplot=True)

        If you have multiple datasets then you can use the otherids
        argument to specify exactly what set of data is used:

        >>> plot_photon_flux(0.5, 2, model=src num=1000, bins=20,
        ...                  id=1, otherids=(2, 3, 4))

        """
        pfplot = self.get_photon_flux_hist(lo=lo, hi=hi, id=id, num=num, bins=bins,
                                           correlated=correlated, numcores=numcores,
                                           bkg_id=bkg_id, scales=scales, model=model,
                                           otherids=otherids, clip=clip, recalc=recalc)
        self._plot(pfplot, overplot=overplot, clearwindow=clearwindow,
                   **kwargs)

    def _bkg_jointplot2(self, plot1, plot2, overplot=False,
                        clearwindow=True, **kwargs):
        """Create a joint plot for bkg, vertically aligned, fit data on the top.

        Parameters
        ----------
        plot1 : sherpa.plot.Plot instance
           The plot to appear in the top panel.
        plot2 : sherpa.plot.Plot instance
           The plot to appear in the bottom panel.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        """

        self._jointplot.reset()

        try:
            sherpa.plot.begin()
            self._jointplot.plottop(plot1, overplot=overplot,
                                    clearwindow=clearwindow, **kwargs)

            # Unlike the plot version we can assume we are dealing
            # with histogram plots here.
            #
            oldval = plot2.plot_prefs['xlog']
            dprefs = plot1.dataplot.histo_prefs
            mprefs = plot1.modelplot.histo_prefs

            if dprefs['xlog'] or mprefs['xlog']:
                plot2.plot_prefs['xlog'] = True

            self._jointplot.plotbot(plot2, overplot=overplot, **kwargs)

            plot2.plot_prefs['xlog'] = oldval
        except:
            sherpa.plot.exceptions()
            raise
        else:
            sherpa.plot.end()

    def plot_bkg_fit_ratio(self, id=None, bkg_id=None, replot=False,
                           overplot=False, clearwindow=True, **kwargs):
        """Plot the fit results, and the data/model ratio, for the background of
        a PHA data set.

        This creates two plots - the first from `plot_bkg_fit` and the
        second from `plot_bkg_ratio` - for a data set.

        .. versionchanged:: 4.12.2
           The ``overplot`` option now works.

        .. versionadded:: 4.12.0

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_bkg_fit_ratio`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_fit_plot : Return the data used by plot_bkg_fit.
        get_bkg_resid_plot : Return the data used by plot_bkg_resid.
        plot : Create one or more plot types.
        plot_bkg : Plot the background values for a PHA data set.
        plot_bkg_model : Plot the model for the background of a PHA data set.
        plot_bkg_fit : Plot the fit results (data, model) for the background of a PHA data set.
        plot_bkg_fit_delchi : Plot the fit results, and the residuals, for the background of a PHA data set.
        plot_bkg_fit_resid : Plot the fit results, and the residuals, for the background of a PHA data set.
        plot_fit : Plot the fit results (data, model) for a data set.
        plot_fit_resid : Plot the fit results, and the residuals, for a data set.
        set_analysis : Set the units used when fitting and displaying spectral data.

        Notes
        -----
        For the residual plot, the ylog setting is ignored, and the Y axis
        is drawn using a linear scale.

        Examples
        --------

        Plot the background fit and the ratio of the background to
        this fit for the default data set:

        >>> plot_bkg_fit_ratio()

        """

        plot1obj = self.get_bkg_fit_plot(id, bkg_id, recalc=not replot)
        plot2obj = self.get_bkg_ratio_plot(id, bkg_id, recalc=not replot)
        self._bkg_jointplot2(plot1obj, plot2obj,
                             overplot=overplot, clearwindow=clearwindow,
                             **kwargs)

    def plot_bkg_fit_resid(self, id=None, bkg_id=None, replot=False,
                           overplot=False, clearwindow=True, **kwargs):
        """Plot the fit results, and the residuals, for the background of
        a PHA data set.

        This creates two plots - the first from `plot_bkg_fit` and the
        second from `plot_bkg_resid` - for a data set.

        .. versionchanged:: 4.12.2
           The ``overplot`` option now works.

        .. versionchanged:: 4.12.0
           The Y axis of the residual plot is now always drawn using a
           linear scale.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_bkg_fit_resid`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_fit_plot : Return the data used by plot_bkg_fit.
        get_bkg_resid_plot : Return the data used by plot_bkg_resid.
        plot : Create one or more plot types.
        plot_bkg : Plot the background values for a PHA data set.
        plot_bkg_model : Plot the model for the background of a PHA data set.
        plot_bkg_fit : Plot the fit results (data, model) for the background of a PHA data set.
        plot_bkg_fit_ratio : Plot the fit results, and the data/model ratio, for the background of a PHA data set.
        plot_bkg_fit_delchi : Plot the fit results, and the residuals, for the background of a PHA data set.
        plot_fit : Plot the fit results (data, model) for a data set.
        plot_fit_resid : Plot the fit results, and the residuals, for a data set.
        set_analysis : Set the units used when fitting and displaying spectral data.

        Notes
        -----
        For the residual plot, the ylog setting is ignored, and the Y axis
        is drawn using a linear scale.

        Examples
        --------

        Plot the background fit and residuals to the default data set:

        >>> plot_bkg_fit_resid()

        """

        plot1obj = self.get_bkg_fit_plot(id, bkg_id, recalc=not replot)
        plot2obj = self.get_bkg_resid_plot(id, bkg_id, recalc=not replot)
        self._bkg_jointplot2(plot1obj, plot2obj,
                             overplot=overplot, clearwindow=clearwindow,
                             **kwargs)

    def plot_bkg_fit_delchi(self, id=None, bkg_id=None, replot=False,
                            overplot=False, clearwindow=True, **kwargs):
        """Plot the fit results, and the residuals, for the background of
        a PHA data set.

        This creates two plots - the first from `plot_bkg_fit` and the
        second from `plot_bkg_delchi` - for a data set.

        .. versionchanged:: 4.12.2
           The ``overplot`` option now works.

        .. versionchanged:: 4.12.0
           The Y axis of the residual plot is now always drawn using a
           linear scale.

        Parameters
        ----------
        id : int or str, optional
           The data set that provides the data. If not given then the
           default identifier is used, as returned by `get_default_id`.
        bkg_id : int or str, optional
           Identify the background component to use, if there are
           multiple ones associated with the data set.
        replot : bool, optional
           Set to ``True`` to use the values calculated by the last
           call to `plot_bkg_fit_delchi`. The default is ``False``.
        overplot : bool, optional
           If ``True`` then add the data to an existing plot, otherwise
           create a new plot. The default is ``False``.
        clearwindow : bool, optional
           Should the existing plot area be cleared before creating this
           new plot (e.g. for multi-panel plots)?

        Raises
        ------
        sherpa.utils.err.ArgumentErr
           If the data set does not contain PHA data.
        sherpa.utils.err.IdentifierErr
           If the ``bkg_id`` parameter is invalid.
        sherpa.utils.err.ModelErr
           If no model expression has been created for the background
           data.

        See Also
        --------
        get_bkg_fit_plot : Return the data used by plot_bkg_fit.
        get_bkg_delchi_plot : Return the data used by plot_bkg_delchi.
        plot : Create one or more plot types.
        plot_bkg : Plot the background values for a PHA data set.
        plot_bkg_model : Plot the model for the background of a PHA data set.
        plot_bkg_fit : Plot the fit results (data, model) for the background of a PHA data set.
        plot_bkg_fit_ratio : Plot the fit results, and the data/model ratio, for the background of a PHA data set.
        plot_bkg_fit_resid : Plot the fit results, and the residuals, for the background of a PHA data set.
        plot_fit : Plot the fit results (data, model) for a data set.
        plot_fit_delchi : Plot the fit results, and the residuals, for a data set.
        set_analysis : Set the units used when fitting and displaying spectral data.

        Notes
        -----
        For the residual plot, the ylog setting is ignored, and the Y axis
        is drawn using a linear scale.

        Examples
        --------

        Plot the background fit and residuals (normalised by the
        error) to the default data set:

        >>> plot_bkg_fit_delchi()

        """

        plot1obj = self.get_bkg_fit_plot(id, bkg_id, recalc=not replot)
        plot2obj = self.get_bkg_delchi_plot(id, bkg_id, recalc=not replot)
        self._bkg_jointplot2(plot1obj, plot2obj,
                             overplot=overplot, clearwindow=clearwindow,
                             **kwargs)

    ###########################################################################
    # Analysis Functions
    ###########################################################################

    def resample_data(self, id=None, niter=1000, seed=None):
        """Resample data with asymmetric error bars.

        The function performs a parametric bootstrap assuming a skewed
        normal distribution centered on the observed data point with
        the variance given by the low and high measurement errors. The
        function simulates niter realizations of the data and fits
        each realization with the assumed model to obtain the best fit
        parameters. The function returns the best fit parameters for
        each realization, and displays the average and standard
        deviation for each parameter.

        .. versionadded:: 4.12.2
           The samples and statistic keys were added to the return
           value and the parameter values are returned as NumPy arrays
           rather than as lists.

        Parameters
        ----------
        id : int or str, optional
           The identifier of the data set to use.
        niter : int, optional
           The number of iterations to use. The default is ``1000``.
        seed : int, optional
           The seed for the random number generator. The default is ```None```.

        Returns
        -------
        sampled : dict
           The keys are statistic, which contains the best-fit
           statistic value for each iteration, samples, which contains
           the resampled data used in the fits as a niter by ndata
           array, and the free parameters in the fit, containing a
           NumPy array containing the fit parameter for each iteration
           (of size niter).

        See Also
        --------
        load_ascii_with_errors : Load an ASCII file with asymmetric errors as a data set.

        Examples
        --------
        Account for of asymmetric errors when calculating parameter
        uncertainties:

        >>> load_ascii_with_errors(1, 'test.dat')
        >>> set_model(polynom1d.p0)
        >>> thaw(p0.c1)
        >>> fit()
        Dataset               = 1
        Method                = levmar
        Statistic             = leastsq
        Initial fit statistic = 4322.56
        Final fit statistic   = 247.768 at function evaluation 6
        Data points           = 61
        Degrees of freedom    = 59
        Change in statistic   = 4074.79
        p0.c0          3.2661       +/- 0.193009
        p0.c1          2162.19      +/- 65.8445
        >>> result = resample_data(1, niter=10)
        p0.c0 : avg = 4.159973865314249 , std = 1.0575403309799554
        p0.c1 : avg = 1943.5489865678633 , std = 268.64478808013547
        >>> print(result['p0.c0'])
        [5.856479033432613, 3.8252624107243465, ... 2.8704270612985345]
        >>> print(result['p0.c1'])
        [1510.049972062868, 1995.4742750432902, ... 2235.9753113309894]

        Display the PDF of the parameter values of the p0.c0 component
        from a run with 5000 iterations:

        >>> sample = resample_data(1, 5000)
        p0.c0 : avg = 3.966543284267264 , std = 0.9104639711036427
        p0.c1 : avg = 1988.8417667057342 , std = 220.21903089622705
        >>> plot_pdf(sample['p0.c0'], bins=40)

        The samples used for the analysis are returned as the samples
        key (as a 2D NumPy array of size number of iterations by
        number of data points), that can be used if further analysis
        is desired. In this case, the distribution of the first bin
        is shown as a CDF:

        >>> sample = resample_data(1, 5000)
        >>> samples = sample['samples']
        >>> plot_cdf(samples[:, 0])

        """
        data = self.get_data(id)
        model = self.get_model(id)
        resampledata = sherpa.sim.ReSampleData(data, model)
        return resampledata(niter=niter, seed=seed)

    def sample_photon_flux(self, lo=None, hi=None, id=None, num=1,
                           scales=None, correlated=False,
                           numcores=None, bkg_id=None, model=None,
                           otherids=(), clip='hard'):
        """Return the photon flux distribution of a model.

        For each iteration, draw the parameter values of the model
        from a normal distribution, evaluate the model, and sum the
        model over the given range (the flux). The return array
        contains the flux and parameter values for each iteration.
        The units for the flux are as returned by `calc_photon_flux`.

        .. versionchanged:: 4.12.2
           The model, otherids, and clip parameters were added and
           the return value has an extra column.

        Parameters
        ----------
        lo : number, optional
           The lower limit to use when summing up the signal. If not
           given then the lower value of the data grid is used.
        hi : optional
           The upper limit to use when summing up the signal. If not
           given then the upper value of the data grid is used.
        id : int or string, optional
           The identifier of the data set to use. If `None`, the
           default value, then all datasets with associated models are
           used to calculate the errors and the model evaluation is
           done using the default dataset.
        num : int, optional
           The number of samples to create. The default is 1.
        scales : array, optional
           The scales used to define the normal distributions for the
           parameters. The size and shape of the array depends on the
           number of free parameters in the fit (n) and the value of
           the `correlated` parameter. When the parameter is `True`,
           scales must be given the covariance matrix for the free
           parameters (a n by n matrix that matches the parameter
           ordering used by Sherpa). For un-correlated parameters
           the covariance matrix can be used, or a one-dimensional
           array of n elements can be used, giving the width (specified
           as the sigma value of a normal distribution) for each
           parameter (e.g. the square root of the diagonal elements
           of the covariance matrix). If the scales parameter is not
           given then the covariance matrix is evaluated for the
           current model and best-fit parameters.
        correlated : bool, optional
           Should the correlation between the parameters be included
           when sampling the parameters? If not, then each parameter
           is sampled from independent distributions. In both cases
           a normal distribution is used.
        numcores : optional
           The number of CPU cores to use. The default is to use all
           the cores on the machine.
        bkg_id : int or string, optional
           The identifier of the background component to use. This
           should only be set when the line to be measured is in the
           background model.
        model : model, optional
           The model to integrate. If left as `None` then the source
           model for the dataset will be used. This can be used to
           calculate the unabsorbed flux, as shown in the examples.
           The model must be part of the source expression.
        otherids : sequence of integer and string ids, optional
           The list of other datasets that should be included when
           calculating the errors to draw values from.
        clip : {'hard', 'soft', 'none'}, optional
            What clipping strategy should be applied to the sampled
            parameters. The default ('hard') is to fix values at their
            hard limits if they exceed them. A value of 'soft' uses
            the soft limits instead, and 'none' applies no
            clipping. The last column in the returned arrays indicates
            if the row had any clipped parameters (even when clip is
            set to 'none').

        Returns
        -------
        vals
           The return array has the shape ``(num, N+2)``, where ``N``
           is the number of free parameters in the fit and num is the
           `num` parameter.  The rows of this array contain the flux
           value, as calculated by `calc_photon_flux`, followed by the
           values of the thawed parameters used for that iteration,
           and then a flag column indicating if the parameters were
           clipped (1) or not (0).  The order of the parameters
           matches the data returned by `get_fit_results`.

        See Also
        --------
        calc_photon_flux : Integrate the unconvolved source model over a pass band.
        calc_energy_flux : Integrate the unconvolved source model over a pass band.
        covar : Estimate the confidence intervals using the confidence method.
        plot_cdf : Plot the cumulative density function of an array.
        plot_pdf : Plot the probability density function of an array.
        plot_energy_flux : Display the energy flux distribution.
        plot_photon_flux : Display the photon flux distribution.
        plot_trace : Create a trace plot of row number versus value.
        sample_energy_flux : Return the energy flux distribution of a model.
        sample_flux : Return the flux distribution of a model.

        Notes
        -----
        There are two ways to use this function to calculate fluxes
        from multiple sources. The first is to leave the `id` argument
        as `None`, in which case all available datasets will be used.
        Alternatively, the `id` and `otherids` arguments can be set to
        list the exact datasets to use, such as `id=1,
        otherids=(2,3,4)`.

        The returned value contains all free parameters in the fit,
        even if they are not included in the model argument (e.g.
        when calculating an unabsorbed flux).

        Examples
        --------

        Calculate the photon flux distribution for the range 0.5 to 7,
        and plot up the resulting flux distribution (as a cumulative
        distribution):

        >>> vals = sample_photon_flux(0.5, 7, num=1000)
        >>> plot_cdf(vals[:, 0], name='flux')

        Repeat the above, but allowing the parameters to be
        correlated, and then calculate the 5, 50, and 95 percent
        quantiles of the photon flux distribution:

        >>> cvals = sample_photon_flux(0.5, 7, num=1000, correlated=True)
        >>> np.percentile(cvals[:, 0], [5, 50, 95])

        The photon flux of a component (or sub-set of components) can be
        calculated using the model argument. For the following case,
        an absorbed power-law was used to fit the data -
        `xsphabs.gal * powerlaw.pl` - and then the flux of just the
        power-law component is calculated. Note that the returned
        array has columns 'flux', 'gal.nh', 'pl.gamma', and 'pl.ampl'
        (that is flux and then the free parameters in the full model).

        >>> vals = sample_photon_flux(0.5, 7, model=pl, num=1000, correlated=True)

        Calculate the 2-10 keV flux for the pl model using a joint fit
        to the datasets 1, 2, 3, and 4:

        >>> vals = sample_photon_flux(2, 10, model=pl, id=1, otherids=(2,3,4),
        ...                           num=1000)

        Use the given parameter errors for sampling the parameter distribution.
        The fit must have three free parameters, and each parameter is
        sampled independently (in this case parerrs gives the sigma
        values for each parameter):

        >>> parerrs = [0.25, 1.22, 1.04e-4]
        >>> vals = sample_photon_flux(2, 10, num=5000, scales=parerrs)

        In this case the parameter errors are taken from the covariance
        analysis, using the `parmaxes` field since these are positive.

        >>> covar()
        >>> parerrs = get_covar_results().parmaxes
        >>> vals = sample_photon_flux(0.5, 2, num=1000, scales=parerrs)

        Run covariance to estimate the parameter errors and then
        extract the covariance matrix from the results (as the `cmat`
        variable).  This matrix is then used to define the parameter
        widths - including correlated terms - in the flux sampling,
        after being increased by ten percent. This is used to
        calculate both the absorbed (`vals1`) and unabsorbed (`vals2`)
        fluxes. Both arrays have columns: flux, gal.nh, pl.gamma, and
        pl.ampl.

        >>> set_source(xsphabs.gal * powlaw1d.pl)
        >>> fit()
        >>> covar()
        >>> cmat = get_covar_results().extra_output
        >>> vals1 = sample_photon_flux(2, 10, num=5000, correlated=True,
        ...                            scales=1.1 * cmat)
        >>> vals2 = sample_photon_flux(2, 10, num=5000, correlated=True,
        ...                            model=pl, scales=1.1 * cmat)

        Calculate the flux and error distribution using fits
        to all datasets:

        >>> set_source(xsphabs.gal * xsapec.clus)
        >>> set_source(2, gal * clus)
        >>> set_source(3, gal * clus)
        ... fit the data
        >>> vals = sample_photon_flux(0.5, 10, model=clus, num=10000)

        Calculate the flux and error distribution using fits
        to an explicit set of datasets (in this case datasets
        1 and 2):

        >>> vals = sample_photon_flux(0.5, 10, id=1, otherids=[2],
        ...                           model=clus, num=10000)

        Generate two sets of parameter values, where the parameter
        values in v1 are generated from a random distribution and then
        clipped to the hard limits of the parameters, and the values
        in v2 use the soft limits of the parameters. The last column
        in both v1 and v2 indicates whether the row had any clipped
        parameters. The flux1_filt and flux2_filt arrays indicate the
        photon-flux distribution after it has been filtered to remove
        any row with clipped parameters:

        >>> v1 = sample_photon_flux(0.5, 2, num=1000)
        >>> v2 = sample_photon_flux(0.5, 2, num=1000, clip='soft')
        >>> flux1 = v1[:, 0]
        >>> flux2 = v2[:, 0]
        >>> flux1_filt = flux1[v1[:, -1] == 0]
        >>> flux2_filt = flux2[v2[:, -1] == 0]

        """
        _, fit = self._get_fit(id, otherids=otherids)

        if bkg_id is None:
            data = self.get_data(id)
            if model is None:
                model = self.get_source(id)
        else:
            data = self.get_bkg(id, bkg_id)
            if model is None:
                model = self.get_bkg_source(id, bkg_id)

        correlated = sherpa.utils.bool_cast(correlated)

        return sherpa.astro.flux.sample_flux(fit, data, model,
                                             method=sherpa.astro.utils.calc_photon_flux,
                                             correlated=correlated,
                                             num=num, lo=lo, hi=hi,
                                             numcores=numcores,
                                             samples=scales, clip=clip)

    def sample_energy_flux(self, lo=None, hi=None, id=None, num=1,
                           scales=None, correlated=False,
                           numcores=None, bkg_id=None, model=None,
                           otherids=(), clip='hard'):
        """Return the energy flux distribution of a model.

        For each iteration, draw the parameter values of the model
        from a normal distribution, evaluate the model, and sum the
        model over the given range (the flux). The return array
        contains the flux and parameter values for each iteration.
        The units for the flux are as returned by `calc_energy_flux`.

        .. versionchanged:: 4.12.2
           The model, otherids, and clip parameters were added and
           the return value has an extra column.

        Parameters
        ----------
        lo : number, optional
           The lower limit to use when summing up the signal. If not
           given then the lower value of the data grid is used.
        hi : optional
           The upper limit to use when summing up the signal. If not
           given then the upper value of the data grid is used.
        id : int or string, optional
           The identifier of the data set to use. If `None`, the
           default value, then all datasets with associated models are
           used to calculate the errors and the model evaluation is
           done using the default dataset.
        num : int, optional
           The number of samples to create. The default is 1.
        scales : array, optional
           The scales used to define the normal distributions for the
           parameters. The size and shape of the array depends on the
           number of free parameters in the fit (n) and the value of
           the `correlated` parameter. When the parameter is `True`,
           scales must be given the covariance matrix for the free
           parameters (a n by n matrix that matches the parameter
           ordering used by Sherpa). For un-correlated parameters
           the covariance matrix can be used, or a one-dimensional
           array of n elements can be used, giving the width (specified
           as the sigma value of a normal distribution) for each
           parameter (e.g. the square root of the diagonal elements
           of the covariance matrix). If the scales parameter is not
           given then the covariance matrix is evaluated for the
           current model and best-fit parameters.
        correlated : bool, optional
           Should the correlation between the parameters be included
           when sampling the parameters? If not, then each parameter
           is sampled from independent distributions. In both cases
           a normal distribution is used.
        numcores : optional
           The number of CPU cores to use. The default is to use all
           the cores on the machine.
        bkg_id : int or string, optional
           The identifier of the background component to use. This
           should only be set when the line to be measured is in the
           background model.
        model : model, optional
           The model to integrate. If left as `None` then the source
           model for the dataset will be used. This can be used to
           calculate the unabsorbed flux, as shown in the examples.
           The model must be part of the source expression.
        otherids : sequence of integer and string ids, optional
           The list of other datasets that should be included when
           calculating the errors to draw values from.
        clip : {'hard', 'soft', 'none'}, optional
            What clipping strategy should be applied to the sampled
            parameters. The default ('hard') is to fix values at their
            hard limits if they exceed them. A value of 'soft' uses
            the soft limits instead, and 'none' applies no
            clipping. The last column in the returned arrays indicates
            if the row had any clipped parameters (even when clip is
            set to 'none').

        Returns
        -------
        vals
           The return array has the shape ``(num, N+2)``, where ``N``
           is the number of free parameters in the fit and num is the
           `num` parameter.  The rows of this array contain the flux
           value, as calculated by `calc_energy_flux`, followed by the
           values of the thawed parameters used for that iteration,
           and then a flag column indicating if the parameters were
           clipped (1) or not (0).  The order of the parameters
           matches the data returned by `get_fit_results`.

        See Also
        --------
        calc_photon_flux : Integrate the unconvolved source model over a pass band.
        calc_energy_flux : Integrate the unconvolved source model over a pass band.
        covar : Estimate the confidence intervals using the confidence method.
        plot_cdf : Plot the cumulative density function of an array.
        plot_pdf : Plot the probability density function of an array.
        plot_energy_flux : Display the energy flux distribution.
        plot_photon_flux : Display the photon flux distribution.
        plot_trace : Create a trace plot of row number versus value.
        sample_photon_flux : Return the flux distribution of a model.
        sample_flux : Return the flux distribution of a model.

        Notes
        -----
        There are two ways to use this function to calculate fluxes
        from multiple sources. The first is to leave the `id` argument
        as `None`, in which case all available datasets will be used.
        Alternatively, the `id` and `otherids` arguments can be set to
        list the exact datasets to use, such as `id=1,
        otherids=(2,3,4)`.

        The returned value contains all free parameters in the fit,
        even if they are not included in the model argument (e.g.
        when calculating an unabsorbed flux).

        Examples
        --------

        Calculate the energy flux distribution for the range 0.5 to 7,
        and plot up the resulting flux distribution (as a cumulative
        distribution):

        >>> vals = sample_energy_flux(0.5, 7, num=1000)
        >>> plot_cdf(vals[:, 0], name='flux')

        Repeat the above, but allowing the parameters to be
        correlated, and then calculate the 5, 50, and 95 percent
        quantiles of the energy flux distribution:

        >>> cvals = sample_energy_flux(0.5, 7, num=1000, correlated=True)
        >>> np.percentile(cvals[:, 0], [5, 50, 95])

        The energy flux of a component (or sub-set of components) can be
        calculated using the model argument. For the following case,
        an absorbed power-law was used to fit the data -
        `xsphabs.gal * powerlaw.pl` - and then the flux of just the
        power-law component is calculated. Note that the returned
        array has columns 'flux', 'gal.nh', 'pl.gamma', and 'pl.ampl'
        (that is flux and then the free parameters in the full model).

        >>> vals = sample_energy_flux(0.5, 7, model=pl, num=1000, correlated=True)

        Calculate the 2-10 keV flux for the pl model using a joint fit
        to the datasets 1, 2, 3, and 4:

        >>> vals = sample_energy_flux(2, 10, model=pl, id=1, otherids=(2,3,4),
        ...                           num=1000)

        Use the given parameter errors for sampling the parameter distribution.
        The fit must have three free parameters, and each parameter is
        sampled independently (in this case parerrs gives the sigma
        values for each parameter):

        >>> parerrs = [0.25, 1.22, 1.04e-4]
        >>> vals = sample_energy_flux(2, 10, num=5000, scales=parerrs)

        In this case the parameter errors are taken from the covariance
        analysis, using the `parmaxes` field since these are positive.

        >>> covar()
        >>> parerrs = get_covar_results().parmaxes
        >>> vals = sample_energy_flux(0.5, 2, num=1000, scales=parerrs)

        Run covariance to estimate the parameter errors and then
        extract the covariance matrix from the results (as the `cmat`
        variable).  This matrix is then used to define the parameter
        widths - including correlated terms - in the flux sampling,
        after being increased by ten percent. This is used to
        calculate both the absorbed (`vals1`) and unabsorbed (`vals2`)
        fluxes. Both arrays have columns: flux, gal.nh, pl.gamma, and
        pl.ampl.

        >>> set_source(xsphabs.gal * powlaw1d.pl)
        >>> fit()
        >>> covar()
        >>> cmat = get_covar_results().extra_output
        >>> vals1 = sample_energy_flux(2, 10, num=5000, correlated=True,
        ...                            scales=1.1 * cmat)
        >>> vals2 = sample_energy_flux(2, 10, num=5000, correlated=True,
        ...                            model=pl, scales=1.1 * cmat)

        Calculate the flux and error distribution using fits
        to all datasets:

        >>> set_source(xsphabs.gal * xsapec.clus)
        >>> set_source(2, gal * clus)
        >>> set_source(3, gal * clus)
        ... fit the data
        >>> vals = sample_energy_flux(0.5, 10, model=clus, num=10000)

        Calculate the flux and error distribution using fits
        to an explicit set of datasets (in this case datasets
        1 and 2):

        >>> vals = sample_energy_flux(0.5, 10, id=1, otherids=[2],
        ...                           model=clus, num=10000)

        Generate two sets of parameter values, where the parameter
        values in v1 are generated from a random distribution and then
        clipped to the hard limits of the parameters, and the values
        in v2 use the soft limits of the parameters. The last column
        in both v1 and v2 indicates whether the row had any clipped
        parameters. The flux1_filt and flux2_filt arrays indicate the
        energy-flux distribution after it has been filtered to remove
        any row with clipped parameters:

        >>> v1 = sample_energy_flux(0.5, 2, num=1000)
        >>> v2 = sample_energy_flux(0.5, 2, num=1000, clip='soft')
        >>> flux1 = v1[:, 0]
        >>> flux2 = v2[:, 0]
        >>> flux1_filt = flux1[v1[:, -1] == 0]
        >>> flux2_filt = flux2[v2[:, -1] == 0]

        """
        _, fit = self._get_fit(id, otherids=otherids)

        if bkg_id is None:
            data = self.get_data(id)
            if model is None:
                model = self.get_source(id)
        else:
            data = self.get_bkg(id, bkg_id)
            if model is None:
                model = self.get_bkg_source(id, bkg_id)

        correlated = sherpa.utils.bool_cast(correlated)

        return sherpa.astro.flux.sample_flux(fit, data, model,
                                             method=sherpa.astro.utils.calc_energy_flux,
                                             correlated=correlated,
                                             num=num, lo=lo, hi=hi,
                                             numcores=numcores,
                                             samples=scales, clip=clip)

    def sample_flux(self, modelcomponent=None, lo=None, hi=None, id=None,
                    num=1, scales=None, correlated=False,
                    numcores=None, bkg_id=None, Xrays=True, confidence=68):
        """Return the flux distribution of a model.

        For each iteration, draw the parameter values of the model
        from a normal distribution, filter out samples that lie
        outside the soft limits of the parameters, evaluate the model,
        and sum the model over the given range (the flux). Return the
        parameter values used, together with the median, upper, and
        lower quantiles of the flux distribution.

        .. versionchanged:: 4.13.1
           The `id` parameter is now used if set (previously the
           default dataset was always used). The screen output is now
           controlled by the Sherpa logging setup. The flux
           calculation no-longer excludes samples at the parameter
           soft limits, as this could cause an over-estimation of the
           flux when a parameter is only an upper limit. The statistic
           value is now returned for each row, even those that were
           excluded from the flux calculation. The last-but-one column
           of the returned `vals` array now records the rows that were
           excluded from the flux calculation.

        Parameters
        ----------
        modelcomponent : optional
           The model to use. It can be a single component or
           a combination. If not given, then the full source
           expression for the data set is used.
        lo : number, optional
           The lower limit to use when summing up the signal. If not
           given then the lower value of the data grid is used.
        hi : optional
           The upper limit to use when summing up the signal. If not
           given then the upper value of the data grid is used.
        id : int or string, optional
           The identifier of the data set to use. The default value
           (``None``) means that the default identifier, as returned by
           `get_default_id`, is used.
        num : int, optional
           The number of samples to create. The default is 1.
        scales : array, optional
           The scales used to define the normal distributions for the
           parameters. The form depends on the `correlated`
           parameter: when ``True``, the array should be a symmetric
           positive semi-definite (N, N) array, otherwise a 1D array
           of length N, where N is the number of free parameters.
        correlated : bool, optional
           If ``True`` (the default is ``False``) then `scales` is the
           full covariance matrix, otherwise it is just a 1D array
           containing the variances of the parameters (the diagonal
           elements of the covariance matrix).
        numcores : optional
           The number of CPU cores to use. The default is to use all
           the cores on the machine.
        bkg_id : int or string, optional
           The identifier of the background component to use. This
           should only be set when the line to be measured is in the
           background model.
        Xrays : bool, optional
           When ``True`` (the default), assume that the model has
           units of photon/cm^2/s, and use `calc_energy_flux`
           to convert to erg/cm^2/s. This should not be changed from
           the default value.
        confidence : number, optional
           The confidence level for the upper and lower values, as a
           percentage (0 to 100). The default is 68, so as to return
           the one-sigma range.

        Returns
        -------
        (fullflux, cptflux, vals)
           The fullflux and cptflux arrays contain the results for the
           full source model and the flux of the `modelcomponent`
           argument (they can be the same). They have three elements
           and give the median value, the value containing 100 -
           confidence/2 of the data, and the fraction containing
           confidence/2 of the flux distribution. For the default
           confidence argument of 68 this means the last two give the
           one-sigma upper and lower bounds. The vals array has a
           shape of ``(num+1, N+3)``, where ``N`` is the number of
           free parameters and num is the `num` parameter. The rows of
           this array contain the flux value for the iteration (for
           the full source model), the parameter values, a flag
           indicating whether any parameter in that row was clipped
           (and so was excluded from the flux calculation), and the
           statistic value for this set of parameters.

        See Also
        --------
        calc_photon_flux : Integrate the unconvolved source model over a pass band.
        calc_energy_flux : Integrate the unconvolved source model over a pass band.
        covar : Estimate the confidence intervals using the confidence method.
        plot_energy_flux : Display the energy flux distribution.
        plot_photon_flux : Display the photon flux distribution.
        sample_energy_flux : Return the energy flux distribution of a model.
        sample_photon_flux : Return the photon flux distribution of a model.

        Notes
        -----
        Setting the Xrays parameter to False is currently unsupported.

        The summary output displayed by this routine - giving the
        median and confidence ranges - is controlled by the standard
        Sherpa logging instance, and can be hidden by changing the
        logging to a level greater than "INFO" (e.g. with
        `sherpa.utils.logging.SherpaVerbosity`).

        This routine can not be used if you have used set_full_model:
        the calc_energy_flux routine should be used instead.

        Examples
        --------

        Estimate the flux distribution for the "src" component using
        the default data set. The parameters are assumed to be
        uncorrelated.

        >>> set_source(xsphabs.gal * xsapec.src)
        >>> fit()
        >>> fflux, cflux, vals = sample_flux(src, 0.5, 2, num=1000)
        original model flux = 2.88993e-14, + 1.92575e-15, - 1.81963e-15
        model component flux = 7.96865e-14, + 4.65144e-15, - 4.41222e-15
        >>> f0, fhi, flo = cflux
        >>> print("Flux: {:.2e} {:+.2e} {:+.2e}".format(f0, fhi-f0, flo-f0))
        Flux: 7.97e-14 +4.65e-15 -4.41e-15

        This time the parameters are assumed to be correlated, using
        the covariance matrix for the fit:

        >>> ans = sample_flux(src, 0.5, 2, num=1000, correlated=True)

        Explicitly send in the parameter widths (sigma values), using
        the estimates generated by `covar`:

        >>> covar()
        >>> errs = get_covar_results().parmaxes
        >>> ans = sample_flux(correlated=False, scales=errs, num=500)

        Explicitly send in a covariance matrix:

        >>> cmatrix = get_covar_results().extra_output
        >>> ans = sample_flux(correlated=True, scales=cmatrix, num=500)

        Run sample_flux after changing the logging level, so that the
        screen output from sample_flux is not displayed. We use the
        SherpaVerbosity function from `sherpa.utils.logging` to
        only change the logging level while runnng sample_flux:

        >>> from sherpa.utils.logging import SherpaVerbosity
        >>> with SherpaVerbosity('WARN'):
        ...     ans = sample_flux(num=1000, lo=0.5, hi=7)

        """

        if (confidence <= 0) or (confidence > 100):
            raise ArgumentErr('bad', 'confidence', 'must be > 0 and <= 100')

        if not Xrays:
            raise NotImplementedError("sample_flux(Xrays=False) is currently unsupported")

        _, fit = self._get_fit(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
        else:
            data = self.get_data(id)

        if (modelcomponent is not None) and \
           not isinstance(modelcomponent, sherpa.models.model.Model):
            raise ArgumentTypeErr('badarg', 'modelcomponent', 'a model')

        # We can not have a "full model" expression so error-out nicely here.
        # Thanks to _get_fit we know we have a model so any error below can
        # not be because no model is set but must be a "need full model"
        # error. TODO: should we have a nicer way to determine this?
        # Also note that it appears we have different ways the two code
        # paths can error out
        #
        if bkg_id is not None:
            try:
                self.get_bkg_source(id, bkg_id)
            except (IdentifierErr, ModelErr):
                # At present ModelErr is thrown but keep in IdentifierErr
                # just in case
                raise IdentifierErr('Please use calc_energy_flux as set_bkg_full_model was used') from None
        else:
            try:
                self.get_source(id)
            except IdentifierErr:
                raise IdentifierErr('Please use calc_energy_flux as set_full_model was used') from None

        correlated = sherpa.utils.bool_cast(correlated)

        # Why is this +1? The original comment was
        # "num+1 cause sample energy flux is under-reporting its result?"
        #
        niter = num + 1

        if not Xrays:
            # NOTE: calc_energy_flux only returns a scalar, which means you can
            #       not pass the results to calc_sample_flux, so this code
            #       is currently broken
            #
            samples = self.calc_energy_flux(lo=lo, hi=hi, id=id,
                                            bkg_id=bkg_id)
        else:
            # NOTE: the samples are drawn from the full model expression
            #       as this is how it was originally written
            #
            samples = self.sample_energy_flux(lo=lo, hi=hi, id=id, num=niter,
                                              scales=scales, clip='soft',
                                              correlated=correlated,
                                              numcores=numcores,
                                              bkg_id=bkg_id)

        return sherpa.astro.flux.calc_sample_flux(lo=lo, hi=hi,
                                                  fit=fit, data=data, samples=samples,
                                                  modelcomponent=modelcomponent,
                                                  confidence=confidence)

    def eqwidth(self, src, combo, id=None, lo=None, hi=None, bkg_id=None,
                error=False, params=None, otherids=(), niter=1000,
                covar_matrix=None):
        """Calculate the equivalent width of an emission or absorption line.

        The equivalent width [1]_ is calculated in the selected units
        for the data set (which can be retrieved with `get_analysis`).

        .. versionchanged:: 4.10.1
           The `error` parameter was added which controls whether the
           return value is a scalar (the calculated equivalent width),
           when set to `False`, or the median value, error limits, and
           ancillary values.

        Parameters
        ----------
        src
           The continuum model (this may contain multiple components).
        combo
           The continuum plus line (absorption or emission) model.
        lo : optional
           The lower limit for the calculation (the units are set by
           `set_analysis` for the data set). The default value (``None``)
           means that the lower range of the data set is used.
        hi : optional
           The upper limit for the calculation (the units are set by
           `set_analysis` for the data set). The default value (``None``)
           means that the upper range of the data set is used.
        id : int or string, optional
           The data set that provides the data. If not given then
           all data sets with an associated model are used simultaneously.
        bkg_id : int or string, optional
           The identifier of the background component to use. This
           should only be set when the line to be measured is in the
           background model.
        error : bool, optional
           The parameter indicates whether the errors are to be calculated
           or not.  The default value is False
        params : 2D array, optional
           The default is None, in which case get_draws shall be called.
           The user can input the parameter array (e.g. from running
           `sample_flux`).
        otherids : sequence of integer or strings, optional
           Other data sets to use in the calculation.
        niter : int, optional
           The number of draws to use. The default is ``1000``.
        covar_matrix : 2D array, optional
           The covariance matrix to use. If ``None`` then the
           result from `get_covar_results().extra_output` is used.

        Returns
        -------
        retval
           If ``error`` is ``False``, then returns the equivalent width,
           otherwise the median, 1 sigma lower bound, 1 sigma upper
           bound, the parameters array, and the array of the equivalent
           width values used to determine the errors.

        See Also
        --------
        calc_model_sum : Sum up the fitted model over a pass band.
        calc_source_sum : Calculate the un-convolved model signal.
        get_default_id : Return the default data set identifier.
        set_model : Set the source model expression.

        References
        ----------

        .. [1] http://en.wikipedia.org/wiki/Equivalent_width

        Examples
        --------

        Set a source model (a powerlaw for the continuum and a
        gaussian for the line), fit it, and then evaluate the
        equivalent width of the line. The example assumes that
        this is a PHA data set, with an associated response,
        so that the analysis can be done in wavelength units.

        >>> set_source(powlaw1d.cont + gauss1d.line)
        >>> set_analysis('wavelength')
        >>> fit()
        >>> eqwidth(cont, cont+line)
        2.1001988282497308

        The calculation is restricted to the range 20 to 20
        Angstroms.

        >>> eqwidth(cont, cont+line, lo=20, hi=24)
        1.9882824973082310

        The calculation is done for the background model of
        data set 2, over the range 0.5 to 2 (the units of this
        are whatever the analysis setting for this data set id).

        >>> set_bkg_source(2, const1d.flat + gauss1d.bline)
        >>> eqwidth(flat, flat+bline, id=2, bkg_id=1, lo=0.5, hi=2)
        0.45494599793003426

        With the `error` flag set to `True`, the return value is
        enhanced with extra information, such as the median and
        one-sigma ranges on the equivalent width::

        >>> res = eqwidth(p1, p1 + g1, error=True)
        >>> ewidth = res[0]  # the median equivalent width
        >>> errlo = res[1]   # the one-sigma lower limit
        >>> errhi = res[2]   # the one-sigma upper limit
        >>> pars = res[3]    # the parameter values used
        >>> ews = res[4]     # array of eq. width values

        which can be used to display the probability density or
        cumulative distribution function of the equivalent widths::

        >>> plot_pdf(ews)
        >>> plot_cdf(ews)

        """
        data = self.get_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)

        ####################################################
        if error:

            def is_numpy_ndarray(arg, name, npars, dim1=None):
                if not isinstance(arg, numpy.ndarray):
                    msg = name + ' must be of type numpy.ndarray'
                    raise IOErr(msg)
                shape = arg.shape
                if len(shape) != 2:
                    msg = name + ' must be 2d numpy.ndarray'
                    raise IOErr(msg)
                if shape[0] != npars:
                    msg = name + ' must be of dimension (%d, x)' % npars
                    raise IOErr(msg)
                if dim1 is not None:
                    if shape[1] != npars:
                        msg = name + ' must be of dimension (%d, %d)' % \
                            (npars, npars)
                        raise IOErr(msg)

            _, fit = self._get_fit(id)
            fit_results = self.get_fit_results()
            parnames = fit_results.parnames
            npar = len(parnames)
            orig_par_vals = numpy.array(fit_results.parvals)

            if params is None:
                # run get_draws or normal distribution depending on fit stat
                if covar_matrix is None:
                    try:
                        # check just in case usr has run covar()
                        covar_results = self.get_covar_results()
                        covar_matrix = covar_results.extra_output
                    except sherpa.utils.err.SessionErr:
                        # usr has not run covar, will have to run it
                        covar_matrix = fit.est_errors().extra_output
                is_numpy_ndarray(covar_matrix, 'covar_matrix', npar, npar)

                # Have enough stuff to generate samples
                if isinstance(self._current_stat, (Cash, CStat, WStat)):
                    _, _, params = \
                        self.get_draws(id, otherids=otherids, niter=niter,
                                       covar_matrix=covar_matrix)
                else:
                    sampler = NormalParameterSampleFromScaleMatrix()
                    tmp = sampler.get_sample(fit, covar_matrix, niter + 1)
                    params = tmp.transpose()

            else:
                is_numpy_ndarray(params, 'params', npar)

            mins = fit.model._get_thawed_par_mins()
            maxs = fit.model._get_thawed_par_maxes()
            eqw = numpy.zeros_like(params[0, :])
            for params_index in range(len(params[0, :])):
                for parnames_index, parname in enumerate(parnames):
                    val = params[parnames_index, params_index]
                    # Note: the normal dist does not respect the soft limits
                    mymin = mins[parnames_index]
                    mymax = maxs[parnames_index]
                    val = max(mymin, min(val, mymax))
                    self.set_par(parname, val)
                eqw[params_index] = \
                    sherpa.astro.utils.eqwidth(data, src, combo, lo, hi)
            median, lower, upper = sherpa.utils.get_error_estimates(eqw)
            fit.model.thawedpars = orig_par_vals
            return median, lower, upper, params, eqw

        ####################################################
        return sherpa.astro.utils.eqwidth(data, src, combo, lo, hi)

    def calc_photon_flux(self, lo=None, hi=None, id=None, bkg_id=None,
                         model=None):
        """Integrate the unconvolved source model over a pass band.

        Calculate the integral of S(E) over a pass band, where S(E) is
        the spectral model evaluated for each bin (that is, the model
        without any instrumental responses applied to it).

        .. versionchanged:: 4.12.1
           The model parameter was added.

        Parameters
        ----------
        lo, hi : number, optional
           If both are None or both are set then calculate the flux
           over the given band. If only one is set then calculate
           the flux density at that point. The units for `lo` and `hi`
           are given by the current analysis setting.
        id : int or str, optional
           Use the source expression associated with this data set. If
           not given then the default identifier is used, as returned
           by `get_default_id`.
        bkg_id : int or str, optional
           If set, use the model associated with the given background
           component rather than the source model.
        model : model, optional
           The model to integrate. If left as `None` then the source
           model for the dataset will be used. This can be used to
           calculate the unabsorbed flux, as shown in the examples.

        Returns
        -------
        flux : number
           The flux or flux density.  For X-Spec style models the
           flux units will be photon/cm^2/s and the flux density units
           will be either photon/cm^2/s/keV or photon/cm^2/s/Angstrom,
           depending on the analysis setting.

        See Also
        --------
        calc_data_sum : Sum up the observed counts over a pass band.
        calc_model_sum : Sum up the fitted model over a pass band.
        calc_energy_flux : Integrate the unconvolved source model over a pass band.
        calc_source_sum: Sum up the source model over a pass band.
        set_analysis : Set the units used when fitting and displaying spectral data
        set_model : Set the source model expression for a data set.

        Notes
        -----
        The units of `lo` and `hi` are determined by the analysis
        setting for the data set (e.g. `get_analysis`).

        Any existing filter on the data set - e.g. as created by
        `ignore` or `notice` - is ignored by this function.

        The units of the answer depend on the model components used in
        the source expression and the axis or axes of the data set.
        It is unlikely to give sensible results for 2D data sets.

        Examples
        --------

        Calculate the integral of the unconvolved model over the
        full range of the default data set:

        >>> calc_photon_flux()

        Return the flux for the data set labelled "core":

        >>> calc_photon_flux(id='core')

        Calculate the photon flux over the ranges 0.5 to 2 and 0.5 to
        7 keV, and compared to the energy fluxes for the same bands:

        >>> set_analysis('energy')
        >>> calc_photon_flux(0.5, 2)
        0.35190275
        >>> calc_photon_flux(0.5, 7)
        0.49050927
        >>> calc_energy_flux(0.5, 2)
        5.7224906878061796e-10
        >>> calc_energy_flux(0.5, 7)
        1.3758131915063825e-09

        Calculate the photon flux density at 0.5 keV for the source
        "core":

        >>> calc_photon_flux(0.5, id="core")
        0.64978176

        Calculate the flux for the model applied to the second background
        component of the 'jet' data set, for the wavelength range 20 to 22
        Angstroms:

        >>> set_analysis('jet', 'wave')
        >>> calc_photon_flux(20, 22, id='jet', bkg_id=2)

        For the following example, the source model is an absorbed
        powerlaw - `xsphabs.gal * powerlaw.pl` - so that the `fabs`
        value represents the absorbed flux, and `funabs` the unabsorbed
        flux (i.e. just the power-law component):

        >>> fabs = calc_photon_flux(0.5, 7)
        >>> funabs = calc_photon_flux(0.5, 7, model=pl)

        """

        if bkg_id is None:
            data = self.get_data(id)
        else:
            data = self.get_bkg(id, bkg_id)

        if model is None:
            if bkg_id is None:
                model = self.get_source(id)
            else:
                model = self.get_bkg_source(id, bkg_id)
        else:
            _check_type(model, sherpa.models.Model, 'model',
                        'a model object')

        return sherpa.astro.utils.calc_photon_flux(data, model, lo, hi)

    def calc_energy_flux(self, lo=None, hi=None, id=None, bkg_id=None,
                         model=None):
        """Integrate the unconvolved source model over a pass band.

        Calculate the integral of E * S(E) over a pass band, where E
        is the energy of the bin and S(E) the spectral model evaluated
        for that bin (that is, the model without any instrumental
        responses applied to it).

        .. versionchanged:: 4.12.1
           The model parameter was added.

        Parameters
        ----------
        lo, hi : number, optional
           If both are None or both are set then calculate the flux
           over the given band. If only one is set then calculate
           the flux density at that point. The units for `lo` and `hi`
           are given by the current analysis setting.
        id : int or str, optional
           Use the source expression associated with this data set. If
           not given then the default identifier is used, as returned
           by ``get_default_id``.
        bkg_id : int or str, optional
           If set, use the model associated with the given background
           component rather than the source model.
        model : model, optional
           The model to integrate. If left as `None` then the source
           model for the dataset will be used. This can be used to
           calculate the unabsorbed flux, as shown in the examples.

        Returns
        -------
        flux : number
           The flux or flux density.  For X-Spec style models the
           flux units will be erg/cm^2/s and the flux density units
           will be either erg/cm^2/s/keV or erg/cm^2/s/Angstrom,
           depending on the analysis setting.

        See Also
        --------
        calc_data_sum : Sum up the data values over a pass band.
        calc_model_sum : Sum up the fitted model over a pass band.
        calc_source_sum: Sum up the source model over a pass band.
        calc_photon_flux : Integrate the unconvolved source model over a pass band.
        set_analysis : Set the units used when fitting and displaying spectral data
        set_model : Set the source model expression for a data set.

        Notes
        -----
        The units of ``lo`` and ``hi`` are determined by the analysis
        setting for the data set (e.g. ``get_analysis``).

        Any existing filter on the data set - e.g. as created by
        ``ignore`` or ``notice`` - is ignored by this function.

        The units of the answer depend on the model components used in
        the source expression and the axis or axes of the data set.
        It is unlikely to give sensible results for 2D data sets.

        Examples
        --------

        Calculate the integral of the unconvolved model over the
        full range of the default data set:

        >>> calc_energy_flux()

        Return the flux for the data set labelled "core":

        >>> calc_energy_flux(id='core')

        Calculate the energy flux over the ranges 0.5 to 2 and 0.5 to
        7 keV:

        >>> set_analysis('energy')
        >>> calc_energy_flux(0.5, 2)
        5.7224906878061796e-10
        >>> calc_energy_flux(0.5, 7)
        1.3758131915063825e-09

        Calculate the energy flux density at 0.5 keV for the source
        "core":

        >>> calc_energy_flux(0.5, id="core")
        5.2573786652855304e-10

        Calculate the flux for the model applied to the second background
        component of the 'jet' data set, for the wavelength range 20 to 22
        Angstroms:

        >>> set_analysis('jet', 'wave')
        >>> calc_energy_flux(20, 22, id='jet', bkg_id=2)

        For the following example, the source model is an absorbed
        powerlaw - `xsphabs.gal * powerlaw.pl` - so that the `fabs`
        value represents the absorbed flux, and `funabs` the unabsorbed
        flux (i.e. just the power-law component):

        >>> fabs = calc_energy_flux(0.5, 7)
        >>> funabs = calc_energy_flux(0.5, 7, model=pl)

        """

        if bkg_id is None:
            data = self.get_data(id)
        else:
            data = self.get_bkg(id, bkg_id)

        if model is None:
            if bkg_id is None:
                model = self.get_source(id)
            else:
                model = self.get_bkg_source(id, bkg_id)
        else:
            _check_type(model, sherpa.models.Model, 'model',
                        'a model object')

        return sherpa.astro.utils.calc_energy_flux(data, model, lo, hi)

    # DOC-TODO: how do lo/hi limits interact with bin edges;
    # is it all in or partially in or ...
    def calc_data_sum(self, lo=None, hi=None, id=None, bkg_id=None):
        """Sum up the data values over a pass band.

        This function is for one-dimensional data sets: use
        `calc_data_sum2d` for two-dimensional data sets.

        Parameters
        ----------
        lo, hi : number, optional
           If both are None or both are set then sum up the data
           over the given band. If only one is set then return
           the data count in the given bin.
        id : int or str, optional
           Use the source expression associated with this data set. If
           not given then the default identifier is used, as returned
           by `get_default_id`.
        bkg_id : int or str, optional
           If set, use the model associated with the given background
           component rather than the source model.

        Returns
        -------
        dsum : number
           If a background estimate has been subtracted from the data
           set then the calculation will use the background-subtracted
           values.

        See Also
        --------
        calc_data_sum2d : Sum up the data values of a 2D data set.
        calc_model_sum : Sum up the fitted model over a pass band.
        calc_energy_flux : Integrate the unconvolved source model over a pass band.
        calc_photon_flux : Integrate the unconcolved source model over a pass band.
        calc_source_sum: Sum up the source model over a pass band.
        set_model : Set the source model expression for a data set.

        Notes
        -----
        The units of ``lo`` and ``hi`` are determined by the analysis
        setting for the data set (e.g. `get_analysis`). The summation
        occurs over those points in the data set that lie within this
        range, not the range itself.

        Any existing filter on the data set - e.g. as created by
        `ignore` or `notice` - is ignored by this function.

        If a grouping scheme has been applied to the data set that it
        will be used. This can change the results, since the first and
        last bins of the selected range may extend outside the
        requested range.

        Examples
        --------

        Sum up the data values (the dependent axis) for all points or
        bins in the default data set:

        >>> dsum = calc_data_sum()

        Calculate the number of counts over the ranges 0.5 to 2 and 0.5 to
        7 keV for the default data set, first using the observed signal
        and then, for the 0.5 to 2 keV band - the background-subtraced
        estimate:

        >>> set_analysis('energy')
        >>> calc_data_sum(0.5, 2)
        745.0
        >>> calc_data_sum(0.5, 7)
        60.0
        >>> subtract()
        >>> calc_data_sum(0.5, 2)
        730.9179738207356

        Calculate the data value in the bin containing 0.5 keV for the
        source "core":

        >>> calc_data_sum(0.5, id="core")
        0.0

        Calculate the sum of the second background component for data
        set 3 over the independent axis range 12 to 45:

        >>> calc_data_sum(12, 45, id=3, bkg_id=2)

        """
        data = self.get_data(id)
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
        return sherpa.astro.utils.calc_data_sum(data, lo, hi)

    # DOC-TODO: better comparison of calc_source_sum and calc_model_sum
    # needed (e.g. integration or results in PHA case?)
    #
    # DOC-TODO: add some form of convolution to the last example
    #           to show the difference between calc_model_sum and
    #           calc_source_sum
    #
    def calc_model_sum(self, lo=None, hi=None, id=None, bkg_id=None):
        """Sum up the fitted model over a pass band.

        Sum up M(E) over a range of bins, where M(E) is the per-bin model
        value after it has been convolved with any instrumental response
        (e.g. RMF and ARF or PSF). This is intended for one-dimensional
        data sets: use `calc_model_sum2d` for two-dimensional data sets.
        The `calc_source_sum` function is used to calculate the sum of the
        model before any instrumental response is applied.

        Parameters
        ----------
        lo, hi : number, optional
           If both are None or both are set then sum up over the given
           band. If only one is set then use the model value in the
           selected bin. The units for `lo` and `hi` are given by the
           current analysis setting.
        id : int or str, optional
           Use the source expression associated with this data set. If
           not given then the default identifier is used, as returned
           by `get_default_id`.
        bkg_id : int or str, optional
           If set, use the model associated with the given background
           component rather than the source model.

        Returns
        -------
        signal : number
           The model value (sum or individual bin).

        See Also
        --------
        calc_data_sum : Sum up the observed counts over a pass band.
        calc_energy_flux : Integrate the unconvolved source model over a pass band.
        calc_photon_flux : Integrate the unconvolved source model over a pass band.
        calc_source_sum: Sum up the source model over a pass band.
        set_model : Set the source model expression for a data set.

        Notes
        -----
        The units of ``lo`` and ``hi`` are determined by the analysis
        setting for the data set (e.g. `get_analysis`). The summation
        occurs over those points in the data set that lie within this
        range, not the range itself.

        Any existing filter on the data set - e.g. as created by
        `ignore` or `notice` - is ignored by this function.

        The units of the answer depend on the model components used in
        the source expression and the axis or axes of the data set.

        Examples
        --------

        Calculate the model evaluated over the full data set (all points
        or pixels of the independent axis) for the default data set,
        and compare it to the sum for th first background component:

        >>> tsrc = calc_model_sum()
        >>> tbkg = calc_model_sum(bkg_id=1)

        Sum up the model over the data range 0.5 to 2 for the default
        data set, and compared to the data over the same range:

        >>> calc_model_sum(0.5, 2)
        404.97796489631639
        >>> calc_data_sum(0.5, 2)
        745.0

        Calculate the model sum, evaluated over the range 20 to 22
        Angstroms, for the first background component of the "histate"
        data set:

        >>> set_analysis("histate", "wavelength")
        >>> calc_model_sum(20, 22, "histate", bkg_id=1)

        In the following example, a small data set is created, covering
        the axis range of -5 to 5, and an off-center gaussian model
        created (centered at 1). The model is evaluated over the full
        data grid and then a subset of pixels. As the summation is done
        over those points in the data set that lie within the requested
        range, the sum for lo=-2 to hi=1 is the same as that for
        lo=-1.5 to hi=1.5:

        >>> load_arrays('test', [-5, -2.5, 0, 2.5, 5], [2, 5, 12, 7, 3])
        >>> set_source('test', gauss1d.gmdl)
        >>> gmdl.pos = 1
        >>> gmdl.fwhm = 2.4
        >>> gmdl.ampl = 10
        >>> calc_model_sum(id='test')
        9.597121089731253
        >>> calc_model_sum(-2, 1, id='test')
        6.179472329646446
        >>> calc_model_sum(-1.5, 1.5, id='test')
        6.179472329646446

        """
        data = self.get_data(id)
        model = None
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
            model = self.get_bkg_model(id, bkg_id)
        else:
            model = self.get_model(id)
        return sherpa.astro.utils.calc_model_sum(data, model, lo, hi)

    def calc_data_sum2d(self, reg=None, id=None):
        """Sum up the data values of a 2D data set.

        This function is for two-dimensional data sets: use
        `calc_model_sum` for one-dimensional data sets.

        Parameters
        ----------
        reg : str, optional
           The spatial filter to use. The default, ``None``, is to
           use the whole data set.
        id : int or str, optional
           Use the source expression associated with this data set. If
           not given then the default identifier is used, as returned
           by `get_default_id`.

        Returns
        -------
        dsum : number
           The sum of the data values that lie within the given
           region.

        See Also
        --------
        calc_data_sum : Sum up the data values of a data set.
        calc_model_sum2d : Sum up the convolved model for a 2D data set.
        calc_source_sum2d: Sum up the unconvolved model for a 2D data set.
        set_model : Set the source model expression for a data set.

        Notes
        -----
        The coordinate system of the region filter is determined by
        the coordinate setting for the data set (e.g. `get_coord`).

        Any existing filter on the data set - e.g. as created by
        `ignore2d` or `notice2d` - is ignored by this function.

        Examples
        --------

        The following examples use the data in the default data set
        created with the following calls, which sets the y (data)
        values to be 0 to 11 in a 3 row by 4 column image:

        >>> ivals = np.arange(12)
        >>> y, x = np.mgrid[10:13, 20:24]
        >>> y = y.flatten()
        >>> x = x.flatten()
        >>> load_arrays(1, x, y, ivals, (3, 4), DataIMG)

        with no argument, the full data set is used:

        >>> calc_data_sum2d()
        66
        >>> ivals.sum()
        66

        and a spatial filter can be used to restrict the region
        used for the summation:

        >>> calc_data_sum2d('circle(22,12,1)')
        36
        >>> calc_data_sum2d('field()-circle(2,2,1)')
        30

        Apply the spatial filter to the data set labelled "a2142":

        >>> calc_data_sum2d('rotbox(4232.3,3876,300,200,43)', 'a2142')

        """
        data = self.get_data(id)
        return sherpa.astro.utils.calc_data_sum2d(data, reg)

    # DOC-TODO: show an example with psf
    #           and change the model (to a non-flat distribution, otherwise
    #           the PSF doesn't really help)
    # DOC-TODO: this needs testing as doesn't seem to be working for me
    def calc_model_sum2d(self, reg=None, id=None):
        """Sum up the convolved model for a 2D data set.

        This function is for two-dimensional data sets: use
        `calc_model_sum` for one-dimensional data sets.

        Parameters
        ----------
        reg : str, optional
           The spatial filter to use. The default, ``None``, is to
           use the whole data set.
        id : int or str, optional
           Use the source expression associated with this data set. If
           not given then the default identifier is used, as returned
           by `get_default_id`.

        Returns
        -------
        msum : number
           The sum of the model values, as fitted to the data, that
           lie within the given region. This includes any PSF
           included by `set_psf`.

        See Also
        --------
        calc_model_sum : Sum up the fitted model over a pass band.
        calc_source_sum2d: Sum up the unconvolved model for a 2D data set.
        set_psf : Add a PSF model to a data set.
        set_model : Set the source model expression for a data set.

        Notes
        -----
        The coordinate system of the region filter is determined by
        the coordinate setting for the data set (e.g. `get_coord`).

        Any existing filter on the data set - e.g. as created by
        `ignore2d` or `notice2d` - is ignored by this function.

        Examples
        --------

        The following examples use the data in the default data set
        created with the following calls, which sets the y (data)
        values to be 0 to 11 in a 3 row by 4 column image:

        >>> ivals = np.arange(12)
        >>> y, x = np.mgrid[10:13, 20:24]
        >>> y = y.flatten()
        >>> x = x.flatten()
        >>> load_arrays(1, x, y, ivals, (3, 4), DataIMG)
        >>> set_source(const2d.bgnd)
        >>> bgnd.c0 = 2

        with no argument, the full data set is used. Since the model
        evaluates to 2 per pixel, and there are 12 pixels in the
        data set, the result is 24:

        >>> calc_model_sum2d()
        24.0

        and a spatial filter can be used to restrict the region
        used for the summation:

        >>> calc_model_sum2d('circle(22,12,1)')
        8.0
        >>> calc_model_sum2d('field()-circle(22,12,1)')
        16.0

        Apply the spatial filter to the model for the data set
        labelled "a2142":

        >>> calc_model_sum2d('rotbox(4232.3,3876,300,200,43)', 'a2142')

        """
        data = self.get_data(id)
        model = self.get_model(id)
        return sherpa.astro.utils.calc_model_sum2d(data, model, reg)

    def calc_source_sum2d(self, reg=None, id=None):
        """Sum up the unconvolved model for a 2D data set.

        This function is for two-dimensional data sets: use
        `calc_source_sum` for one-dimensional data sets.

        Parameters
        ----------
        reg : str, optional
           The spatial filter to use. The default, ``None``, is to
           use the whole data set.
        id : int or str, optional
           Use the source expression associated with this data set. If
           not given then the default identifier is used, as returned
           by `get_default_id`.

        Returns
        -------
        msum : number
           The sum of the model values that lie within the given
           region. This does not include any PSF included by
           `set_psf`.

        See Also
        --------
        calc_model_sum2d : Sum up the convolved model for a 2D data set.
        calc_source_sum : Sum up the model over a pass band.
        set_psf : Add a PSF model to a data set.
        set_model : Set the source model expression for a data set.

        Notes
        -----
        The coordinate system of the region filter is determined by
        the coordinate setting for the data set (e.g. `get_coord`).

        Any existing filter on the data set - e.g. as created by
        `ignore2d` or `notice2d` - is ignored by this function.

        Examples
        --------

        The following examples use the data in the default data set
        created with the following calls, which sets the y (data)
        values to be 0 to 11 in a 3 row by 4 column image:

        >>> ivals = np.arange(12)
        >>> y, x = np.mgrid[10:13, 20:24]
        >>> y = y.flatten()
        >>> x = x.flatten()
        >>> load_arrays(1, x, y, ivals, (3, 4), DataIMG)
        >>> set_source(const2d.bgnd)
        >>> bgnd.c0 = 2

        with no argument, the full data set is used. Since the model
        evaluates to 2 per pixel, and there are 12 pixels in the
        data set, the result is 24:

        >>> calc_source_sum2d()
        24.0

        and a spatial filter can be used to restrict the region
        used for the summation:

        >>> calc_source_sum2d('circle(22,12,1)')
        8.0
        >>> calc_source_sum2d('field()-circle(22,12,1)')
        16.0

        Apply the spatial filter to the model for the data set
        labelled "a2142":

        >>> calc_source_sum2d('rotbox(4232.3,3876,300,200,43)', 'a2142')

        """
        data = self.get_data(id)
        src = self.get_source(id)
        return sherpa.astro.utils.calc_model_sum2d(data, src, reg)

    def calc_source_sum(self, lo=None, hi=None, id=None, bkg_id=None):
        """Sum up the source model over a pass band.

        Sum up S(E) over a range of bins, where S(E) is the per-bin model
        value before it has been convolved with any instrumental response
        (e.g. RMF and ARF or PSF). This is intended for one-dimensional
        data sets: use `calc_source_sum2d` for two-dimensional data sets.
        The `calc_model_sum` function is used to calculate the sum of the
        model after any instrumental response is applied.

        Parameters
        ----------
        lo, hi : number, optional
           If both are None or both are set then sum up over the given
           band. If only one is set then use the model value in the
           selected bin. The units for `lo` and `hi` are given by the
           current analysis setting.
        id : int or str, optional
           Use the source expression associated with this data set. If
           not given then the default identifier is used, as returned
           by `get_default_id`.
        bkg_id : int or str, optional
           If set, use the model associated with the given background
           component rather than the source model.

        Returns
        -------
        signal : number
           The model value (sum or individual bin).

        See Also
        --------
        calc_data_sum : Sum up the observed counts over a pass band.
        calc_model_sum : Sum up the fitted model over a pass band.
        calc_energy_flux : Integrate the unconvolved source model over a pass band.
        calc_photon_flux : Integrate the unconvolved source model over a pass band.
        set_model : Set the source model expression for a data set.

        Notes
        -----
        The units of ``lo`` and ``hi`` are determined by the analysis
        setting for the data set (e.g. `get_analysis`). The summation
        occurs over those points in the data set that lie within this
        range, not the range itself.

        Any existing filter on the data set - e.g. as created by
        `ignore` or `notice` - is ignored by this function.

        The units of the answer depend on the model components used in
        the source expression and the axis or axes of the data set.

        Examples
        --------

        Calculate the model evaluated over the full data set (all points
        or pixels of the independent axis) for the default data set,
        and compare it to the sum for th first background component:

        >>> tsrc = calc_source_sum()
        >>> tbkg = calc_source_sum(bkg_id=1)

        Sum up the model over the data range 0.5 to 2 for the default
        data set:

        >>> calc_source_sum(0.5, 2)
        139.12819041922018

        Compare the output of the `calc_source_sum` and `calc_photon_flux`
        routines. A 1099-bin data space is created, with a model which has
        a value of 1 for each bin. As the bin width is constant, at 0.01,
        the integrated value, calculated by `calc_photon_flux`, is one
        hundredth the value returned by `calc_data_sum`:

        >>> dataspace1d(0.01, 11, 0.01, id="test")
        >>> set_source("test", const1d.bflat)
        >>> bflat.c0 = 1
        >>> calc_source_sum(id="test")
        1099.0
        >>> calc_photon_flux(id="test")
        10.99

        In the following example, a small data set is created, covering
        the axis range of -5 to 5, and an off-center gaussian model
        created (centered at 1). The model is evaluated over the full
        data grid and then a subset of pixels. As the summation is done
        over those points in the data set that lie within the requested
        range, the sum for lo=-2 to hi=1 is the same as that for
        lo=-1.5 to hi=1.5:

        >>> load_arrays('test', [-5, -2.5, 0, 2.5, 5], [2, 5, 12, 7, 3])
        >>> set_source('test', gauss1d.gmdl)
        >>> gmdl.pos = 1
        >>> gmdl.fwhm = 2.4
        >>> gmdl.ampl = 10
        >>> calc_source_sum(id='test')
        9.597121089731253
        >>> calc_source_sum(-2, 1, id='test')
        6.179472329646446
        >>> calc_source_sum(-1.5, 1.5, id='test')
        6.179472329646446

        """
        data = self.get_data(id)
        model = None
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
            model = self.get_bkg_source(id, bkg_id)
        else:
            model = self.get_source(id)
        return sherpa.astro.utils.calc_source_sum(data, model, lo, hi)

    # DOC-TODO: no reason can't k-correct wavelength range,
    # but need to work out how to identify the units
    def calc_kcorr(self, z, obslo, obshi, restlo=None, resthi=None,
                   id=None, bkg_id=None):
        """Calculate the K correction for a model.

        The K correction ([1]_, [2]_, [3]_, [4]_) is the numeric
        factor applied to measured energy fluxes in an observed
        energy band to estimate the flux in a given rest-frame
        energy band. It accounts for the change in spectral energy
        distribution between the desired rest-frame band and the
        rest-frame band corresponding to the observed band. This is
        often used when converting a flux into a luminosity.

        Parameters
        ----------
        z : number or array, >= 0
           The redshift, or redshifts, of the source.
        obslo : number
           The minimum energy of the observed band.
        obshi : number
           The maximum energy of the observed band, which must
           be larger than ``obslo``.
        restlo : number or ``None``
           The minimum energy of the rest-frame band. If ``None`` then
           use ``obslo``.
        resthi : number or ``None``
           The maximum energy of the rest-frame band. It must be
           larger than ``restlo``. If ``None`` then use ``obshi``.
        id : int or str, optional
           Use the source expression associated with this data set. If
           not given then the default identifier is used, as returned
           by `get_default_id`.
        bkg_id : int or str, optional
           If set, use the model associated with the given background
           component rather than the source model.

        Returns
        -------
        kz : number or array of numbers

        See Also
        --------
        calc_energy_flux : Integrate the unconvolved source model over a pass band.
        dataspace1d : Create the independent axis for a 1D data set.

        Notes
        -----
        This is only defined when the analysis is in 'energy' units.

        If the model contains a redshift parameter then it should
        be set to 0, rather than the source redshift.

        If the source model is at zero redshift, the observed energy
        band is olo to ohi, and the rest frame band is rlo to rhi
        (which need not match the observed band), then the K
        correction at a redshift z can be calculated as::

          frest = calc_energy_flux(rlo, rhi)
          fobs  = calc_energy_flux(olo*(1+z), ohi*(1+z))
          kz    = frest / fobs

        The energy ranges used - rlo to rhi and olo*(1+z) to ohi*(1+z)
        - should be fully covered by the data grid, otherwise the flux
        calculation will be truncated at the grid boundaries, leading
        to incorrect results.

        References
        ----------

        .. [1] "The K correction", Hogg, D.W., et al.
               http://arxiv.org/abs/astro-ph/0210394

        .. [2] Appendix B of Jones et al. 1998, ApJ, vol 495,
               p. 100-114.
               http://adsabs.harvard.edu/abs/1998ApJ...495..100J

        .. [3] "K and evolutionary corrections from UV to IR",
               Poggianti, B.M., A&AS, 1997, vol 122, p. 399-407.
               http://adsabs.harvard.edu/abs/1997A%26AS..122..399P

        .. [4] "Galactic evolution and cosmology - Probing the
               cosmological deceleration parameter", Yoshii, Y. &
               Takahara, F., ApJ, 1988, vol 326, p. 1-18.
               http://adsabs.harvard.edu/abs/1988ApJ...326....1Y

        Examples
        --------

        Calculate the K correction for an X-Spec apec model, with a
        source temperature of 6 keV and abundance of 0.3 solar, for
        the energy band of 0.5 to 2 keV:

        >>> dataspace1d(0.01, 10, 0.01)
        >>> set_source(xsapec.clus)
        >>> clus.kt = 6
        >>> clus.abundanc = 0.3
        >>> calc_kcorr(0.5, 0.5, 2)
        0.82799195070436793

        Calculate the K correction for a range of redshifts (0 to 2)
        using an observed frame of 0.5 to 2 keV and a rest frame of 0.1
        to 10 keV (the energy grid is set to ensure that it covers the
        full energy range; that is the rest-frame band and the
        observed frame band multiplied by the smallest and largest
        (1+z) terms):

        >>> dataspace1d(0.01, 11, 0.01)
        >>> zs = np.linspace(0, 2, 21)
        >>> ks = calc_kcorr(zs, 0.5, 2, restlo=0.1, resthi=10)

        Calculate the k correction for the background dataset
        bkg_id=2 for a redshift of 0.5 over the energy range
        0.5 to 2 keV with rest-frame energy limits of 2 to 10 keV.

        >>> calc_kcorr(0.5, 0.5, 2, 2, 10, bkg_id=2)

        """
        data = self.get_data(id)
        model = None
        if bkg_id is not None:
            data = self.get_bkg(id, bkg_id)
            model = self.get_bkg_source(id, bkg_id)
        else:
            model = self.get_source(id)

        return sherpa.astro.utils.calc_kcorr(data, model, z, obslo, obshi,
                                             restlo, resthi)

    ###########################################################################
    # Session Text Save Function
    ###########################################################################

    def save_all(self, outfile=None, clobber=False):
        """Save the information about the current session to a text file.

        This differs to the `save` command in that the output is human
        readable. Three consequences are:

         1. numeric values may not be recorded to their full precision

         2. data sets are not included in the file

         3. some settings and values may not be recorded.

        Parameters
        ----------
        outfile : str or file-like, optional
           If given, the output is written to this file, and the
           `clobber` parameter controls what happens if the
           file already exists.
           `outfile` can be a filename string or a file handle
           (or file-like object, such as ``StringIO``) to write
           to. If not set then the standard output is used.
        clobber : bool, optional
           If `outfile` is a filename, then this flag controls
           whether an existing file can be overwritten (``True``)
           or if it raises an exception (``False``, the default
           setting).

        Raises
        ------
        sherpa.utils.err.IOErr
           If `outfile` already exists and `clobber` is ``False``.

        See Also
        --------
        save : Save the current Sherpa session to a file.
        restore : Load in a Sherpa session from a file.

        Notes
        -----

        This command will create a series of commands that restores
        the current Sherpa set up. It does not save the set of commands
        used. Not all Sherpa settings are saved. Items not fully restored
        include:

        - data created by calls to `load_arrays`, or changed from the
          version on disk - e.g. by calls to `sherpa.astro.ui.set_counts`.

        - any optional keywords to comands such as `load_data`
          or `load_pha`

        - user models may not be restored correctly

        - only a subset of Sherpa commands are saved.

        Examples
        --------

        Write the current Sherpa session to the screen:

        >>> save_all()

        Save the session to the file 'fit.sherpa', overwriting
        it if it already exists:

        >>> save_all('fit.sherpa', clobber=True)

        Write the contents to a StringIO object:

        >>> from io import StringIO
        >>> store = StringIO()
        >>> save_all(store)

        """

        if isinstance(outfile, string_types):
            if os.path.isfile(outfile):
                if sherpa.utils.bool_cast(clobber):
                    os.remove(outfile)
                else:
                    raise IOErr('filefound', outfile)

            with open(outfile, 'w') as fh:
                serialize.save_all(self, fh)

        else:
            if outfile is not None:
                fh = outfile
            else:
                fh = sys.stdout

            serialize.save_all(self, fh)

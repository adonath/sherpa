#
#  Copyright (C) 2007, 2017, 2020, 2021
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

"""Support for model parameter values.

Parameter creation, evaluation, and combination are normally done as
part of the model interface provided by
sherpa.models.model.ArithmeticModel.

In the following the p variable corresponds to

    >>> from sherpa.models.parameter import Parameter
    >>> p = Parameter('model', 'eta', 2)
    >>> print(p)
    val         = 2.0
    min         = -3.4028234663852886e+38
    max         = 3.4028234663852886e+38
    units       =
    frozen      = False
    link        = None
    default_val = 2.0
    default_min = -3.4028234663852886e+38
    default_max = 3.4028234663852886e+38

Naming
======

The first two arguments to a parameter are the model name and then the
parameter name, so `"model"` and `"eta"` here. They are used to
display the `name` and `fullname` attributes:

    >>> p.name
    'eta'
    >>> p.fullname
    'model.eta'

A units field can be attached to the parameter, but this is used purely
for screen output by the sherpa.models.model.ArithmeticModel class and
is not used when changing or evaluating the parameter.

Changing parameter values
=========================

The `val` attribute is used to retrieve or change the parameter value:

    >>> p.val
    2.0
    >>> p.val = 3

Parameter limts
===============

The parameter is forced to lie within the `min` and `max` attributes
of the parameter (known as the "soft" limits). The default values
for these are the 32-bit floating point maximum value, and it's
negative:

    >>> p.max
    3.4028234663852886e+38
    >>> p.min
    -3.4028234663852886e+38

Setting a value outside this range will raise a sherpa.utils.err.ParameterErr

    >>> p.val = 1e40
    ParameterErr: parameter model.eta has a maximum of 3.40282e+38

These limits can be changed, as shown below, but they must lie
within the `hard_min` to `hard_max` range of the parameter (the
"hard" limits), which can not be changed:

    >>> p.min = 0
    >>> p.max = 10

Freezing and thawing
====================

When fitting a model expression it is useful to be able to restrict
the fit to a subset of parameters. This is done by only selecting
those parameters which are not "frozen". This can be indicated by
calling the `freeze` and `thaw` methods, or changing the `frozen`
attribute directly:

    >>> p.frozen
    False
    >>> p.freeze()
    >>> p.frozen
    True
    >>> p.thaw()
    >>> p.frozen
    False

Note that the `frozen` flag is used to indicate what parameters to
vary in a fit, but it is still possible to directly change a parameter
value when it is frozen:

    >>> p.freeze()
    >>> p.val = 6
    >>> print(p)
    val         = 6.0
    min         = 0.0
    max         = 10.0
    units       =
    frozen      = True
    link        = None
    default_val = 6.0
    default_min = -3.4028234663852886e+38
    default_max = 3.4028234663852886e+38

Changing multiple settings at once
==================================

The `set` method should be used when multiple settings need to be
changed at once, as it allows for changes to both the value and
limits, such as changing the value to be 20 and the limits to 8 to 30:

    >>> p.val = 20
    ParameterErr: parameter model.eta has a maximum of 10
    >>> p.set(val=20, min=8, max=30)
    >>> print(p)
    val         = 20.0
    min         = 8.0
    max         = 30.0
    units       =
    frozen      = True
    link        = None
    default_val = 20.0
    default_min = -3.4028234663852886e+38
    default_max = 3.4028234663852886e+38

Linking parameters
==================

A parameter can be "linked" to another parameter, in which case the
value of the parameter is calculated based on the link expression,
such as being twice the other parameter:

    >>> q = Parameter('other', 'beta', 4)
    >>> p.val = 2 * p
    >>> print(p)
    val         = 8.0
    min         = 8.0
    max         = 30.0
    units       =
    frozen      = True
    link        = (2 * other.beta)
    default_val = 8.0
    default_min = -3.4028234663852886e+38
    default_max = 3.4028234663852886e+38

The `link` attribute stores the expression:

    >>> p.link
    <BinaryOpParameter '(2 * other.beta)'>

A ParameterErr exception will be raised whenever the linked expression
is evaluated and the result lies outside the parameters soft limits
(the `min` to `max` range). For this example, p must lie between 8 and
30 and so changing parameter q to a value of 3 will cause an error,
but only when parameter p is checked, not when the related parameter
(here q) is changed:

    >>> q.val = 3
    >>> print(p)
    ParameterErr: parameter model.eta has a minimum of 8
    >>> p.val
    ParameterErr: parameter model.eta has a minimum of 8

Resetting a parameter
=====================

The `reset` method is used to restore the parameter value and soft
limits to a known state. The idea is that if the values were changed
in a fit then `reset` will change them back to the values before a
fit.

"""

import logging
import numpy
from sherpa.utils import SherpaFloat, NoNewAttributesAfterInit
from sherpa.utils.err import ParameterErr
from sherpa.utils import formatting


warning = logging.getLogger(__name__).warning


__all__ = ('Parameter', 'CompositeParameter', 'ConstantParameter',
           'UnaryOpParameter', 'BinaryOpParameter')


# Default minimum and maximum magnitude for parameters
# tinyval = 1.0e-120
# hugeval = 1.0e+120
# tinyval = 1.0e-38
# hugeval = 1.0e+38
#
# Use FLT_TINY and FLT_MAX
tinyval = float(numpy.finfo(numpy.float32).tiny)
hugeval = float(numpy.finfo(numpy.float32).max)


def _make_set_limit(name):
    def _set_limit(self, val):
        val = SherpaFloat(val)
        # Ensure that we don't try to set any value that is outside
        # the hard parameter limits.
        if val < self._hard_min:
            raise ParameterErr('edge', self.fullname,
                               'hard minimum', self._hard_min)
        if val > self._hard_max:
            raise ParameterErr('edge', self.fullname,
                               'hard maximum', self._hard_max)

        # Ensure that we don't try to set a parameter range, such that
        # the minimum will be greater than the current parameter value,
        # or that the maximum will be less than the current parameter value.

        # But we only want to do this check *after* parameter has been
        # created and fully initialized; we are doing this check some time
        # *later*, when the user is trying to reset a parameter range
        # such that the new range will leave the current value
        # *outside* the new range.  We want to warn against and disallow that.

        # Due to complaints about having to rewrite existing user scripts,
        # downgrade the ParameterErr issued here to mere warnings.  Also,
        # set the value to the appropriate soft limit.
        if hasattr(self, "_NoNewAttributesAfterInit__initialized") and \
           self._NoNewAttributesAfterInit__initialized:
            if name == "_min" and (val > self.val):
                self.val = val
                warning(('parameter %s less than new minimum; %s reset to %g') % (self.fullname, self.fullname, self.val))
            if name == "_max" and (val < self.val):
                self.val = val
                warning(('parameter %s greater than new maximum; %s reset to %g') % (self.fullname, self.fullname, self.val))

        setattr(self, name, val)

    return _set_limit


def _make_unop(op, opstr):
    def func(self):
        return UnaryOpParameter(self, op, opstr)
    return func


def _make_binop(op, opstr):
    def func(self, rhs):
        return BinaryOpParameter(self, rhs, op, opstr)

    def rfunc(self, lhs):
        return BinaryOpParameter(lhs, self, op, opstr)

    return (func, rfunc)


class Parameter(NoNewAttributesAfterInit):
    """Represent a model parameter.

    Parameters
    ----------
    modelname : str
        The name of the model component containing the parameter.
    name : str
        The name of the parameter. It should be considered to be
        matched in a case-insensitive manner.
    val : number
        The default value for the parameter.
    min, max, hard_min, hard_max: number, optional
        The soft and hard limits for the parameter value.
    units : str, optional
        The units for the parameter value.
    frozen : bool, optional
        Does the parameter default to being frozen?
    alwaysfrozen : bool, optional
        If set then the parameter can never be thawed.
    hidden : bool, optional
        Should the parameter be included when displaying the model
        contents?
    aliases : None or list of str
        If not None then alternative names for the parameter (these
        are expected to be matched in a case-insensitive manner).

    """

    #
    # Read-only properties
    #

    def _get_alwaysfrozen(self):
        return self._alwaysfrozen
    alwaysfrozen = property(_get_alwaysfrozen,
                            doc='Is the parameter always frozen?')

    def _get_hard_min(self):
        return self._hard_min
    hard_min = property(_get_hard_min,
                        doc='The hard minimum of the parameter.\n\n' +
                        'See Also\n' +
                        '--------\n' +
                        'hard_max')

    def _get_hard_max(self):
        return self._hard_max
    hard_max = property(_get_hard_max,
                        doc='The hard maximum of the parameter.\n\n' +
                        'See Also\n' +
                        '--------\n' +
                        'hard_min')

    # 'val' property
    #
    # Note that _get_val has to check the parameter value when it
    # is a link, to ensure that it isn't outside the parameter's
    # min/max range. See issue #742.
    #
    def _get_val(self):
        if hasattr(self, 'eval'):
            return self.eval()
        if self.link is None:
            return self._val

        val = self.link.val
        if val < self.min:
            raise ParameterErr('edge', self.fullname, 'minimum', self.min)
        if val > self.max:
            raise ParameterErr('edge', self.fullname, 'maximum', self.max)

        return val

    def _set_val(self, val):
        if isinstance(val, Parameter):
            self.link = val
        else:
            # Reset link
            self.link = None

            # Validate new value
            val = SherpaFloat(val)
            if val < self.min:
                raise ParameterErr('edge', self.fullname, 'minimum', self.min)
            if val > self.max:
                raise ParameterErr('edge', self.fullname, 'maximum', self.max)

            self._val = val
            self._default_val = val

    val = property(_get_val, _set_val,
                   doc='The current value of the parameter.\n\n' +
                   'If the parameter is a link then it is possible that accessing\n' +
                   'the value will raise a ParamaterErr in cases where the link\n' +
                   'expression falls outside the soft limits of the parameter.\n\n' +
                   'See Also\n' +
                   '--------\n' +
                   'default_val, link, max, min')

    #
    # '_default_val' property
    #

    def _get_default_val(self):
        if hasattr(self, 'eval'):
            return self.eval()
        if self.link is not None:
            return self.link.default_val
        return self._default_val

    def _set_default_val(self, default_val):
        if isinstance(default_val, Parameter):
            self.link = default_val
        else:
            # Reset link
            self.link = None

            # Validate new value
            default_val = SherpaFloat(default_val)
            if default_val < self.min:
                raise ParameterErr('edge', self.fullname, 'minimum', self.min)
            if default_val > self.max:
                raise ParameterErr('edge', self.fullname, 'maximum', self.max)

            self._default_val = default_val

    default_val = property(_get_default_val, _set_default_val,
                           doc='The default value of the parameter.\n\n' +
                           'See Also\n' +
                           '--------\n' +
                           'val')

    #
    # 'min' and 'max' properties
    #

    def _get_min(self):
        return self._min
    min = property(_get_min, _make_set_limit('_min'),
                   doc='The minimum value of the parameter.\n\n' +
                   'The minimum must lie between the hard_min and hard_max limits.\n\n' +
                   'See Also\n' +
                   '--------\n' +
                   'max, val')

    def _get_max(self):
        return self._max
    max = property(_get_max, _make_set_limit('_max'),
                   doc='The maximum value of the parameter.\n\n' +
                   'The maximum must lie between the hard_min and hard_max limits.\n\n' +
                   'See Also\n' +
                   '--------\n' +
                   'min, val')

    #
    # 'default_min' and 'default_max' properties
    #

    def _get_default_min(self):
        return self._default_min
    default_min = property(_get_default_min, _make_set_limit('_default_min'))

    def _get_default_max(self):
        return self._default_max
    default_max = property(_get_default_max, _make_set_limit('_default_max'))

    #
    # 'frozen' property
    #

    def _get_frozen(self):
        if self.link is not None:
            return True
        return self._frozen

    def _set_frozen(self, val):
        val = bool(val)
        if self._alwaysfrozen and (not val):
            raise ParameterErr('alwaysfrozen', self.fullname)
        self._frozen = val
    frozen = property(_get_frozen, _set_frozen,
                      doc='Is the parameter currently frozen?\n\n' +
                      'Those parameters created with `alwaysfrozen` set can not\n' +
                      'be changed.\n\n' +
                      'See Also\n' +
                      '--------\n' +
                      'alwaysfrozen\n')

    #
    # 'link' property'
    #

    def _get_link(self):
        return self._link

    def _set_link(self, link):
        if link is not None:
            if self._alwaysfrozen:
                raise ParameterErr('frozennolink', self.fullname)
            if not isinstance(link, Parameter):
                raise ParameterErr('notlink')

            # Short cycles produce error
            # e.g. par = 2*par+3
            if self in link:
                raise ParameterErr('linkcycle')

            # Correctly test for link cycles in long trees.
            cycle = False
            ll = link
            while isinstance(ll, Parameter):
                if ll == self or self in ll:
                    cycle = True
                ll = ll.link

            # Long cycles are overwritten BUG #12287
            if cycle and isinstance(link, Parameter):
                link.link = None

        self._link = link
    link = property(_get_link, _set_link,
                    doc='The link expression to other parameters, if set.\n\n' +
                    'The link expression defines if the parameter is not\n' +
                    'a free parameter but is actually defined in terms of\n'
                    'other parameters.\n\n' +
                    'See Also\n' +
                    '--------\n' +
                    'val\n\n' +
                    'Examples\n' +
                    '--------\n\n' +
                    '>>> a = Parameter("mdl", "a", 2)\n' +
                    '>>> b = Parameter("mdl", "b", 1)\n' +
                    '>>> b.link = 10 - a\n' +
                    '>>> a.val\n' +
                    '2.0\n' +
                    '>>> b.val\n' +
                    '8.0\n')

    #
    # Methods
    #

    def __init__(self, modelname, name, val, min=-hugeval, max=hugeval,
                 hard_min=-hugeval, hard_max=hugeval, units='',
                 frozen=False, alwaysfrozen=False, hidden=False, aliases=None):
        self.modelname = modelname
        self.name = name
        self.fullname = '%s.%s' % (modelname, name)

        self._hard_min = SherpaFloat(hard_min)
        self._hard_max = SherpaFloat(hard_max)
        self.units = units

        self._alwaysfrozen = bool(alwaysfrozen)
        if alwaysfrozen:
            self._frozen = True
        else:
            self._frozen = frozen

        self.hidden = hidden

        # Set validated attributes.  Access them via their properties so that
        # validation takes place.
        self.min = min
        self.max = max
        self.val = val
        self.default_min = min
        self.default_max = max
        self.default_val = val
        self.link = None
        self._guessed = False

        self.aliases = [a.lower() for a in aliases] if aliases is not None else []

        NoNewAttributesAfterInit.__init__(self)

    def __iter__(self):
        return iter([self])

    def __repr__(self):
        r = "<%s '%s'" % (type(self).__name__, self.name)
        if self.modelname:
            r += " of model '%s'" % self.modelname
        r += '>'
        return r

    def __str__(self):
        if self.link is not None:
            linkstr = self.link.fullname
        else:
            linkstr = str(None)

        return (('val         = %s\n' +
                 'min         = %s\n' +
                 'max         = %s\n' +
                 'units       = %s\n' +
                 'frozen      = %s\n' +
                 'link        = %s\n'
                 'default_val = %s\n' +
                 'default_min = %s\n' +
                 'default_max = %s') %
                (str(self.val), str(self.min), str(self.max), self.units,
                 self.frozen, linkstr, str(self.default_val),
                 str(self.default_min), str(self.default_max)))

    # Support 'rich display' representations
    #
    def _val_to_html(self, v):
        """Convert a value to a string for use by the HTML output.

        The conversion to a string uses the Python defaults for most
        cases. The units field is currently used to determine whether
        to convert angles to factors of pi (this probably should be
        done by a subclass or mixture).
        """

        # The use of equality rather than some form of tolerance
        # should be okay here.
        #
        if v == hugeval:
            return 'MAX'
        elif v == -hugeval:
            return '-MAX'
        elif v == tinyval:
            return 'TINY'
        elif v == -tinyval:
            return '-TINY'

        if self.units in ['radian', 'radians']:
            tau = 2 * numpy.pi

            if v == tau:
                return '2&#960;'
            elif v == -tau:
                return '-2&#960;'
            elif v == numpy.pi:
                return '&#960;'
            elif v == -numpy.pi:
                return '-&#960;'

        return str(v)

    def _units_to_html(self):
        """Convert the unit to HTML.

        This is provided for future expansion/experimentation,
        and is not guaranteed to remain.
        """

        return self.units

    def _repr_html_(self):
        """Return a HTML (string) representation of the parameter
        """
        return html_parameter(self)

    # Unary operations
    __neg__ = _make_unop(numpy.negative, '-')
    __abs__ = _make_unop(numpy.absolute, 'abs')

    # Binary operations
    __add__, __radd__ = _make_binop(numpy.add, '+')
    __sub__, __rsub__ = _make_binop(numpy.subtract, '-')
    __mul__, __rmul__ = _make_binop(numpy.multiply, '*')
    __div__, __rdiv__ = _make_binop(numpy.divide, '/')
    __floordiv__, __rfloordiv__ = _make_binop(numpy.floor_divide, '//')
    __truediv__, __rtruediv__ = _make_binop(numpy.true_divide, '/')
    __mod__, __rmod__ = _make_binop(numpy.remainder, '%')
    __pow__, __rpow__ = _make_binop(numpy.power, '**')

    def freeze(self):
        """Set the `frozen` attribute for the parameter.

        See Also
        --------
        thaw
        """
        self.frozen = True

    def thaw(self):
        """Unset the `frozen` attribute for the parameter.

        See Also
        --------
        frozen
        """
        self.frozen = False

    def unlink(self):
        """Remove any link to other parameters."""
        self.link = None

    def reset(self):
        """Reset the parameter value and limits to their default values."""
        # circumvent the attr checks for simplicity, as the defaults have
        # already passed (defaults either set by user or through self.set).
        if self._guessed:
            # TODO: It is not clear the logic for when _guessed gets set
            # (see sherpa.utils.param_apply_limits) so we do not
            # describe the logic in the docstring yet.
            self._min = self.default_min
            self._max = self.default_max
            self._guessed = False
        self._val = self.default_val

    def set(self, val=None, min=None, max=None, frozen=None,
            default_val=None, default_min=None, default_max=None):
        """Change a parameter setting.

        Parameters
        ----------
        val : number or None, optional
            The new parameter value.
        min, max : number or None, optional
            The new parameter range.
        frozen : bool or None, optional
            Should the frozen flag be set?
        default_val : number or None, optional
            The new default parameter value.
        default_min, default_max : number or None, optional
            The new default parameter limits.
        """

        # The validation checks are left to the individual properties.
        # However, it means that the logic here has to handle cases
        # of 'set(val=1, min=0, max=2)' but a value of 1 lies
        # outside the min/max of the object before the call, and
        # we don't want the call to fail because of this.
        #
        if max is not None and max > self.max:
            self.max = max
        if default_max is not None and default_max > self.default_max:
            self.default_max = default_max

        if min is not None and min < self.min:
            self.min = min
        if default_min is not None and default_min < self.default_min:
            self.default_min = default_min

        if val is not None:
            self.val = val
        if default_val is not None:
            self.default_val = default_val

        if min is not None:
            self.min = min
        if max is not None:
            self.max = max

        if default_min is not None:
            self.default_min = default_min
        if default_max is not None:
            self.default_max = default_max

        if frozen is not None:
            self.frozen = frozen


class CompositeParameter(Parameter):
    """Represent a parameter with composite parts.

    This is the base class for representing expressions that combine
    multiple parameters and values.

    Parameters
    ----------
    name : str
        The name for the collection.
    parts : sequence of Parameter objects
        The parameters.

    Notes
    -----
    Composite parameters can be iterated through to find their
    components:

       >>> p = Parameter('m', 'p', 2)
       >>> q = Parameter('m', 'q', 4)
       >>> c = (p + q) / 2
       >>> c
       <BinaryOpParameter '((m.p + m.q) / 2)'>
       >>> for cpt in c:
       ...     print(type(cpt))
       ...
       <class 'BinaryOpParameter'>
       <class 'Parameter'>
       <class 'Parameter'>
       <class 'ConstantParameter'>

    """

    def __init__(self, name, parts):
        self.parts = tuple(parts)
        Parameter.__init__(self, '', name, 0.0)
        self.fullname = name

    def __iter__(self):
        return iter(self._get_parts())

    def _get_parts(self):
        parts = []

        for p in self.parts:
            # A CompositeParameter should not hold a reference to itself
            assert (p is not self), (("'%s' object holds a reference to " +
                                      "itself") % type(self).__name__)

            parts.append(p)
            if isinstance(p, CompositeParameter):
                parts.extend(p._get_parts())

        # FIXME: do we want to remove duplicate components from parts?

        return parts

    def eval(self):
        """Evaluate the composite expression."""
        raise NotImplementedError


class ConstantParameter(CompositeParameter):
    """Represent an expression containing 1 or more parameters."""

    def __init__(self, value):
        self.value = SherpaFloat(value)
        CompositeParameter.__init__(self, str(value), ())

    def eval(self):
        return self.value


class UnaryOpParameter(CompositeParameter):
    """Apply an operator to a parameter expression.

    Parameters
    ----------
    arg : Parameter instance
    op : function reference
        The ufunc to apply to the parameter value.
    opstr : str
        The symbol used to represent the operator.

    See Also
    --------
    BinaryOpParameter
    """

    def __init__(self, arg, op, opstr):
        self.arg = arg
        self.op = op
        CompositeParameter.__init__(self,
                                    '%s(%s)' % (opstr, self.arg.fullname),
                                    (self.arg,))

    def eval(self):
        return self.op(self.arg.val)


class BinaryOpParameter(CompositeParameter):
    """Combine two parameter expressions.

    Parameters
    ----------
    lhs : Parameter instance
        The left-hand side of the expression.
    rhs : Parameter instance
        The right-hand side of the expression.
    op : function reference
        The ufunc to apply to the two parameter values.
    opstr : str
        The symbol used to represent the operator.

    See Also
    --------
    UnaryOpParameter
    """

    @staticmethod
    def wrapobj(obj):
        if isinstance(obj, Parameter):
            return obj
        return ConstantParameter(obj)

    def __init__(self, lhs, rhs, op, opstr):
        self.lhs = self.wrapobj(lhs)
        self.rhs = self.wrapobj(rhs)
        self.op = op
        CompositeParameter.__init__(self, '(%s %s %s)' %
                                    (self.lhs.fullname, opstr,
                                     self.rhs.fullname), (self.lhs, self.rhs))

    def eval(self):
        return self.op(self.lhs.val, self.rhs.val)


# Notebook representation
#
def html_parameter(par):
    """Construct the HTML to display the parameter."""

    # Note that as this is a specialized table we do not use
    # formatting.html_table but create everything directly.
    #
    def addtd(val):
        "Use the parameter to convert to HTML"
        return '<td>{}</td>'.format(par._val_to_html(val))

    out = '<table class="model">'
    out += '<thead><tr>'
    cols = ['Component', 'Parameter', 'Thawed', 'Value',
            'Min', 'Max', 'Units']
    for col in cols:
        out += '<th>{}</th>'.format(col)

    out += '</tr></thead><tbody><tr>'

    out += '<th class="model-odd">{}</th>'.format(par.modelname)
    out += '<td>{}</td>'.format(par.name)

    linked = par.link is not None
    if linked:
        out += "<td>linked</td>"
    else:
        out += '<td><input disabled type="checkbox"'
        if not par.frozen:
            out += ' checked'
        out += '></input></td>'

    out += addtd(par.val)
    if linked:
        # 8592 is single left arrow
        # 8656 is double left arrow
        #
        val = formatting.clean_bracket(par.link.fullname)
        out += '<td colspan="2">&#8656; {}</td>'.format(val)

    else:
        out += addtd(par.min)
        out += addtd(par.max)

    out += '<td>{}</td>'.format(par._units_to_html())
    out += '</tr>'

    out += '</tbody></table>'

    ls = ['<details open><summary>Parameter</summary>' + out + '</details>']
    return formatting.html_from_sections(par, ls)

#!/usr/bin/env python
#
# paths2openscad.py
#
# This is an Inkscape extension to output paths to extruded OpenSCAD polygons
# The Inkscape objects must first be converted to paths (Path > Object to
# Path). Some paths may not work well -- the paths have to be polygons.  As
# such, paths derived from text may meet with mixed results.

# Written by Daniel C. Newman ( dan dot newman at mtbaldy dot us )
# 10 June 2012
#
# 15 June 2012
#   Updated by Dan Newman to handle a single level of polygon nesting.
#   This is sufficient to handle most fonts.
#   If you want to nest two polygons, combine them into a single path
#   within Inkscape with "Path > Combine Path".
#
# 15 August 2014
#   Updated by Josef Skladanka to automatically set extruded heights
#
# 2017-03-11, juergen@fabmail.org
#   0.12 parse svg width="400mm" correctly. Came out downscaled by 3...
#
# 2017-04-08, juergen@fabmail.org
#   0.13 allow letter 'a' prefix on height values for anti-matter.
#        All anti-matter objects are subtracted from all normal objects.
#        raise: Offset along Z axis, to make cut-outs and balconies.
#        Refactored object_merge_extrusion_values() from convertPath().
#        Inheriting extrusion values from enclosing groups.
#
# 2017-04-10, juergen@fabmail.org
#   0.14 Started merging V7 outline mode by Neon22.
#        (http://www.thingiverse.com/thing:1065500)
#        Toplevel object from http://www.thingiverse.com/thing:1286041
#        is already included.
#
# 2017-04-16, juergen@fabmail.org
#   0.15 Fixed https://github.com/fablabnbg/inkscape-paths2openscad/
#        issues/1#issuecomment-294257592
#        Line width of V7 code became a minimum line width,
#        rendering is now based on stroke-width
#        Refactored LengthWithUnit() from getLength()
#        Finished merge with v7 code.
#        Subpath in subpath are now handled very nicely.
#        Added msg_extrude_by_hull_and_paths() outline mode with nested paths.
#
# 2017-06-12, juergen@fabmail.org
#   0.16 Feature added: scale: XXX to taper the object while extruding.

# 2017-06-15, juergen@fabmail.org
#   0.17 scale is now centered on each path. and supports an optional second
#        value for explicit Y scaling. Renamed the autoheight command line
#        option to 'parsedesc' with default true. Renamed dict auto to
#        extrusion. Rephrased all prose to refer to extrusion syntax rather
#        than auto height.
# 2017-06-18, juergen@fabmail.org
#   0.18 pep8 relaxed. all hard 80 cols line breaks removed.
#   Refactored the commands into a separate tab in the inx.
#   Added 'View in OpenSCAD' feature with pidfile for single instance.
#
# 2017-08-10, juergen@fabmail.org
#   0.19 fix style="" elements.
#
# 2017-11-14, juergen@fabmail.org
#   0.20 do not traverse into objects with style="display:none"
#       some precondition checks had 'pass' but should have 'continue'.
#
# 2018-01-21, juergen@fabmail.org
#   0.21 start a new openscad instance if the command has changed.
#
# 2018-01-27, juergen@fabmail.org
#   0.22 command comparison fixed. do not use 0.21 !
#
# CAUTION: keep the version numnber in sync with paths2openscad.inx about page

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os
import sys
import os.path
import inkex
import simplepath
import simpletransform
import cubicsuperpath
import cspsubdiv
import bezmisc
import re
import string
import tempfile
import gettext

DEFAULT_WIDTH = 100
DEFAULT_HEIGHT = 100
# Parse all these as 56.7 mm height:
#  "path1234_56_7_mm", "pat1234____57.7mm", "path1234_57.7__mm"
RE_AUTO_HEIGHT_ID   = re.compile(r".*?_+([aA]?\d+(?:[_\.]\d+)?)_*mm$")
RE_AUTO_HEIGHT_DESC = re.compile(r"^(?:ht|[Hh]eight):\s*([aA]?\d+(?:\.\d+)?) ?mm$", re.MULTILINE)
RE_AUTO_SCALE_DESC  = re.compile(r"^(?:sc|[Ss]cale):\s*(\d+(?:\.\d+)?(?: ?, ?\d+(?:\.\d+)?)?) ?%$", re.MULTILINE)
RE_AUTO_RAISE_DESC  = re.compile(r"^(?:[Rr]aise|[Oo]ffset):\s*(\d+(?:\.\d+)?) ?mm$", re.MULTILINE)
DESC_TAGS = ['desc', inkex.addNS('desc', 'svg')]

# CAUTION: keep these defaults in sync with paths2openscad.inx
INX_SCADVIEW           = os.getenv('INX_SCADVIEW',           "openscad '{NAME}.scad'")
INX_SCAD2STL           = os.getenv('INX_SCAD2STL',           "openscad '{NAME}.scad' -o '{NAME}.stl'")
INX_STL_POSTPROCESSING = os.getenv('INX_STL_POSTPROCESSING', "cura '{NAME}.stl' &")


def IsProcessRunning(pid):
    '''
    Windows code from https://stackoverflow.com/questions/7647167/check-if-a-process-is-running-in-python-in-linux-unix
    '''
    sys_platform = sys.platform.lower()
    if sys_platform.startswith('win'):
        import subprocess

        ps = subprocess.Popen(r'tasklist.exe /NH /FI "PID eq %d"' % (pid), shell=True, stdout=subprocess.PIPE)
        output = ps.stdout.read()
        ps.stdout.close()
        ps.wait()
        if processId in output:
            return True
        return False
    else:
        # OSX sys_platform.startswith('darwin'):
        # and Linux
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def parseLengthWithUnits(str, default_unit='px'):
    '''
    Parse an SVG value which may or may not have units attached
    This version is greatly simplified in that it only allows: no units,
    units of px, and units of %.  Everything else, it returns None for.
    There is a more general routine to consider in scour.py if more
    generality is ever needed.
    With inkscape 0.91 we need other units too: e.g. svg:width="400mm"
    '''

    u = default_unit
    s = str.strip()
    if s[-2:] in ('px', 'pt', 'pc', 'mm', 'cm', 'in', 'ft'):
        u = s[-2:]
        s = s[:-2]
    elif s[-1:] in ('m', '%'):
        u = s[-1:]
        s = s[:-1]

    try:
        v = float(s)
    except:
        return None, None

    return v, u


def pointInBBox(pt, bbox):
    '''
    Determine if the point pt=[x, y] lies on or within the bounding
    box bbox=[xmin, xmax, ymin, ymax].
    '''

    # if ( x < xmin ) or ( x > xmax ) or ( y < ymin ) or ( y > ymax )
    if (pt[0] < bbox[0]) or (pt[0] > bbox[1]) or (pt[1] < bbox[2]) or (pt[1] > bbox[3]):
        return False
    else:
        return True


def bboxInBBox(bbox1, bbox2):
    '''
    Determine if the bounding box bbox1 lies on or within the
    bounding box bbox2.  NOTE: we do not test for strict enclosure.

    Structure of the bounding boxes is

    bbox1 = [ xmin1, xmax1, ymin1, ymax1 ]
    bbox2 = [ xmin2, xmax2, ymin2, ymax2 ]
    '''

    # if ( xmin1 < xmin2 ) or ( xmax1 > xmax2 ) or
    # ( ymin1 < ymin2 ) or ( ymax1 > ymax2 )

    if (bbox1[0] < bbox2[0]) or (bbox1[1] > bbox2[1]) or (bbox1[2] < bbox2[2]) or (bbox1[3] > bbox2[3]):
        return False
    else:
        return True


def pointInPoly(p, poly, bbox=None):
    '''
    Use a ray casting algorithm to see if the point p = [x, y] lies within
    the polygon poly = [[x1,y1],[x2,y2],...].  Returns True if the point
    is within poly, lies on an edge of poly, or is a vertex of poly.
    '''

    if (p is None) or (poly is None):
        return False

    # Check to see if the point lies outside the polygon's bounding box
    if bbox is not None:
        if not pointInBBox(p, bbox):
            return False

    # Check to see if the point is a vertex
    if p in poly:
        return True

    # Handle a boundary case associated with the point
    # lying on a horizontal edge of the polygon
    x = p[0]
    y = p[1]
    p1 = poly[0]
    p2 = poly[1]
    for i in range(len(poly)):
        if i != 0:
            p1 = poly[i - 1]
            p2 = poly[i]
        if (y == p1[1]) and (p1[1] == p2[1]) and (x > min(p1[0], p2[0])) and (x < max(p1[0], p2[0])):
            return True

    n = len(poly)
    inside = False

    p1_x, p1_y = poly[0]
    for i in range(n + 1):
        p2_x, p2_y = poly[i % n]
        if y > min(p1_y, p2_y):
            if y <= max(p1_y, p2_y):
                if x <= max(p1_x, p2_x):
                    if p1_y != p2_y:
                        intersect = p1_x + (y - p1_y) * (p2_x - p1_x) / (p2_y - p1_y)
                        if x <= intersect:
                            inside = not inside
                    else:
                        inside = not inside
        p1_x, p1_y = p2_x, p2_y

    return inside


def polyInPoly(poly1, bbox1, poly2, bbox2):
    '''
    Determine if polygon poly2 = [[x1,y1],[x2,y2],...]
    contains polygon poly1.

    The bounding box information, bbox=[xmin, xmax, ymin, ymax]
    is optional.  When supplied it can be used to perform rejections.
    Note that one bounding box containing another is not sufficient
    to imply that one polygon contains another.  It's necessary, but
    not sufficient.
    '''

    # See if poly1's bboundin box is NOT contained by poly2's bounding box
    # if it isn't, then poly1 cannot be contained by poly2.

    if (bbox1 is not None) and (bbox2 is not None):
        if not bboxInBBox(bbox1, bbox2):
            return False

    # To see if poly1 is contained by poly2, we need to ensure that each
    # vertex of poly1 lies on or within poly2

    for p in poly1:
        if not pointInPoly(p, poly2, bbox2):
            return False

    # Looks like poly1 is contained on or in Poly2

    return True


def subdivideCubicPath(sp, flat, i=1):
    '''
    [ Lifted from eggbot.py with impunity ]

    Break up a bezier curve into smaller curves, each of which
    is approximately a straight line within a given tolerance
    (the "smoothness" defined by [flat]).

    This is a modified version of cspsubdiv.cspsubdiv(): rewritten
    because recursion-depth errors on complicated line segments
    could occur with cspsubdiv.cspsubdiv().
    '''

    while True:
        while True:
            if i >= len(sp):
                return

            p0 = sp[i - 1][1]
            p1 = sp[i - 1][2]
            p2 = sp[i][0]
            p3 = sp[i][1]

            b = (p0, p1, p2, p3)

            if cspsubdiv.maxdist(b) > flat:
                break

            i += 1

        one, two = bezmisc.beziersplitatt(b, 0.5)
        sp[i - 1][2] = one[1]
        sp[i][0] = two[2]
        p = [one[2], one[3], two[1]]
        sp[i:1] = [p]


def msg_linear_extrude(id, prefix):
    msg = '    translate (%s_%d_center) linear_extrude(height=h, convexity=10, scale=0.01*s)\n' + \
          '      translate (-%s_%d_center) polygon(%s_%d_points);\n'
    return msg % (id, prefix, id, prefix, id, prefix)


def msg_linear_extrude_by_paths(id, prefix):
    msg = '    translate (%s_%d_center) linear_extrude(height=h, convexity=10, scale=0.01*s)\n' + \
          '      translate (-%s_%d_center) polygon(%s_%d_points, %s_%d_paths);\n'
    return msg % (id, prefix, id, prefix, id, prefix, id, prefix)


def msg_extrude_by_hull(id, prefix):
    msg = '    for (t = [0: len(%s_%d_points)-2]) {\n' % (id, prefix) + \
          '      hull() {\n' + \
          '        translate(%s_%d_points[t]) \n' % (id, prefix) + \
          '          cylinder(h=h, r=w/2, $fn=res);\n' + \
          '        translate(%s_%d_points[t + 1]) \n' % (id, prefix) + \
          '          cylinder(h=h, r=w/2, $fn=res);\n' + \
          '      }\n' + \
          '    }\n'
    return msg


def msg_extrude_by_hull_and_paths(id, prefix):
    msg = '    for (p = [0: len(%s_%d_paths)-1]) {\n' % (id, prefix) + \
          '      pp = %s_%d_paths[p];\n' % (id, prefix) + \
          '      for (t = [0: len(pp)-2]) {\n' + \
          '        hull() {\n' + \
          '          translate(%s_%d_points[pp[t]])\n' % (id, prefix) + \
          '            cylinder(h=h, r=w/2, $fn=res);\n' + \
          '          translate(%s_%d_points[pp[t+1]])\n' % (id, prefix) + \
          '            cylinder(h=h, r=w/2, $fn=res);\n' + \
          '        }\n' + \
          '      }\n' + \
          '    }\n'
    return msg


class OpenSCAD(inkex.Effect):
    def __init__(self):

        inkex.localize()    # does not help for localizing my *.inx file
        inkex.Effect.__init__(self)

        self.OptionParser.add_option(
            "--tab",  # NOTE: value is not used.
            action="store", type="string", dest="tab", default="splash",
            help="The active tab when Apply was pressed")

        self.OptionParser.add_option(
            '--smoothness', dest='smoothness', type='float', default=float(0.2), action='store',
            help='Curve smoothing (less for more)')

        self.OptionParser.add_option(
            '--height', dest='height', type='string', default='5', action='store',
            help='Height (mm)')

        self.OptionParser.add_option(
            '--min_line_width', dest='min_line_width', type='float', default=float(1), action='store',
            help='Line width for non closed curves (mm)')

        self.OptionParser.add_option(
            "-n", '--line_fn', dest='line_fn', type='int', default=int(4), action='store',
            help='Line width precision ($fn when constructing hull)')

        self.OptionParser.add_option(
            "--force_line", action="store", type="inkbool", dest="force_line", default=False,
            help="Force outline mode.")

        self.OptionParser.add_option(
            '--fname', dest='fname', type='string', default='{NAME}.scad', action='store',
            help='openSCAD output file derived from the svg file name.')

        self.OptionParser.add_option(
            '--parsedesc', dest='parsedesc', type='string', default='true', action='store',
            help='Parse height and other parameters from object descriptions')

        self.OptionParser.add_option(
            '--scadview', dest='scadview', type='string', default='false', action='store',
            help='Open the file with openscad ( details see --scadviewcmd option )')
        self.OptionParser.add_option(
            '--scadviewcmd', dest='scadviewcmd', type='string', default=INX_SCADVIEW, action='store',
            help='Command used start an openscad viewer. Use {SCAD} for the openSCAD input.')

        self.OptionParser.add_option(
            '--scad2stl', dest='scad2stl', type='string', default='false', action='store',
            help='Also convert to STL ( details see --scad2stlcmd option )')
        self.OptionParser.add_option(
            '--scad2stlcmd', dest='scad2stlcmd', type='string', default=INX_SCAD2STL, action='store',
            help='Command used to convert to STL. You can use {NAME}.scad for the openSCAD file to read and ' +
                 '{NAME}.stl for the STL file to write.')

        self.OptionParser.add_option(
            '--stlpost', dest='stlpost', type='string', default='false', action='store',
            help='Start e.g. a slicer. This implies the --scad2stl option. ( see --stlpostcmd )')
        self.OptionParser.add_option(
            '--stlpostcmd', dest='stlpostcmd', type='string', default=INX_STL_POSTPROCESSING, action='store',
            help='Command used for post processing an STL file (typically a slicer). You can use {NAME}.stl for the STL file.')

        self.dpi = 90.0                # factored out for inkscape-0.92
        self.px_used = False           # raw px unit depends on correct dpi.
        self.cx = float(DEFAULT_WIDTH)  / 2.0
        self.cy = float(DEFAULT_HEIGHT) / 2.0
        self.xmin, self.xmax = (1.0E70, -1.0E70)
        self.ymin, self.ymax = (1.0E70, -1.0E70)

        # Dictionary of paths we will construct.  It's keyed by the SVG node
        # it came from.  Such keying isn't too useful in this specific case,
        # but it can be useful in other applications when you actually want
        # to go back and update the SVG document
        self.paths = {}

        # Output file handling
        self.call_list = []
        self.call_list_neg = []        # anti-matter (holes via difference)
        self.pathid = int(0)

        # Output file
        self.f = None

        # For handling an SVG viewbox attribute, we will need to know the
        # values of the document's <svg> width and height attributes as well
        # as establishing a transform from the viewbox to the display.

        self.docWidth = float(DEFAULT_WIDTH)
        self.docHeight = float(DEFAULT_HEIGHT)
        self.docTransform = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

        # Dictionary of warnings issued.  This to prevent from warning
        # multiple times about the same problem
        self.warnings = {}

    def getLength(self, name, default):

        '''
        Get the <svg> attribute with name "name" and default value "default"
        Parse the attribute into a value and associated units.  Then, accept
        units of cm, ft, in, m, mm, pc, or pt.  Convert to pixels.

        Note that SVG defines 90 px = 1 in = 25.4 mm.
        Note: Since inkscape 0.92 we use the CSS standard of 96 px = 1 in.
        '''
        str = self.document.getroot().get(name)
        if str:
            return self.LengthWithUnit(str)
        else:
            # No width specified; assume the default value
            return float(default)

    def LengthWithUnit(self, strn, default_unit='px'):
        v, u = parseLengthWithUnits(strn, default_unit)
        if v is None:
            # Couldn't parse the value
            return None
        elif (u == 'mm'):
            return float(v) * (self.dpi / 25.4)
        elif (u == 'cm'):
            return float(v) * (self.dpi * 10.0 / 25.4)
        elif (u == 'm'):
            return float(v) * (self.dpi * 1000.0 / 25.4)
        elif (u == 'in'):
            return float(v) * self.dpi
        elif (u == 'ft'):
            return float(v) * 12.0 * self.dpi
        elif (u == 'pt'):
            # Use modern "Postscript" points of 72 pt = 1 in instead
            # of the traditional 72.27 pt = 1 in
            return float(v) * (self.dpi / 72.0)
        elif (u == 'pc'):
            return float(v) * (self.dpi / 6.0)
        elif (u == 'px'):
            self.px_used = True
            return float(v)
        else:
            # Unsupported units
            return None

    def getDocProps(self):

        '''
        Get the document's height and width attributes from the <svg> tag.
        Use a default value in case the property is not present or is
        expressed in units of percentages.
        '''

        inkscape_version = self.document.getroot().get(
            "{http://www.inkscape.org/namespaces/inkscape}version")
        sodipodi_docname = self.document.getroot().get(
            "{http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd}docname")
        if sodipodi_docname is None:
            sodipodi_docname = "inkscape"
        self.basename = re.sub(r"\.SVG", "", sodipodi_docname, flags=re.I)
        # a simple 'inkscape:version' does not work here. sigh....
        #
        # BUG:
        # inkscape 0.92 uses 96 dpi, inkscape 0.91 uses 90 dpi.
        # From inkscape 0.92 we receive an svg document that has
        # both inkscape:version and sodipodi:docname if the document
        # was ever saved before. If not, both elements are missing.
        #
        import lxml.etree
        # inkex.errormsg(lxml.etree.tostring(self.document.getroot()))
        if inkscape_version:
            '''
            inkscape:version="0.91 r"
            inkscape:version="0.92.0 ..."
           See also https://github.com/fablabnbg/paths2openscad/issues/1
            '''
            # inkex.errormsg("inkscape:version="+inkscape_version)
            m = re.match(r"(\d+)\.(\d+)", inkscape_version)
            if m:
                if int(m.group(1)) > 0 or int(m.group(2)) > 91:
                    self.dpi = 96                # 96dpi since inkscape 0.92
                    # inkex.errormsg("switching to 96 dpi")

        # BUGFIX https://github.com/fablabnbg/inkscape-paths2openscad/issues/1
        # get height and width after dpi. This is needed for e.g. mm units.
        self.docHeight = self.getLength('height', DEFAULT_HEIGHT)
        self.docWidth = self.getLength('width', DEFAULT_WIDTH)

        if (self.docHeight is None) or (self.docWidth is None):
            return False
        else:
            return True

    def handleViewBox(self):

        '''
        Set up the document-wide transform in the event that the document has
        an SVG viewbox
        '''

        if self.getDocProps():
            viewbox = self.document.getroot().get('viewBox')
            if viewbox:
                vinfo = viewbox.strip().replace(',', ' ').split(' ')
                if (vinfo[2] != 0) and (vinfo[3] != 0):
                    sx = self.docWidth  / float(vinfo[2])
                    sy = self.docHeight / float(vinfo[3])
                    self.docTransform = simpletransform.parseTransform('scale(%f,%f)' % (sx, sy))

    def getPathVertices(self, path, node=None, transform=None):

        '''
        Decompose the path data from an SVG element into individual
        subpaths, each subpath consisting of absolute move to and line
        to coordinates.  Place these coordinates into a list of polygon
        vertices.
        '''

        if (not path) or (len(path) == 0):
            # Nothing to do
            return None

        # parsePath() may raise an exception.  This is okay
        sp = simplepath.parsePath(path)
        if (not sp) or (len(sp) == 0):
            # Path must have been devoid of any real content
            return None

        # Get a cubic super path
        p = cubicsuperpath.CubicSuperPath(sp)
        if (not p) or (len(p) == 0):
            # Probably never happens, but...
            return None

        if transform:
            simpletransform.applyTransformToPath(transform, p)

        # Now traverse the cubic super path
        subpath_list = []
        subpath_vertices = []

        for sp in p:

            # We've started a new subpath
            # See if there is a prior subpath and whether we should keep it
            if len(subpath_vertices):
                subpath_list.append([subpath_vertices, [sp_xmin, sp_xmax, sp_ymin, sp_ymax]])

            subpath_vertices = []
            subdivideCubicPath(sp, float(self.options.smoothness))

            # Note the first point of the subpath
            first_point = sp[0][1]
            subpath_vertices.append(first_point)
            sp_xmin = first_point[0]
            sp_xmax = first_point[0]
            sp_ymin = first_point[1]
            sp_ymax = first_point[1]

            n = len(sp)

            # Traverse each point of the subpath
            for csp in sp[1:n]:

                # Append the vertex to our list of vertices
                pt = csp[1]
                subpath_vertices.append(pt)

                # Track the bounding box of this subpath
                if pt[0] < sp_xmin:
                    sp_xmin = pt[0]
                elif pt[0] > sp_xmax:
                    sp_xmax = pt[0]
                if pt[1] < sp_ymin:
                    sp_ymin = pt[1]
                elif pt[1] > sp_ymax:
                    sp_ymax = pt[1]

            # Track the bounding box of the overall drawing
            # This is used for centering the polygons in OpenSCAD around the
            # (x,y) origin
            if sp_xmin < self.xmin:
                self.xmin = sp_xmin
            if sp_xmax > self.xmax:
                self.xmax = sp_xmax
            if sp_ymin < self.ymin:
                self.ymin = sp_ymin
            if sp_ymax > self.ymax:
                self.ymax = sp_ymax

        # Handle the final subpath
        if len(subpath_vertices):
            subpath_list.append([subpath_vertices, [sp_xmin, sp_xmax, sp_ymin, sp_ymax]])

        if len(subpath_list) > 0:
            self.paths[node] = subpath_list

    def getPathStyle(self, node):
        style = node.get('style', '')
        ret = {}
        # fill:none;fill-rule:evenodd;stroke:#000000;stroke-width:10;stroke-linecap:butt;stroke-linejoin:miter;stroke-miterlimit:4;stroke-dasharray:none;stroke-opacity:1
        for elem in style.split(';'):
            if len(elem):
                try:
                    (key, val) = elem.strip().split(':')
                except:
                    print >> sys.stderr, "unparsable element '{1}' in style '{0}'".format(elem, style)
                ret[key] = val
        return ret

    def convertPath(self, node):

        def object_merge_extrusion_values(extrusion, node):

            """ Parser for description and ID fields for extrusion parameters.
                This recurse into parents, to inherit values from enclosing
                groups.
            """
            p = node.getparent()
            if p is not None and p.tag in (inkex.addNS('g', 'svg'), 'g'):
                object_merge_extrusion_values(extrusion, p)

            # let the node override inherited values
            rawid = node.get('id', '')
            if rawid is not None:
                height = RE_AUTO_HEIGHT_ID.findall(rawid)
                if height:
                    extrusion['height'] = height[-1].replace("_", ".")
            # let description contents override id contents.
            for tagname in DESC_TAGS:
                desc_node = node.find("./%s" % tagname)
                if desc_node is not None:
                    height = RE_AUTO_HEIGHT_DESC.findall(desc_node.text)
                    if height:
                        extrusion['height'] = height[-1]
                    zscale = RE_AUTO_SCALE_DESC.findall(desc_node.text)
                    if zscale:
                        if ',' in zscale[-1]:
                            extrusion['scale'] = '[' + zscale[-1] + ']'
                        else:
                            extrusion['scale'] = zscale[-1]
                    zraise = RE_AUTO_RAISE_DESC.findall(desc_node.text)
                    if zraise:
                        extrusion['raise'] = zraise[-1]
            if extrusion['height'][0] in ('a', 'A'):
                extrusion['neg'] = True
                extrusion['height'] = extrusion['height'][1:]
            # END object_merge_extrusion_values

        path = self.paths[node]
        if (path is None) or (len(path) == 0):
            return

        # Determine which polys contain which

        contains = [[] for i in xrange(len(path))]
        contained_by = [[] for i in xrange(len(path))]

        for i in range(0, len(path)):
            for j in range(i + 1, len(path)):
                if polyInPoly(path[j][0], path[j][1], path[i][0], path[i][1]):
                    # subpath i contains subpath j
                    contains[i].append(j)
                    # subpath j is contained in subpath i
                    contained_by[j].append(i)
                elif polyInPoly(path[i][0], path[i][1], path[j][0], path[j][1]):
                    # subpath j contains subpath i
                    contains[j].append(i)
                    # subpath i is containd in subpath j
                    contained_by[i].append(j)

        # Generate an OpenSCAD module for this path
        rawid = node.get('id', '')
        if (rawid is None) or (rawid == ''):
            id = str(self.pathid) + 'x'
            rawid = id
            self.pathid += 1
        else:
            id = re.sub('[^A-Za-z0-9_]+', '', rawid)

        style = self.getPathStyle(node)
        stroke_width = style.get('stroke-width', '1')

        # FIXME: works with document units == 'mm', but otherwise untested..
        stroke_width_mm = self.LengthWithUnit(stroke_width, default_unit='mm')
        stroke_width_mm = str(stroke_width_mm * 25.4 / self.dpi)  # px to mm
        fill_color = style.get('fill', '#FFF')
        if (fill_color == 'none'):
            filled = False
        else:
            filled = True
        if (filled is False and style.get('stroke', 'none') == 'none'):
            inkex.errormsg("WARNING: " + rawid + " has fill:none and stroke:none, object ignored.")
            return

        # inkex.errormsg('filled='+str(filled))
        # inkex.errormsg(id+': style='+str(style))

        # #### global data for msg_*() functions. ####
        # fold subpaths into a single list of points and index paths.
        prefix = 0
        for i in range(0, len(path)):
            # Skip this subpath if it is contained by another one
            if len(contained_by[i]) != 0:
                continue
            subpath = path[i][0]
            bbox = path[i][1]   # [xmin, xmax, ymin, ymax]

            #
            polycenter = id + '_' + str(prefix) + '_center = [%f,%f]' % ((bbox[0] + bbox[1]) * .5 - self.cx,
                                                                         (bbox[2] + bbox[3]) * .5 - self.cy)
            polypoints = id + '_' + str(prefix) + '_points = ['
            # polypaths = [[0,1,2], [3,4,5]]   # this path is two triangle
            polypaths = id + '_' + str(prefix) + '_paths = [['
            if len(contains[i]) == 0:
                # This subpath does not contain any subpaths
                for point in subpath:
                    polypoints += '[%f,%f],' % ((point[0] - self.cx),
                                                (point[1] - self.cy))
                polypoints = polypoints[:-1]
                polypoints += '];\n'
                self.f.write(polycenter + ";\n")
                self.f.write(polypoints)
                prefix += 1
            else:
                # This subpath contains other subpaths
                # collect all points into polypoints
                # also collect the indices into polypaths
                for point in subpath:
                    polypoints += '[%f,%f],' % ((point[0] - self.cx),
                                                (point[1] - self.cy))
                count = len(subpath)
                for k in range(0, count):
                    polypaths += '%d,' % (k)
                polypaths = polypaths[:-1] + '],\n\t\t\t\t['
                # The nested paths
                for j in contains[i]:
                    for point in path[j][0]:
                        polypoints += '[%f,%f],' % ((point[0] - self.cx),
                                                    (point[1] - self.cy))
                    for k in range(count, count + len(path[j][0])):
                        polypaths += '%d,' % k
                    count += len(path[j][0])
                    polypaths = polypaths[:-1] + '],\n\t\t\t\t['
                polypoints = polypoints[:-1]
                polypoints += '];\n'
                polypaths = polypaths[:-7] + '];\n'
                # write the polys and paths
                self.f.write(polycenter + ";\n")
                self.f.write(polypoints)
                self.f.write(polypaths)
                prefix += 1
        # #### end global data for msg_*() functions. ####

        self.f.write('module poly_' + id + '(h, w, s, res=line_fn)\n{\n')
        self.f.write('  scale([25.4/%g, -25.4/%g, 1]) union()\n  {\n' % (self.dpi, self.dpi))

        # And add the call to the call list
        # Height is set by the overall module parameter
        # unless an extrusion height is parsed from the description or ID.
        extrusion = {'height': 'h', 'raise': '0', 'scale': 100.0, 'neg': False}
        if self.options.parsedesc == 'true':
            object_merge_extrusion_values(extrusion, node)

        call_item = 'translate ([0,0,%s]) poly_%s(%s, min_line_mm(%s), %s);\n' % (
            extrusion['raise'], id, extrusion['height'], stroke_width_mm, extrusion['scale'])

        if extrusion['neg']:
            self.call_list_neg.append(call_item)
        else:
            self.call_list.append(call_item)

        prefix = 0
        for i in range(0, len(path)):

            # Skip this subpath if it is contained by another one
            if len(contained_by[i]) != 0:
                continue

            subpath = path[i][0]
            bbox = path[i][1]

            if filled and not self.options.force_line:

                if len(contains[i]) == 0:
                    # This subpath does not contain any subpaths
                    poly = msg_linear_extrude(id, prefix)
                else:
                    # This subpath contains other subpaths
                    poly = msg_linear_extrude_by_paths(id, prefix)

            else:   # filled == False -> outline mode

                if len(contains[i]) == 0:
                    # This subpath does not contain any subpaths
                    poly = msg_extrude_by_hull(id, prefix)
                else:
                    # This subpath contains other subpaths
                    poly = msg_extrude_by_hull_and_paths(id, prefix)

            self.f.write(poly)
            prefix += 1

        # End the module
        self.f.write('  }\n}\n')

    def recursivelyTraverseSvg(self, aNodeList, matCurrent=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                               parent_visibility='visible'):

        '''
        [ This too is largely lifted from eggbot.py ]

        Recursively walk the SVG document, building polygon vertex lists
        for each graphical element we support.

        Rendered SVG elements:
            <circle>, <ellipse>, <line>, <path>, <polygon>, <polyline>, <rect>

        Supported SVG elements:
            <group>, <use>

        Ignored SVG elements:
            <defs>, <eggbot>, <metadata>, <namedview>, <pattern>,
            processing directives

        All other SVG elements trigger an error (including <text>)
        '''

        for node in aNodeList:

            # Ignore invisible nodes
            v = node.get('visibility', parent_visibility)
            if v == 'inherit':
                v = parent_visibility
            if v == 'hidden' or v == 'collapse':
                continue

            s = node.get('style', '')
            if s == 'display:none':
                continue

            # First apply the current matrix transform to this node's tranform
            matNew = simpletransform.composeTransform(
                matCurrent, simpletransform.parseTransform(node.get("transform")))

            if node.tag == inkex.addNS('g', 'svg') or node.tag == 'g':

                self.recursivelyTraverseSvg(node, matNew, v)

            elif node.tag == inkex.addNS('use', 'svg') or node.tag == 'use':

                # A <use> element refers to another SVG element via an
                # xlink:href="#blah" attribute.  We will handle the element by
                # doing an XPath search through the document, looking for the
                # element with the matching id="blah" attribute.  We then
                # recursively process that element after applying any necessary
                # (x,y) translation.
                #
                # Notes:
                #  1. We ignore the height and width attributes as they do not
                #     apply to path-like elements, and
                #  2. Even if the use element has visibility="hidden", SVG
                #     still calls for processing the referenced element.  The
                #     referenced element is hidden only if its visibility is
                #     "inherit" or "hidden".

                refid = node.get(inkex.addNS('href', 'xlink'))
                if not refid:
                    continue

                # [1:] to ignore leading '#' in reference
                path = '//*[@id="%s"]' % refid[1:]
                refnode = node.xpath(path)
                if refnode:
                    x = float(node.get('x', '0'))
                    y = float(node.get('y', '0'))
                    # Note: the transform has already been applied
                    if (x != 0) or (y != 0):
                        matNew2 = composeTransform(matNew, parseTransform('translate(%f,%f)' % (x, y)))
                    else:
                        matNew2 = matNew
                    v = node.get('visibility', v)
                    self.recursivelyTraverseSvg(refnode, matNew2, v)

            elif node.tag == inkex.addNS('path', 'svg'):

                path_data = node.get('d')
                if path_data:
                    self.getPathVertices(path_data, node, matNew)

            elif node.tag == inkex.addNS('rect', 'svg') or node.tag == 'rect':

                # Manually transform
                #
                #    <rect x="X" y="Y" width="W" height="H"/>
                #
                # into
                #
                #    <path d="MX,Y lW,0 l0,H l-W,0 z"/>
                #
                # I.e., explicitly draw three sides of the rectangle and the
                # fourth side implicitly

                # Create a path with the outline of the rectangle
                x = float(node.get('x'))
                y = float(node.get('y'))
                w = float(node.get('width', '0'))
                h = float(node.get('height', '0'))
                a = []
                a.append(['M ', [x, y]])
                a.append([' l ', [w, 0]])
                a.append([' l ', [0, h]])
                a.append([' l ', [-w, 0]])
                a.append([' Z', []])
                self.getPathVertices(simplepath.formatPath(a), node, matNew)

            elif node.tag == inkex.addNS('line', 'svg') or node.tag == 'line':

                # Convert
                #
                #   <line x1="X1" y1="Y1" x2="X2" y2="Y2/>
                #
                # to
                #
                #   <path d="MX1,Y1 LX2,Y2"/>

                x1 = float(node.get('x1'))
                y1 = float(node.get('y1'))
                x2 = float(node.get('x2'))
                y2 = float(node.get('y2'))
                if (not x1) or (not y1) or (not x2) or (not y2):
                    continue
                a = []
                a.append(['M ', [x1, y1]])
                a.append([' L ', [x2, y2]])
                self.getPathVertices(simplepath.formatPath(a), node, matNew)

            elif node.tag == inkex.addNS('polyline', 'svg') or node.tag == 'polyline':

                # Convert
                #
                #  <polyline points="x1,y1 x2,y2 x3,y3 [...]"/>
                #
                # to
                #
                #   <path d="Mx1,y1 Lx2,y2 Lx3,y3 [...]"/>
                #
                # Note: we ignore polylines with no points

                pl = node.get('points', '').strip()
                if pl == '':
                    continue

                pa = pl.split()
                d = "".join(["M " + pa[i] if i == 0 else " L " + pa[i] for i in range(0, len(pa))])
                self.getPathVertices(d, node, matNew)

            elif node.tag == inkex.addNS('polygon', 'svg') or node.tag == 'polygon':

                # Convert
                #
                #  <polygon points="x1,y1 x2,y2 x3,y3 [...]"/>
                #
                # to
                #
                #   <path d="Mx1,y1 Lx2,y2 Lx3,y3 [...] Z"/>
                #
                # Note: we ignore polygons with no points

                pl = node.get('points', '').strip()
                if pl == '':
                    continue

                pa = pl.split()
                d = "".join(["M " + pa[i] if i == 0 else " L " + pa[i] for i in range(0, len(pa))])
                d += " Z"
                self.getPathVertices(d, node, matNew)

            elif node.tag == inkex.addNS('ellipse', 'svg') or node.tag == 'ellipse' or \
                 node.tag == inkex.addNS('circle', 'svg')  or node.tag == 'circle':

                # Convert circles and ellipses to a path with two 180 degree
                # arcs. In general (an ellipse), we convert
                #
                #   <ellipse rx="RX" ry="RY" cx="X" cy="Y"/>
                #
                # to
                #
                #   <path d="MX1,CY A RX,RY 0 1 0 X2,CY A RX,RY 0 1 0 X1,CY"/>
                #
                # where
                #
                #   X1 = CX - RX
                #   X2 = CX + RX
                #
                # Note: ellipses or circles with a radius attribute of value 0
                # are ignored

                if node.tag == inkex.addNS('ellipse', 'svg') or node.tag == 'ellipse':
                    rx = float(node.get('rx', '0'))
                    ry = float(node.get('ry', '0'))
                else:
                    rx = float(node.get('r', '0'))
                    ry = rx
                if rx == 0 or ry == 0:
                    continue

                cx = float(node.get('cx', '0'))
                cy = float(node.get('cy', '0'))
                x1 = cx - rx
                x2 = cx + rx
                d = 'M %f,%f '     % (x1, cy) + \
                    'A %f,%f '     % (rx, ry) + \
                    '0 1 0 %f,%f ' % (x2, cy) + \
                    'A %f,%f '     % (rx, ry) + \
                    '0 1 0 %f,%f'  % (x1, cy)
                self.getPathVertices(d, node, matNew)

            elif node.tag == inkex.addNS('pattern', 'svg') or node.tag == 'pattern':
                pass

            elif node.tag == inkex.addNS('metadata', 'svg') or node.tag == 'metadata':
                pass

            elif node.tag == inkex.addNS('defs', 'svg') or node.tag == 'defs':
                pass

            elif node.tag == inkex.addNS('desc', 'svg') or node.tag == 'desc':
                pass

            elif node.tag == inkex.addNS('namedview', 'sodipodi') or node.tag == 'namedview':
                pass

            elif node.tag == inkex.addNS('eggbot', 'svg') or node.tag == 'eggbot':
                pass

            elif node.tag == inkex.addNS('text', 'svg') or node.tag == 'text':
                texts = []
                plaintext = ''
                for tnode in node.iterfind('.//'):  # all subtree
                    if tnode is not None and tnode.text is not None:
                        texts.append(tnode.text)
                if len(texts):
                    plaintext = "', '".join(texts).encode('latin-1')
                    inkex.errormsg('Warning: text "%s"' % plaintext)
                    inkex.errormsg('Warning: unable to draw text, please convert it to a path first.')

            elif node.tag == inkex.addNS('title', 'svg') or node.tag == 'title':
                pass

            elif node.tag == inkex.addNS('image', 'svg') or node.tag == 'image':
                if 'image' not in self.warnings:
                    inkex.errormsg(
                        gettext.gettext(
                            'Warning: unable to draw bitmap images; please convert them to line art first.  '
                            'Consider using the "Trace bitmap..." tool of the "Path" menu.  Mac users please '
                            'note that some X11 settings may cause cut-and-paste operations to paste in bitmap copies.'))
                    self.warnings['image'] = 1

            elif node.tag == inkex.addNS('pattern', 'svg') or node.tag == 'pattern':
                pass

            elif node.tag == inkex.addNS('radialGradient', 'svg') or node.tag == 'radialGradient':
                # Similar to pattern
                pass

            elif node.tag == inkex.addNS('linearGradient', 'svg') or node.tag == 'linearGradient':
                # Similar in pattern
                pass

            elif node.tag == inkex.addNS('style', 'svg') or node.tag == 'style':
                # This is a reference to an external style sheet and not the
                # value of a style attribute to be inherited by child elements
                pass

            elif node.tag == inkex.addNS('cursor', 'svg') or node.tag == 'cursor':
                pass

            elif node.tag == inkex.addNS('color-profile', 'svg') or node.tag == 'color-profile':
                # Gamma curves, color temp, etc. are not relevant to single
                # color output
                pass

            elif not isinstance(node.tag, basestring):
                # This is likely an XML processing instruction such as an XML
                # comment.  lxml uses a function reference for such node tags
                # and as such the node tag is likely not a printable string.
                # Further, converting it to a printable string likely won't
                # be very useful.
                pass

            else:
                inkex.errormsg('Warning: unable to draw object <%s>, please convert it to a path first.' % node.tag)
                pass

    def recursivelyGetEnclosingTransform(self, node):

        '''
        Determine the cumulative transform which node inherits from
        its chain of ancestors.
        '''
        node = node.getparent()
        if node is not None:
            parent_transform = self.recursivelyGetEnclosingTransform(node)
            node_transform = node.get('transform', None)
            if node_transform is None:
                return parent_transform
            else:
                tr = simpletransform.parseTransform(node_transform)
                if parent_transform is None:
                    return tr
                else:
                    return simpletransform.composeTransform(parent_transform, tr)
        else:
            return self.docTransform

    def effect(self):

        # Viewbox handling
        self.handleViewBox()

        # First traverse the document (or selected items), reducing
        # everything to line segments.  If working on a selection,
        # then determine the selection's bounding box in the process.
        # (Actually, we just need to know it's extrema on the x-axis.)

        if self.options.ids:
            # Traverse the selected objects
            for id in self.options.ids:
                transform = self.recursivelyGetEnclosingTransform(self.selected[id])
                self.recursivelyTraverseSvg([self.selected[id]], transform)
        else:
            # Traverse the entire document building new, transformed paths
            self.recursivelyTraverseSvg(self.document.getroot(), self.docTransform)

        # Determine the center of the drawing's bounding box
        self.cx = self.xmin + (self.xmax - self.xmin) / 2.0
        self.cy = self.ymin + (self.ymax - self.ymin) / 2.0

        # Determine which polygons lie entirely within other polygons
        try:
            if os.sep not in self.options.fname and 'PWD' in os.environ:
                # current working directory of an extension seems to be the extension dir.
                # Workaround using PWD, if available...
                self.options.fname = self.options.fname.format(**{'NAME': self.basename})
                self.options.fname = os.environ['PWD'] + '/' + self.options.fname
            scad_fname = os.path.expanduser(self.options.fname)
            if '/' != os.sep:
                scad_fname = scad_fname.replace('/', os.sep)
            self.f = open(scad_fname, 'w')
            # for use in options.fname basename is derived from the sodipodi_docname by
            # stripping the svg extension - or if there is no sodipodi_docname basename is 'inkscape'.
            # for use in scadviewcmd, scad2stlcmd and stlpostcmd basename is rederived from
            # options.fname by stripping an scad extension.
            self.basename = re.sub(r"\.scad", "", scad_fname, flags=re.I)

            self.f.write('''
// Module names are of the form poly_<inkscape-path-id>().  As a result,
// you can associate a polygon in this OpenSCAD program with the corresponding
// SVG element in the Inkscape document by looking for the XML element with
// the attribute id=\"inkscape-path-id\".

// fudge value is used to ensure that subtracted solids are a tad taller
// in the z dimension than the polygon being subtracted from.  This helps
// keep the resulting .stl file manifold.
fudge = 0.1;
''')
            # writeout users parameters
            self.f.write('height = %s;\n' % (self.options.height))
            self.f.write('line_fn = %d;\n' % (self.options.line_fn))
            self.f.write('min_line_width = %s;\n' % (self.options.min_line_width))
            self.f.write('function min_line_mm(w) = max(min_line_width, w) * %g/25.4;\n\n' % self.dpi)

            for key in self.paths:
                self.f.write('\n')
                self.convertPath(key)

            # Come up with a name for the module based on the file name.
            name = os.path.splitext(os.path.basename(self.options.fname))[0]
            # Remove all punctuation except underscore.
            name = re.sub('[' + string.punctuation.replace('_', '') + ']', '', name)

            self.f.write('\nmodule %s(h)\n{\n' % name)

            # Now output the list of modules to call
            self.f.write('  difference()\n  {\n    union()\n    {\n')
            for call in self.call_list:
                self.f.write('      ' + call)
            self.f.write('    }\n    union()\n    {\n')
            for call in self.call_list_neg:
                self.f.write('      ' + call)
            self.f.write('    }\n  }\n')

            # The module that calls all the other ones.
            self.f.write('}\n\n%s(height);\n' % (name))
            self.f.close()

        except IOError as e:
            inkex.errormsg('Unable to write file ' + self.options.fname)
            inkex.errormsg("ERROR: " + str(e))

        if self.options.scadview == 'true':
            pidfile = tempfile.gettempdir() + os.sep + "paths2openscad.pid"
            running = False
            cmd = self.options.scadviewcmd.format(**{'SCAD': scad_fname, 'NAME': self.basename})
            try:
                m = re.match(r"(\d+)\s+(.*)", open(pidfile).read())
                oldpid = int(m.group(1))
                oldcmd = m.group(2)
                # print >> sys.stderr, "pid {1} seen in {0}".format(pidfile, oldpid)
                # print >> sys.stderr, "cmd {0},  oldcmd {1}".format(cmd, oldcmd)
                if cmd == oldcmd:
                    # we found a pidfile and the cmd in there is still identical.
                    # If we change the filename in the inkscape extension gui, the cmd differs, and
                    # the still running openscad would not pick up our changes.
                    # If the command is identical, we check if the pid in the pidfile is alive.
                    # If so, we assume, the still running openscad will pick up the changes.
                    #
                    # WARNING: too much magic here. We cannot really test, if the last assumption holds.
                    # Comment out the next line to always start a new instance of openscad.
                    running = IsProcessRunning(oldpid)
                    # print >> sys.stderr, "running {0}".format(running)
            except:
                pass
            if not running:
                import subprocess
                try:
                    tty = open("/dev/tty", "w")
                except:
                    tty = subprocess.PIPE
                try:
                    proc = subprocess.Popen(cmd, shell=True, stdin=tty, stdout=tty, stderr=tty)
                except OSError as e:
                    raise OSError("%s failed: errno=%d %s" % (cmd, e.errno, e.strerror))
                try:
                    open(pidfile, "w").write(str(proc.pid) + "\n" + cmd + "\n")
                except:
                    pass
            else:
                # BUG alert:
                # If user changes the file viewed in openscad (save with different name, re-open that name
                #     without closing openscad, again, the still running openscad does not
                #     pick up the changes. and we have no way to tell the difference if it did.
                pass

        if self.options.scad2stl == 'true' or self.options.stlpost == 'true':
            stl_fname = self.basename + '.stl'
            cmd = self.options.scad2stlcmd.format(**{'SCAD': scad_fname, 'STL': stl_fname, 'NAME': self.basename})
            try:
                os.unlink(stl_fname)
            except:
                pass

            import subprocess
            try:
                proc = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except OSError as e:
                raise OSError("{0} failed: errno={1} {2}".format(cmd, e.errno, e.strerror))
            stdout, stderr = proc.communicate()

            len = -1
            try:
                len = os.path.getsize(stl_fname)
            except:
                pass
            if len < 1000:
                print >> sys.stderr, "CMD: {0}".format(cmd)
                print >> sys.stderr, "WARNING: {0} is very small: {1} bytes.".format(stl_fname, len)
                print >> sys.stderr, "= " * 24
                print >> sys.stderr, "STDOUT:\n", stdout, "= " * 24
                print >> sys.stderr, "STDERR:\n", stderr, "= " * 24
                if len <= 0:  # something is wrong. better stop here
                    self.options.stlpost = 'false'

            if self.options.stlpost == 'true':
                cmd = self.options.stlpostcmd.format(**{'STL': self.basename + '.stl', 'NAME': self.basename})
                try:
                    tty = open("/dev/tty", "w")
                except:
                    tty = subprocess.PIPE

                try:
                    proc = subprocess.Popen(cmd, shell=True, stdin=tty, stdout=tty, stderr=tty)
                except OSError as e:
                    raise OSError("%s failed: errno=%d %s" % (cmd, e.errno, e.strerror))

                stdout, stderr = proc.communicate()
                if stdout or stderr:
                    print >> sys.stderr, "CMD: ", cmd, "\n", "= " * 24
                if stdout:
                    print >> sys.stderr, "STDOUT:\n", stdout, "= " * 24
                if stderr:
                    print >> sys.stderr, "STDERR:\n", stderr, "= " * 24


if __name__ == '__main__':
    e = OpenSCAD()
    e.affect()

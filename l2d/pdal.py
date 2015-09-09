#!/usr/bin/env python
################################################################################
#   lidar2dems - utilties for creating DEMs from LiDAR data
#
#   AUTHOR: Matthew Hanson, matt.a.hanson@gmail.com
#
#   Copyright (C) 2015 Applied Geosolutions LLC, oss@appliedgeosolutions.com
#
#   Redistribution and use in source and binary forms, with or without
#   modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice, this
#     list of conditions and the following disclaimer.
#
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions and the following disclaimer in the documentation
#     and/or other materials provided with the distribution.
#
#   THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
#   AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#   IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#   DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
#   FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
#   DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
#   SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
#   CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
#   OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#   OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
################################################################################

# Library functions for creating DEMs from Lidar data

import os
from lxml import etree
import tempfile
import gippy
from gippy.algorithms import CookieCutter
import numpy
from shapely.wkt import loads
import glob
from datetime import datetime
import uuid
from .utils import splitexts, class_params, class_suffix, dem_products


""" XML Functions """


def _xml_base():
    """ Create initial XML for PDAL pipeline """
    xml = etree.Element("Pipeline", version="1.0")
    return xml


def _xml_p2g_base(fout, output, radius, site=None):
    """ Create initial XML for PDAL pipeline containing a Writer element """
    xml = _xml_base()
    etree.SubElement(xml, "Writer", type="writers.p2g")
    etree.SubElement(xml[0], "Option", name="grid_dist_x").text = "1.0"
    etree.SubElement(xml[0], "Option", name="grid_dist_y").text = "1.0"
    etree.SubElement(xml[0], "Option", name="radius").text = str(radius)
    etree.SubElement(xml[0], "Option", name="output_format").text = "tif"
    # add EPSG option? - 'EPSG:%s' % epsg
    if site is not None:
        etree.SubElement(xml[0], "Option", name="spatialreference").text = site.Projection()
        # this not yet working in p2g
        # bounds = get_vector_bounds(site)
        # bounds = '([%s, %s], [%s, %s])' % (bounds[0], bounds[2], bounds[1], bounds[3])
        # etree.SubElement(xml[0], "Option", name="bounds").text = bounds
    etree.SubElement(xml[0], "Option", name="filename").text = fout
    for t in output:
        etree.SubElement(xml[0], "Option", name="output_type").text = t
    return xml


def _xml_las_base(fout):
    """ Create initial XML for writing to a LAS file """
    xml = _xml_base()
    etree.SubElement(xml, "Writer", type="writers.las")
    etree.SubElement(xml[0], "Option", name="filename").text = fout
    return xml


def _xml_add_pclblock(xml, pclblock):
    """ Add pclblock Filter element by taking in filename of a JSON file """
    _xml = etree.SubElement(xml, "Filter", type="filters.pclblock")
    etree.SubElement(_xml, "Option", name="filename").text = pclblock
    return _xml


def _xml_add_pmf(xml, slope, cellsize):
    """ Add progressive morphological filter """
    # create JSON file for performing outlier removal
    j1 = '{"pipeline": {"name": "PMF","version": 1.0,"filters":'
    json = j1 + '[{"name": "ProgressiveMorphologicalFilter","setSlope": %s,"setellSize": %s}]}}' % (slope, cellsize)
    f, fname = tempfile.mkstemp(suffix='.json')
    os.write(f, json)
    os.close(f)
    return _xml_add_pclblock(xml, fname)


def _xml_add_decimation_filter(xml, step):
    """ Add decimation Filter element and return """
    fxml = etree.SubElement(xml, "Filter", type="filters.decimation")
    etree.SubElement(fxml, "Option", name="step").text = str(step)
    return fxml


def _xml_add_classification_filter(xml, classification, equality="equals"):
    """ Add classification Filter element and return """
    fxml = etree.SubElement(xml, "Filter", type="filters.range")
    _xml = etree.SubElement(fxml, "Option", name="dimension")
    _xml.text = "Classification"
    _xml = etree.SubElement(_xml, "Options")
    etree.SubElement(_xml, "Option", name=equality).text = str(classification)
    return fxml


def _xml_add_maxsd_filter(xml, meank=20, thresh=3.0):
    """ Add outlier Filter element and return """
    # create JSON file for performing outlier removal
    j1 = '{"pipeline": {"name": "Outlier Removal","version": 1.0,"filters":'
    json = j1 + '[{"name": "StatisticalOutlierRemoval","setMeanK": %s,"setStddevMulThresh": %s}]}}' % (meank, thresh)
    f, fname = tempfile.mkstemp(suffix='.json')
    os.write(f, json)
    os.close(f)
    return _xml_add_pclblock(xml, fname)


def _xml_add_maxz_filter(xml, maxz):
    """ Add max elevation Filter element and return """
    fxml = etree.SubElement(xml, "Filter", type="filters.range")
    _xml = etree.SubElement(fxml, "Option", name="dimension")
    _xml.text = "Z"
    _xml = etree.SubElement(_xml, "Options")
    etree.SubElement(_xml, "Option", name="max").text = maxz
    return fxml


def _xml_add_maxangle_filter(xml, maxabsangle):
    """ Add scan angle Filter element and return """
    fxml = etree.SubElement(xml, "Filter", type="filters.range")
    _xml = etree.SubElement(fxml, "Option", name="dimension")
    _xml.text = "ScanAngleRank"
    _xml = etree.SubElement(_xml, "Options")
    etree.SubElement(_xml, "Option", name="max").text = maxabsangle
    etree.SubElement(_xml, "Option", name="min").text = str(-float(maxabsangle))
    return fxml


def _xml_add_scanedge_filter(xml, value):
    """ Add EdgeOfFlightLine Filter element and return """
    fxml = etree.SubElement(xml, "Filter", type="filters.range")
    _xml = etree.SubElement(fxml, "Option", name="dimension")
    _xml.text = "EdgeOfFlightLine"
    _xml = etree.SubElement(_xml, "Options")
    etree.SubElement(_xml, "Option", name="equals").text = value
    return fxml


def _xml_add_returnnum_filter(xml, value):
    """ Add ReturnNum Filter element and return """
    fxml = etree.SubElement(xml, "Filter", type="filters.range")
    _xml = etree.SubElement(fxml, "Option", name="dimension")
    _xml.text = "ReturnNum"
    _xml = etree.SubElement(_xml, "Options")
    etree.SubElement(_xml, "Option", name="equals").text = value
    return fxml


def _xml_add_filters(xml, maxsd=None, maxz=None, maxangle=None, returnnum=None):
    if maxsd is not None:
        xml = _xml_add_maxsd_filter(xml, thresh=maxsd)
    if maxz is not None:
        xml = _xml_add_maxz_filter(xml, maxz)
    if maxangle is not None:
        xml = _xml_add_maxangle_filter(xml, maxangle)
    if returnnum is not None:
        xml = _xml_add_returnnum_filter(xml, returnnum)
    return xml


def _xml_add_crop_filter(xml, wkt):
    """ Add cropping polygon as Filter Element and return """
    fxml = etree.SubElement(xml, "Filter", type="filters.crop")
    etree.SubElement(fxml, "Option", name="polygon").text = wkt
    return fxml


def _xml_add_reader(xml, filename):
    """ Add LAS Reader Element and return """
    _xml = etree.SubElement(xml, "Reader", type="readers.las")
    etree.SubElement(_xml, "Option", name="filename").text = os.path.abspath(filename)
    return _xml


def _xml_add_readers(xml, filenames):
    """ Add merge Filter element and readers to a Writer element and return Filter element """
    if len(filenames) > 1:
        fxml = etree.SubElement(xml, "Filter", type="filters.merge")
    else:
        fxml = xml
    for f in filenames:
        _xml_add_reader(fxml, f)
    return fxml


def _xml_print(xml):
    """ Pretty print xml """
    print etree.tostring(xml, pretty_print=True)


""" Run PDAL commands """


def run_pipeline(xml, verbose=False):
    """ Run PDAL Pipeline with provided XML """
    if verbose:
        _xml_print(xml)

    # write to temp file
    f, xmlfile = tempfile.mkstemp(suffix='.xml')
    if verbose:
        print 'Pipeline file: %s' % xmlfile
    os.write(f, etree.tostring(xml))
    os.close(f)

    cmd = [
        'pdal',
        'pipeline',
        '-i %s' % xmlfile,
        '-v4',
    ]
    if verbose:
        out = os.system(' '.join(cmd))
    else:
        out = os.system(' '.join(cmd) + ' > /dev/null 2>&1')
    os.remove(xmlfile)


def run_pdalground(fin, fout, slope, cellsize, verbose=False):
    """ Run PDAL ground """
    cmd = [
        'pdal',
        'ground',
        '-i %s' % fin,
        '-o %s' % fout,
        '--slope %s' % slope,
        '--cellSize %s' % cellsize,
        '--classify'
    ]
    if verbose:
        cmd.append('-v1')
        print ' '.join(cmd)
    out = os.system(' '.join(cmd))
    if verbose:
        print out


# LiDAR Classification and DEM creation


def classify(filenames, site=None, buffer=20,
             slope=None, cellsize=None, decimation=None,
             outdir='', suffix='', verbose=False):
    """ Classify files and output single las file """
    start = datetime.now()

    # get classification parameters
    slope, cellsize = class_params(site, slope, cellsize)

    # output filename
    fout = '' if site is None else site.Basename() + '_'
    fout = os.path.join(os.path.abspath(outdir), fout + class_suffix(slope, cellsize, suffix))
    prettyname = os.path.relpath(fout)

    if not os.path.exists(fout):
        print 'Classifying %s files into %s' % (len(filenames), prettyname)

        # xml pipeline
        # problem using PMF in XML - instead merge to ftmp and runn 'pdal ground'
        ftmp = os.path.join(os.path.abspath(outdir), str(uuid.uuid4()) + '.las')
        xml = _xml_las_base(ftmp)
        _xml = xml[0]
        if decimation is not None:
            _xml = _xml_add_decimation_filter(_xml, decimation)
        # need to build PDAL with GEOS
        if site is not None:
            wkt = loads(site.WKT()).buffer(buffer).wkt
            _xml = _xml_add_crop_filter(_xml, wkt)
        _xml_add_readers(_xml, filenames)
        run_pipeline(xml, verbose=verbose)
        print 'Created temp merged las file %s in %s' % (os.path.relpath(ftmp), datetime.now() - start)

        run_pdalground(ftmp, fout, slope, cellsize, verbose=verbose)

        # remove merged, unclassified file
        if os.path.exists(fout):
            os.remove(ftmp)

    print 'Completed %s in %s' % (prettyname, datetime.now() - start)
    return fout


def create_dems(filenames, demtype, radius=['0.56'], site=None, gapfill=False, outdir='', suffix='', **kwargs):
    """ Create DEMS for multiple radii, and optionally gapfill """
    fouts = []
    for rad in radius:
        fouts.append(create_dem(filenames, demtype, radius=rad, site=site, outdir=outdir, suffix=suffix, **kwargs))
    fnames = {}
    # convert from list of dicts, to dict of lists
    for product in fouts[0].keys():
        fnames[product] = [f[product] for f in fouts]
    fouts = fnames

    # gapfill all products (except density)
    _fouts = {}
    if gapfill:
        for product in fouts.keys():
            # do not gapfill, but keep product pointing to first radius run
            if product == 'den':
                _fouts[product] = fouts[product][0]
                continue
            # output filename
            bname = '' if site is None else site.Basename() + '_'
            fout = os.path.join(outdir, bname + '%s%s.%s.tif' % (demtype, suffix, product))
            if not os.path.exists(fout):
                gap_fill(fouts[product], fout, site=site)
            _fouts[product] = fout
    else:
        # only return single filename (first radius run)
        for product in fouts.keys():
            _fouts[product] = fouts[product][0]

    return _fouts


def create_dem(filenames, demtype, radius='0.56', site=None, decimation=None,
               maxsd=None, maxz=None, maxangle=None, returnnum=None,
               products=None, outdir='', suffix='', verbose=False):
    """ Create DEM from collection of LAS files """
    start = datetime.now()
    # filename based on demtype, radius, and optional suffix
    bname = '' if site is None else site.Basename() + '_'
    bname = os.path.join(os.path.abspath(outdir), '%s%s_r%s%s' % (bname, demtype, radius, suffix))
    ext = 'tif'

    # products (den, max, etc)
    if products is None:
        products = dem_products(demtype)
    fouts = {o: bname + '.%s.%s' % (o, ext) for o in products}
    prettyname = os.path.relpath(bname) + ' [%s]' % (' '.join(products))

    # run if any products missing (any extension version is ok, i.e. vrt or tif)
    run = False
    for f in fouts.values():
        if len(glob.glob(f[:-3] + '*')) == 0:
            run = True

    if run:
        print 'Creating %s from %s files' % (prettyname, len(filenames))
        # xml pipeline
        xml = _xml_p2g_base(bname, products, radius, site)
        _xml = xml[0]
        if decimation is not None:
            _xml = _xml_add_decimation_filter(_xml, decimation)
        _xml = _xml_add_filters(_xml, maxsd, maxz, maxangle, returnnum)
        if demtype == 'dsm':
            _xml = _xml_add_classification_filter(_xml, 1, equality='max')
        elif demtype == 'dtm':
            _xml = _xml_add_classification_filter(_xml, 2)
        _xml_add_readers(_xml, filenames)
        run_pipeline(xml, verbose=verbose)

    print 'Completed %s in %s' % (prettyname, datetime.now() - start)
    return fouts


def create_chm(dtm, dsm, chm):
    """ Create CHM from a DTM and DSM - assumes common grid """
    dtm_img = gippy.GeoImage(dtm)
    dsm_img = gippy.GeoImage(dsm)
    imgout = gippy.GeoImage(chm, dtm_img)
    nodata = dtm_img[0].NoDataValue()
    imgout.SetNoData(nodata)
    dsm_arr = dsm_img[0].Read()
    arr = dsm_arr - dtm_img[0].Read()
    arr[dsm_arr == nodata] = nodata
    imgout[0].Write(arr)
    return imgout.Filename()


def gap_fill(filenames, fout, site=None, interpolation='nearest'):
    """ Gap fill from higher radius DTMs, then fill remainder with interpolation """
    print 'Gap-filling to create %s' % os.path.relpath(fout)
    start = datetime.now()
    from scipy.interpolate import griddata
    if len(filenames) == 0:
        raise Exception('No filenames provided!')

    filenames = sorted(filenames)
    imgs = gippy.GeoImages(filenames)
    nodata = imgs[0][0].NoDataValue()
    arr = imgs[0][0].Read()

    for i in range(1, imgs.size()):
        locs = numpy.where(arr == nodata)
        arr[locs] = imgs[i][0].Read()[locs]

    # interpolation at bad points
    goodlocs = numpy.where(arr != nodata)
    badlocs = numpy.where(arr == nodata)
    arr[badlocs] = griddata(goodlocs, arr[goodlocs], badlocs, method=interpolation)

    # write output
    imgout = gippy.GeoImage(fout, imgs[0])
    imgout.SetNoData(nodata)
    imgout[0].Write(arr)
    fout = imgout.Filename()
    imgout = None

    # align and clip
    if site is not None:
        from osgeo import gdal
        # get resolution
        ds = gdal.Open(fout, gdal.GA_ReadOnly)
        gt = ds.GetGeoTransform()
        ds = None
        parts = splitexts(fout)
        _fout = parts[0] + '_clip' + parts[1]
        CookieCutter(gippy.GeoImages([fout]), site, _fout, gt[1], abs(gt[5]), True)
        if os.path.exists(fout):
            os.remove(fout)
            os.rename(_fout, fout)

    print 'Completed in %s' % (datetime.now() - start)

    return fout
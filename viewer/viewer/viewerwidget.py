
"""
Viewer Widget. Allows display of images,
zooming and panning etc.
"""

from __future__ import division # ensure we are using Python 3 semantics
import numpy
from PyQt4.QtGui import QAbstractScrollArea, QPainter, QRubberBand, QCursor
from PyQt4.QtGui import QPixmap, QPainterPath, QPen
from PyQt4.QtCore import Qt, QRect, QSize, QPoint, SIGNAL

from . import viewererrors
from . import viewerlayers

VIEWER_ZOOM_WHEEL_FRACTION = 0.1 # viewport increased/decreased by the fraction
                            # on zoom out/ zoom in with mouse wheel

class QueryInfo(object):
    """
    Container class for the information passed in the locationSelected
    signal.
    """
    def __init__(self, easting, northing, column, row, data, layer):
        self.easting = easting
        self.northing = northing
        self.column = column
        self.row = row
        self.data = data
        self.layer = layer

class GeolinkInfo(object):
    """
    Conainter class for the information passed in the geolinkMove
    and geolinkQueryPoint signals.
    """
    def __init__(self, senderid, easting, northing, metresperwinpix=0):
        self.senderid = senderid
        self.easting = easting
        self.northing = northing
        self.metresperwinpix = metresperwinpix

VIEWER_TOOL_NONE = 0
VIEWER_TOOL_ZOOMIN = 1
VIEWER_TOOL_ZOOMOUT = 2
VIEWER_TOOL_PAN = 3
VIEWER_TOOL_QUERY = 4
VIEWER_TOOL_POLYGON = 5
VIEWER_TOOL_POLYLINE = 6

class ViewerWidget(QAbstractScrollArea):
    """
    The main ViewerWidget class. Should be embeddable in
    other applications. See the open() function for loading
    images.
    """
    def __init__(self, parent):
        QAbstractScrollArea.__init__(self, parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        self.layers = viewerlayers.LayerManager()

        self.paintPoint = QPoint() # normally 0,0 unless we are panning

        # when moving the scroll bars
        # events get fired that we wish to ignore
        self.suppressscrollevent = False

        # set the background color to black so window
        # is black when nothing loaded and when panning
        # new areas are initially black.
        widget = self.viewport()
        palette = widget.palette()
        palette.setColor(widget.backgroundRole(), Qt.black)
        widget.setPalette(palette)

        # to do with tools
        self.rubberBand = None
        self.panCursor = None
        self.panGrabCursor = None
        self.zoomInCursor = None
        self.zoomOutCursor = None
        self.queryCursor = None
        self.polygonCursor = None
        self.activeTool = VIEWER_TOOL_NONE
        self.panOrigin = None
        self.toolPoints = None # for line and polygon tools - list of points
        self.toolPointsFinished = True # True if we finished collecting
                                # with line and poly tools
        self.toolPen = QPen() # for drawing the toolPoints
        self.toolPen.setWidth(1)
        self.toolPen.setColor(Qt.yellow)
        self.toolPen.setDashPattern([5, 5, 5, 5])

        # Define the scroll wheel behaviour
        self.mouseWheelZoom = True
        # do we follow extent when geolinking?
        self.geolinkFollowExtent = True

    def updateScrollBars(self):
        """
        Update the scroll bars to accurately show where
        we are relative to the full extent
        """
        fullextent = self.layers.getFullExtent()
        setbars = False
        self.suppressscrollevent = True
        if fullextent is not None:
            (fullleft, fulltop, fullright, fullbottom) = fullextent
            layer = self.layers.getTopLayer()
            if layer is not None:
                (left, top, right, bottom) = layer.coordmgr.getWorldExtent()
                (wldX, wldY) = layer.coordmgr.getWorldCenter()
                verticalBar = self.verticalScrollBar()
                horizontalBar = self.horizontalScrollBar()
                # always set range to 0 - 1000 and calculate 
                # everything as fraction of that
                verticalBar.setRange(0, 1000)
                horizontalBar.setRange(0, 1000)

                # to pagestep which is also the slider size
                fullxsize = float(fullright - fullleft)
                hpagestep = (float(right - left) / fullxsize) * 1000
                horizontalBar.setPageStep(int(hpagestep))
                fullysize = float(fulltop - fullbottom)
                vpagestep = (float(top - bottom) / fullysize) * 1000
                verticalBar.setPageStep(int(vpagestep))

                # position of the slider relative to the center of the image
                hpos = (float(wldX - fullleft) / fullxsize) * 1000
                horizontalBar.setSliderPosition(int(hpos))
                vpos = (float(fulltop - wldY) / fullysize) * 1000
                verticalBar.setSliderPosition(int(vpos))
                setbars = True
        if not setbars:
            # something went wrong - disable
            self.horizontalScrollBar().setRange(0, 0)
            self.verticalScrollBar().setRange(0, 0)
        self.suppressscrollevent = False

    def addRasterLayer(self, fname, stretch, lut=None):
        """
        Add the given filename to the stack of images being displayed
        as a raster layer
        """
        size = self.viewport().size()
        self.layers.addRasterLayer(fname, size.width(), size.height(), 
                            stretch, lut)
        # get rid off tool points
        self.toolPoints = None
        self.toolPointsFinished = True

        self.viewport().update()
        self.updateScrollBars()

    def removeLayer(self):
        """
        Removes the top later
        """
        self.layers.removeTopLayer()
        # get rid off tool points
        self.toolPoints = None
        self.toolPointsFinished = True
        self.viewport().update()
        self.updateScrollBars()

    # query point functions
    def setQueryPoint(self, senderid, easting, northing, color, 
                        size=None, cursor=None):
        """
        Sets/Updates query point keyed on the id() of the sender
        """
        self.layers.queryPointLayer.setQueryPoint(senderid, easting, northing,
                                                color, size, cursor)
        self.layers.queryPointLayer.getImage()
        self.viewport().update()

    def removeQueryPoint(self, senderid):
        """
        Removes a query point. keyed on the id() of the sender
        """
        self.layers.queryPointLayer.removeQueryPoint(senderid)
        self.layers.queryPointLayer.getImage()
        self.viewport().update()

    def highlightValues(self, color, selectionArray=None):
        """
        Applies a QColor to the LUT where selectionArray == True
        to the top layer and redraws. Pass None to reset
        """
        layer = self.layers.getTopRasterLayer()
        if layer is not None:
            if len(layer.stretch.bands) != 1:
                msg = 'can only highlight values on single band images'
                raise viewererrors.InvalidDataset(msg)
            layer.highlightRows(color, selectionArray)

            # force repaint
            self.viewport().update()

    def setColorTableLookup(self, lookupArray=None, colName=None, 
                            surrogateLUT=None, surrogateName=None):
        """
        Uses the supplied lookupArray to look up image
        data before indexing into color table in the top
        layer and redraws. Pass None to reset.
        """
        layer = self.layers.getTopRasterLayer()
        if layer is not None:
            if len(layer.stretch.bands) != 1:
                msg = 'can only highlight values on single band images'
                raise viewererrors.InvalidDataset(msg)
            layer.setColorTableLookup(lookupArray, colName, surrogateLUT, 
                        surrogateName)

            # force repaint
            self.viewport().update()

    def zoomNativeResolution(self):
        """
        Sets the zoom to native resolution wherever
        the current viewport is centered
        """
        self.layers.zoomNativeResolution()
        # force repaint
        self.viewport().update()
        self.updateScrollBars()
        # geolink
        self.emitGeolinkMoved()

    def zoomFullExtent(self):
        """
        Resets the zoom to full extent - should be
        the same as when file was opened.
        """
        self.layers.zoomFullExtent()
        # force repaint
        self.viewport().update()
        self.updateScrollBars()
        # geolink
        self.emitGeolinkMoved()

    def setActiveTool(self, tool):
        """
        Set active tool (one of VIEWER_TOOL_*).
        pass VIEWER_TOOL_NONE to disable
        """
        # if the tool was line or polygon
        # now is the time to remove the outline from the widget
        if (self.activeTool == VIEWER_TOOL_POLYGON or 
                self.activeTool == VIEWER_TOOL_POLYLINE):
            self.toolPoints = None
            self.toolPointsFinished = True
            # force repaint
            self.viewport().update()

        self.activeTool = tool
        if tool == VIEWER_TOOL_ZOOMIN:
            if self.zoomInCursor is None:
                # create if needed.
                self.zoomInCursor = QCursor(QPixmap(["16 16 3 1",
                                  ". c None",
                                  "a c #000000",
                                  "# c #ffffff",
                                  ".....#####......",
                                  "...##aaaaa##....",
                                  "..#.a.....a.#...",
                                  ".#.a...a...a.#..",
                                  ".#a....a....a#..",
                                  "#a.....a.....a#.",
                                  "#a.....a.....a#.",
                                  "#a.aaaa#aaaa.a#.",
                                  "#a.....a.....a#.",
                                  "#a.....a.....a#.",
                                  ".#a....a....a#..",
                                  ".#.a...a...aaa#.",
                                  "..#.a.....a#aaa#",
                                  "...##aaaaa###aa#",
                                  ".....#####...###",
                                  "..............#."]))
            self.viewport().setCursor(self.zoomInCursor)

        elif tool == VIEWER_TOOL_ZOOMOUT:
            if self.zoomOutCursor is None:
                # create if needed
                self.zoomOutCursor = QCursor(QPixmap(["16 16 4 1",
                                  "b c None",
                                  ". c None",
                                  "a c #000000",
                                  "# c #ffffff",
                                  ".....#####......",
                                  "...##aaaaa##....",
                                  "..#.a.....a.#...",
                                  ".#.a.......a.#..",
                                  ".#a.........a#..",
                                  "#a...........a#.",
                                  "#a...........a#.",
                                  "#a.aaaa#aaaa.a#.",
                                  "#a...........a#.",
                                  "#a...........a#.",
                                  ".#a.........a#..",
                                  ".#.a.......aaa#.",
                                  "..#.a.....a#aaa#",
                                  "...##aaaaa###aa#",
                                  ".....#####...###",
                                  "..............#."]))
            self.viewport().setCursor(self.zoomOutCursor)

        elif tool == VIEWER_TOOL_PAN:
            if self.panCursor is None:
                # both these used for pan operations
                self.panCursor = QCursor(Qt.OpenHandCursor)
                self.panGrabCursor = QCursor(Qt.ClosedHandCursor)
            self.viewport().setCursor(self.panCursor)

        elif tool == VIEWER_TOOL_QUERY:
            if self.queryCursor is None:
                self.queryCursor = QCursor(Qt.CrossCursor)
            self.viewport().setCursor(self.queryCursor)

        elif tool == VIEWER_TOOL_POLYGON or tool == VIEWER_TOOL_POLYLINE:
            if self.polygonCursor is None:
                self.polygonCursor = QCursor(QPixmap(["16 16 3 1",
                                  " \xc2     c None",
                                  ".\xc2     c #000000",
                                  "+\xc2     c #FFFFFF",
                                  "                ",
                                  "       +.+      ",
                                  "      ++.++     ",
                                  "     +.....+    ",
                                  "    +.     .+   ",
                                  "   +.   .   .+  ",
                                  "  +.    .    .+ ",
                                  " ++.    .    .++",
                                  " ... ...+... ...",
                                  " ++.    .    .++",
                                  "  +.    .    .+ ",
                                  "   +.   .   .+  ",
                                  "   ++.     .+   ",
                                  "    ++.....+    ",
                                  "      ++.++     ",
                                  "       +.+      "]))
            self.viewport().setCursor(self.polygonCursor)
            msg = ('Left click adds a point, middle to remove last,' +
                        ' right click to end')
            self.emit(SIGNAL("showStatusMessage(QString)"), msg)

        elif tool == VIEWER_TOOL_NONE:
            # change back
            self.viewport().setCursor(Qt.ArrowCursor)

    def setNewStretch(self, newstretch, local=False):
        """
        Change the stretch being applied to the current data
        """
        layer = self.layers.getTopRasterLayer()
        if layer is not None:
            layer.setNewStretch(newstretch, local)
            self.viewport().update()

    def setMouseScrollWheelAction(self, scrollZoom):
        "Set the action for a mouse wheen event (scroll/zoom)"
        self.mouseWheelZoom = scrollZoom

    def setGeolinkFollowExtentAction(self, followExtent):
        "Set whether we are following geolink extent of just center"
        self.geolinkFollowExtent = followExtent

    def flicker(self):
        """
        Call to change the flicker state (ie draw the top raster image
        or not). 
        """
        state = False
        layer = self.layers.getTopLayer()
        if layer is not None:
            layer.displayed = not layer.displayed
            state = layer.displayed
            self.viewport().update()
        return state

    def scrollContentsBy(self, dx, dy):
        """
        Handle the user moving the scroll bars
        """
        if not self.suppressscrollevent:
            layer = self.layers.getTopLayer()
            if layer is not None:
                (left, top, right, bottom) = layer.coordmgr.getWorldExtent()
                hpagestep = float(self.horizontalScrollBar().pageStep())
                xamount = -(float(dx) / hpagestep) * (right - left)
                vpagestep = float(self.verticalScrollBar().pageStep())
                yamount = (float(dy) / vpagestep) * (top - bottom)
                wldX, wldY = layer.coordmgr.getWorldCenter()
                layer.coordmgr.setWorldCenter(wldX + xamount, wldY + yamount)
                self.layers.makeLayersConsistent(layer)
                self.layers.updateImages()
                self.viewport().update()
                self.updateScrollBars()

                # geolink
                self.emitGeolinkMoved()

    def wheelEvent(self, event):
        """
        User has used mouse wheel to zoom in/out or pan depending on defined preference
        """
        layer = self.layers.getTopRasterLayer()
        if layer is not None:

            if self.mouseWheelZoom:
                (wldX, wldY) = layer.coordmgr.getWorldCenter()

                impixperwinpix = layer.coordmgr.imgPixPerWinPix
                if event.delta() > 0:
                    impixperwinpix *= 1.0 - VIEWER_ZOOM_WHEEL_FRACTION
                elif event.delta() < 0:
                    impixperwinpix *= 1.0 + VIEWER_ZOOM_WHEEL_FRACTION
                layer.coordmgr.setZoomFactor(impixperwinpix)
                layer.coordmgr.setWorldCenter(wldX, wldY)
                self.layers.makeLayersConsistent(layer)
                self.layers.updateImages()
                self.updateScrollBars()
                self.viewport().update()
            else:
                dx = 0
                dy = 0
                if event.orientation() == Qt.Horizontal:
                    dx = event.delta()
                else:
                    dy = event.delta()
                self.scrollContentsBy(dx, dy)
        
            # geolink
            self.emitGeolinkMoved()

    def resizeEvent(self, event):
        """
        Window has been resized - get new data
        """
        size = event.size()
        self.layers.setDisplaySize(size.width(), size.height())
        self.updateScrollBars()

    def paintEvent(self, event):
        """
        Viewport needs to be redrawn. Assume that
        each layer's image is current (as created by getImage())
        we can just draw it with QPainter
        """
        paint = QPainter(self.viewport())

        for layer in self.layers.layers:
            if layer.displayed:
                paint.drawImage(self.paintPoint, layer.image)

        # draw any query points on top of image
        paint.drawImage(self.paintPoint, self.layers.queryPointLayer.image)

        # now any tool points
        if self.toolPoints is not None:
            path = QPainterPath()
            firstpt = self.toolPoints[0]
            path.moveTo(firstpt.x(), firstpt.y())
            for pt in self.toolPoints[1:]:
                path.lineTo(pt.x(), pt.y())
            paint.setPen(self.toolPen)
            paint.drawPath(path)

        paint.end()

    def mousePressEvent(self, event):
        """
        Mouse has been clicked down if we are in zoom/pan
        mode we need to start doing stuff here
        """
        QAbstractScrollArea.mousePressEvent(self, event)
        pos = event.pos()

        if (self.activeTool == VIEWER_TOOL_ZOOMIN or 
                    self.activeTool == VIEWER_TOOL_ZOOMOUT):
            if self.rubberBand is None:
                self.rubberBand = QRubberBand(QRubberBand.Rectangle, self)
            self.rubberBand.setGeometry(QRect(pos, QSize()))
            self.rubberBand.show()
            self.rubberBand.origin = pos

        elif self.activeTool == VIEWER_TOOL_PAN:
            # remember pos
            self.panOrigin = pos
            # change cursor
            self.viewport().setCursor(self.panGrabCursor)

        elif self.activeTool == VIEWER_TOOL_QUERY:

            layer = self.layers.getTopRasterLayer()
            if layer is not None:
                # display coords. I don't think anything needs to be added here
                (dspX, dspY) = (pos.x(), pos.y())
                # Raster row/column
                (column, row) = layer.coordmgr.display2pixel(dspX, dspY)
                (easting, northing) = layer.coordmgr.pixel2world(column, row)
                #print layer.coordmgr

                # update the point
                self.updateQueryPoint(easting, northing, column, row)

                # emit the geolinked query point signal
                obj = GeolinkInfo(id(self), easting, northing)
                self.emit(SIGNAL("geolinkQueryPoint(PyQt_PyObject)"), obj )

        elif self.activeTool == VIEWER_TOOL_POLYGON:
            button = event.button()
            if button == Qt.LeftButton:
                # adding points
                if self.toolPoints is None or self.toolPointsFinished:
                    # first point - starts and ends at same pos
                    self.toolPoints = [pos, pos]
                    self.toolPointsFinished = False
                else:
                    # last point same as first - insert before last
                    self.toolPoints.insert(-1, pos)

            elif button == Qt.MiddleButton and self.toolPoints is not None:
                # delete last point
                if len(self.toolPoints) > 2:
                    del self.toolPoints[-2]

            elif button == Qt.RightButton and self.toolPoints is not None:
                # finished
                # create object for signal
                from viewertoolclasses import PolygonToolInfo
                layer = self.layers.getTopRasterLayer()
                modifiers = event.modifiers()
                obj = PolygonToolInfo(self.toolPoints, layer, modifiers)
                self.emit(SIGNAL("polygonCollected(PyQt_PyObject)"), obj)

                self.toolPointsFinished = True # done, but still display

            # redraw so paint() gets called
            self.viewport().update()

        elif self.activeTool == VIEWER_TOOL_POLYLINE:
            button = event.button()
            if button == Qt.LeftButton:
                # adding points
                if self.toolPoints is None or self.toolPointsFinished:
                    # first point 
                    self.toolPoints = [pos]
                    self.toolPointsFinished = False
                else:
                    # add to list
                    self.toolPoints.append(pos)

            elif button == Qt.MiddleButton and self.toolPoints is not None:
                # delete last point
                if len(self.toolPoints) > 1:
                    self.toolPoints.pop()

            elif button == Qt.RightButton and self.toolPoints is not None:
                # finished
                # create object for signal
                from viewertoolclasses import PolylineToolInfo
                layer = self.layers.getTopRasterLayer()
                modifiers = event.modifiers()
                obj = PolylineToolInfo(self.toolPoints, layer, modifiers)
                self.emit(SIGNAL("polylineCollected(PyQt_PyObject)"), obj)

                self.toolPointsFinished = True # done, but still display

            # redraw so paint() gets called
            self.viewport().update()

    def mouseReleaseEvent(self, event):
        """
        Mouse has been released, if we are in zoom/pan
        mode we do stuff here.
        """
        QAbstractScrollArea.mouseReleaseEvent(self, event)
        if self.rubberBand is not None and self.rubberBand.isVisible():
            # get the information about the rect they have drawn
            # note this is on self, rather than viewport()
            selection = self.rubberBand.geometry()
            geom = self.viewport().geometry()

            selectionsize = float(selection.width() * selection.height())

            geomsize = float(geom.width() * geom.height())

            self.rubberBand.hide()

            layer = self.layers.getTopRasterLayer()
            if layer is not None:
                if selectionsize == 0:
                    fraction = 0.5 # they just clicked
                else:
                    fraction = numpy.sqrt(selectionsize / geomsize)

                if self.activeTool == VIEWER_TOOL_ZOOMIN:
                    if selectionsize == 0:
                        wldX, wldY = layer.coordmgr.display2world(
                                            selection.left(), selection.top())
                        layer.coordmgr.setZoomFactor(
                                    layer.coordmgr.imgPixPerWinPix * fraction)
                        layer.coordmgr.setWorldCenter(wldX, wldY)
                        # not sure why we need this but get black strips 
                        # around otherwise
                        layer.coordmgr.recalcBottomRight() 
                    else:
                        # I don't think anything needs to be added here
                        dspTop = selection.top()
                        dspLeft = selection.left()
                        dspBottom = selection.bottom()
                        dspRight = selection.right()
                        (rastLeft, rastTop) = layer.coordmgr.display2pixel(
                                                            dspLeft, dspTop)
                        (rastRight, rastBottom) = layer.coordmgr.display2pixel(
                                                        dspRight, dspBottom)
                        #print layer.coordmgr
                        layer.coordmgr.setTopLeftPixel(rastLeft, rastTop)
                        layer.coordmgr.calcZoomFactor(rastRight, rastBottom)
                        # not sure why we need this but get black strips 
                        # around otherwise
                        layer.coordmgr.recalcBottomRight() 
                        #print layer.coordmgr


                elif self.activeTool == VIEWER_TOOL_ZOOMOUT:
                    # the smaller the area the larger the zoom
                    wldX, wldY = layer.coordmgr.display2world(
                                            selection.left(), selection.top())
                    layer.coordmgr.setZoomFactor(
                                    layer.coordmgr.imgPixPerWinPix / fraction)
                    layer.coordmgr.setWorldCenter(wldX, wldY)

                # redraw
                self.layers.makeLayersConsistent(layer)
                self.layers.updateImages()
                self.viewport().update()
                self.updateScrollBars()

                # geolink
                self.emitGeolinkMoved()

        elif self.activeTool == VIEWER_TOOL_PAN:
            # change cursor back
            self.viewport().setCursor(self.panCursor)
            layer = self.layers.getTopRasterLayer()
            if layer is not None:
                # stop panning and move viewport
                dspXmove = -self.paintPoint.x()
                dspYmove = -self.paintPoint.y()
                (pixNewX, pixNewY) = layer.coordmgr.display2pixel(dspXmove, 
                                                                dspYmove)
                #print 'panning'
                #print layer.coordmgr
                layer.coordmgr.setTopLeftPixel(pixNewX, pixNewY)
                layer.coordmgr.recalcBottomRight()
                #print layer.coordmgr
                # reset
                self.paintPoint.setX(0)
                self.paintPoint.setY(0)
                # redraw
                self.layers.makeLayersConsistent(layer)
                self.layers.updateImages()
                self.viewport().update()
                self.updateScrollBars()
                # geolink
                self.emitGeolinkMoved()


    def mouseMoveEvent(self, event):
        """
        Mouse has been moved while dragging. If in zoom/pan
        mode we need to do something here.
        """
        QAbstractScrollArea.mouseMoveEvent(self, event)
        if self.rubberBand is not None and self.rubberBand.isVisible():
            # must be doing zoom in/out. extend rect
            rect = QRect(self.rubberBand.origin, event.pos()).normalized()
            self.rubberBand.setGeometry(rect)

        elif self.activeTool == VIEWER_TOOL_PAN:
            # panning. Work out the offset from where we
            # starting panning and draw the current image
            # at an offset
            pos = event.pos()
            xamount = pos.x() - self.panOrigin.x()
            yamount = pos.y() - self.panOrigin.y()
            self.paintPoint.setX(xamount)
            self.paintPoint.setY(yamount)
            # force repaint - self.paintPoint used by paintEvent()
            self.viewport().update()
            self.updateScrollBars()

    # query point routines
    def updateQueryPoint(self, easting, northing, column, row):
        """
        Map has been clicked, get the value and emit
        a locationSelected signal.
        """
        # read the data out of the dataset
        layer = self.layers.getTopRasterLayer()
        if (layer is not None and column >= 0 and 
                column < layer.gdalDataset.RasterXSize and 
                row >= 0 and row < layer.gdalDataset.RasterYSize):
            data = layer.gdalDataset.ReadAsArray(int(column), int(row), 1, 1)
            if data is not None:
                # we just want the single 'drill down' of data as a 1d array
                data = data[..., 0, 0]
                # if single band GDAL gives us a single value - 
                # convert back to array
                # to make life easier
                if data.size == 1:
                    data = numpy.array([data])

                qi = QueryInfo(easting, northing, column, row, data, layer)
                # emit the signal - handled by the QueryDockWidget
                self.emit(SIGNAL("locationSelected(PyQt_PyObject)"), qi)

    def doGeolinkQueryPoint(self, easting, northing):
        """
        Call this when the widget query point has been moved
        in another viewer and should be updated in this
        one if the query tool is active.
        """
        if self.activeTool == VIEWER_TOOL_QUERY:
            layer = self.layers.getTopRasterLayer()
            if layer is not None:
                (col, row) = layer.coordmgr.world2pixel(easting, northing)
                self.updateQueryPoint(easting, northing, col, row)

    # geolinking routines
    def doGeolinkMove(self, easting, northing, metresperwinpix):
        """
        Call this when widget needs to be moved because
        of geolinking event.
        """
        layer = self.layers.getTopRasterLayer()
        if layer is not None:
            if self.geolinkFollowExtent and metresperwinpix != 0:
                imgpixperwinpix = metresperwinpix / layer.coordmgr.geotransform[1]
                layer.coordmgr.setZoomFactor(imgpixperwinpix)

            layer.coordmgr.setWorldCenter(easting, northing)
            self.layers.makeLayersConsistent(layer)
            self.layers.updateImages()
            self.updateScrollBars()
            self.viewport().update()

    def emitGeolinkMoved(self):
        """
        Call this on each zoom/pan to emit the appropriate signal.
        """
        # get the coords of the current centre
        layer = self.layers.getTopRasterLayer()
        if layer is not None:
            easting, northing = layer.coordmgr.getWorldCenter()
            metresperwinpix = (layer.coordmgr.imgPixPerWinPix * 
                                        layer.coordmgr.geotransform[1])
            # emit the signal
            obj = GeolinkInfo(id(self), easting, northing, metresperwinpix)
            self.emit(SIGNAL("geolinkMove(PyQt_PyObject)"), obj )



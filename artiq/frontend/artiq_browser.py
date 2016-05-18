#!/usr/bin/env python3.5

import argparse
import asyncio
import atexit
import os
import logging

from PyQt5 import QtCore, QtGui, QtWidgets
from quamash import QEventLoop

from artiq import __artiq_dir__ as artiq_dir
from artiq.tools import verbosity_args, init_logger, atexit_register_coroutine
from artiq.gui import state, applets, models
from artiq.browser import datasets, files, experiments


logger = logging.getLogger(__name__)


def get_argparser():
    if os.name == "nt":
        default_db_file = os.path.expanduser("~\\artiq_browser.pyon")
    else:
        default_db_file = os.path.expanduser("~/.artiq_browser.pyon")

    parser = argparse.ArgumentParser(description="ARTIQ Browser")
    parser.add_argument("--db-file", default=default_db_file,
                        help="database file for local browser settings "
                        "(default: %(default)s)")
    parser.add_argument("--browse-root", default="",
                        help="root path for directory tree "
                        "(default %(default)s)")
    parser.add_argument("select", metavar="SELECT", nargs="?",
                        help="directory to browse or file to load")
    verbosity_args(parser)
    return parser


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        QtWidgets.QMainWindow.__init__(self)

        icon = QtGui.QIcon(os.path.join(artiq_dir, "gui", "logo.svg"))
        self.setWindowIcon(icon)
        self.setWindowTitle("ARTIQ Browser")

        qfm = QtGui.QFontMetrics(self.font())
        self.resize(140*qfm.averageCharWidth(), 38*qfm.lineSpacing())

        self.exit_request = asyncio.Event()

    def closeEvent(self, *args):
        self.exit_request.set()

    def save_state(self):
        return {
            "state": bytes(self.saveState()),
            "geometry": bytes(self.saveGeometry())
        }

    def restore_state(self, state):
        self.restoreGeometry(QtCore.QByteArray(state["geometry"]))
        self.restoreState(QtCore.QByteArray(state["state"]))


def main():
    # initialize application
    args = get_argparser().parse_args()
    init_logger(args)

    app = QtWidgets.QApplication(["ARTIQ Browser"])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    atexit.register(loop.close)
    smgr = state.StateManager(args.db_file)

    datasets_sub = models.LocalModelManager(datasets.Model)
    datasets_sub.init({})

    # initialize main window
    main_window = MainWindow()
    smgr.register(main_window)
    main_window.setUnifiedTitleAndToolBarOnMac(True)

    mdi_area = experiments.ExperimentsArea(args.browse_root, datasets_sub)
    mdi_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    mdi_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    main_window.setCentralWidget(mdi_area)
    smgr.register(mdi_area)

    d_files = files.FilesDock(datasets_sub, args.browse_root,
                              select=args.select)
    smgr.register(d_files)

    d_applets = applets.AppletsDock(main_window, datasets_sub)
    atexit_register_coroutine(d_applets.stop)
    smgr.register(d_applets)

    d_datasets = datasets.DatasetsDock(datasets_sub)
    smgr.register(d_datasets)

    main_window.addDockWidget(QtCore.Qt.LeftDockWidgetArea, d_files)
    main_window.addDockWidget(QtCore.Qt.BottomDockWidgetArea, d_applets)
    main_window.addDockWidget(QtCore.Qt.RightDockWidgetArea, d_datasets)

    open_action = QtWidgets.QAction("&Open", main_window)
    open_action.setIcon(app.style().standardIcon(
        QtWidgets.QStyle.SP_DialogOpenButton))
    open_action.setShortcuts(QtGui.QKeySequence.Open)
    open_action.triggered.connect(mdi_area.select_experiment)
    exp_group = main_window.menuBar().addMenu("&Experiment")
    exp_group.addAction(open_action)

    # load/initialize state
    if os.name == "nt":
        # HACK: show the main window before creating applets.
        # Otherwise, the windows of those applets that are in detached
        # QDockWidgets fail to be embedded.
        main_window.show()

    smgr.load()

    smgr.start()
    atexit_register_coroutine(smgr.stop)

    # run
    main_window.show()

    loop.run_until_complete(main_window.exit_request.wait())

if __name__ == "__main__":
    main()

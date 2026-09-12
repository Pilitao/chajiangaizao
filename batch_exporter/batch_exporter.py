"""
GDQuest Batch Exporter
-----------------
Batch export art assets from Krita using layer metadata.
"""

from functools import partial
from krita import DockWidget, DockWidgetFactory, DockWidgetFactoryBase, Krita
from PyQt5.QtWidgets import (
    QPushButton,
    QStatusBar,
    QLabel,
    QLineEdit,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QComboBox,
)
import os
from .Config import CONFIG
from .Infrastructure import WNode
from .Utils import kickstart, flip

KI = Krita.instance()


class GameArtTools(DockWidget):
    title = "Batch Exporter"

    def __init__(self):
        super().__init__()
        KI.setBatchmode(True)
        self.setWindowTitle(self.title)
        self.saved_export_path = KI.readSetting("", "batch_exporter_export_path", "")
        self.saved_scale = int(KI.readSetting("", "batch_exporter_global_scale", "50"))
        self.saved_filename = KI.readSetting("", "batch_exporter_filename", "")
        self.createInterface()

    def createInterface(self):
        uiContainer = QWidget(self)

        # 文件名输入行
        filenameLayout = QHBoxLayout()
        filenameLabel = QLabel("File Name:")
        self.filenameLineEdit = QLineEdit()
        self.filenameLineEdit.setText(self.saved_filename)
        self.filenameLineEdit.textChanged.connect(self.onFilenameChanged)
        filenameLayout.addWidget(filenameLabel)
        filenameLayout.addWidget(self.filenameLineEdit)

        # 路径设置行
        exportPathLayout = QHBoxLayout()
        exportPathLabel = QLabel("Export Path:")
        self.exportPathLineEdit = QLineEdit()
        self.exportPathLineEdit.setText(self.saved_export_path)
        browseButton = QPushButton("Browse...")
        exportPathLayout.addWidget(exportPathLabel)
        exportPathLayout.addWidget(self.exportPathLineEdit)
        exportPathLayout.addWidget(browseButton)

        # 全局缩放下拉框（步长改为5，范围5~100）
        scaleLayout = QHBoxLayout()
        scaleLabel = QLabel("Default Scale (%):")
        self.scaleComboBox = QComboBox()
        for val in range(5, 105, 5):  # 5,10,15,...,100
            self.scaleComboBox.addItem(str(val), val)
        index = self.scaleComboBox.findData(self.saved_scale)
        if index >= 0:
            self.scaleComboBox.setCurrentIndex(index)
        self.scaleComboBox.currentIndexChanged.connect(self.onScaleChanged)
        scaleLayout.addWidget(scaleLabel)
        scaleLayout.addWidget(self.scaleComboBox)
        scaleLayout.addStretch()

        # 导出按钮（默认颜色）
        exportSelectedLayersButton = QPushButton("Export Selected Layers")

        # 重命名工具
        renameLabel = QLabel("Update Name and Metadata")
        renameLineEdit = QLineEdit()
        renameButton = QPushButton("Update")
        statusBar = QStatusBar()

        # 布局
        vboxlayout = QVBoxLayout()
        vboxlayout.addLayout(filenameLayout)
        vboxlayout.addLayout(exportPathLayout)
        vboxlayout.addLayout(scaleLayout)
        vboxlayout.addWidget(exportSelectedLayersButton)
        vboxlayout.addWidget(renameLabel)
        vboxlayout.addWidget(renameLineEdit)

        hboxlayout = QHBoxLayout()
        hboxlayout.addStretch()
        hboxlayout.addWidget(renameButton)

        vboxlayout.addLayout(hboxlayout)
        vboxlayout.addStretch()
        vboxlayout.addWidget(statusBar)

        uiContainer.setLayout(vboxlayout)
        self.setWidget(uiContainer)

        # 信号连接
        exportSelectedLayersButton.released.connect(self.exportSelectedLayers)
        renameLineEdit.returnPressed.connect(
            partial(renameLayers, CONFIG, statusBar, renameLineEdit)
        )
        renameButton.released.connect(partial(renameLayers, CONFIG, statusBar, renameLineEdit))
        browseButton.released.connect(self.browseExportPath)

    def browseExportPath(self):
        path = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if path:
            self.exportPathLineEdit.setText(path)
            KI.writeSetting("", "batch_exporter_export_path", path)
            self.saved_export_path = path

    def onScaleChanged(self, index):
        scale = self.scaleComboBox.currentData()
        if scale is not None:
            KI.writeSetting("", "batch_exporter_global_scale", str(scale))

    def onFilenameChanged(self, text):
        KI.writeSetting("", "batch_exporter_filename", text)

    def exportSelectedLayers(self):
        filename = self.filenameLineEdit.text().strip()
        if not filename:
            filename = "output"

        export_path = self.exportPathLineEdit.text().strip()
        if not export_path:
            doc = KI.activeDocument()
            export_path = os.path.dirname(doc.fileName()) if doc else "."

        global_scale = int(KI.readSetting("", "batch_exporter_global_scale", "50"))
        CONFIG["meta"]["s"] = [global_scale]

        statusBar = self.findChild(QStatusBar)
        if statusBar:
            statusBar.showMessage("Exporting...", 2000)

        try:
            doc = KI.activeDocument()
            nodes = KI.activeWindow().activeView().selectedNodes()
            if not nodes:
                if statusBar:
                    statusBar.showMessage("No layers selected.", 3000)
                return

            for node in nodes:
                wn = WNode(CONFIG, node)
                wn.save(export_path, filename)

            if statusBar:
                statusBar.showMessage("Export completed.", 3000)
        except Exception as e:
            if statusBar:
                statusBar.showMessage(f"Error: {e}", 5000)
            raise

    def canvasChanged(self, canvas):
        pass


def renameLayers(cfg, statusBar, lineEdit):
    msg, timeout = (cfg["done"]["msg"].format("Renaming successful!"), cfg["done"]["timeout"])
    try:
        nodes = KI.activeWindow().activeView().selectedNodes()
        it = map(partial(WNode, cfg), nodes)
        it = map(partial(flip(WNode.rename), lineEdit.text()), it)
        kickstart(it)
    except ValueError as e:
        msg, timeout = cfg["error"]["msg"].format(e), cfg["error"]["timeout"]
    statusBar.showMessage(msg, timeout)


def registerDocker():
    docker = DockWidgetFactory(
        "pykrita_gdquest_art_tools", DockWidgetFactoryBase.DockRight, GameArtTools
    )
    KI.addDockWidgetFactory(docker)
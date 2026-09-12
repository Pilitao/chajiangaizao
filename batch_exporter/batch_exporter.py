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
from .Utils.Export import make_unique_filename

KI = Krita.instance()


class GameArtTools(DockWidget):
    title = "批量导出工具"

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
        filenameLabel = QLabel("文件名:")
        self.filenameLineEdit = QLineEdit()
        self.filenameLineEdit.setText(self.saved_filename)
        self.filenameLineEdit.textChanged.connect(self.onFilenameChanged)
        filenameLayout.addWidget(filenameLabel)
        filenameLayout.addWidget(self.filenameLineEdit)

        # 路径设置行
        exportPathLayout = QHBoxLayout()
        exportPathLabel = QLabel("导出路径:")
        self.exportPathLineEdit = QLineEdit()
        self.exportPathLineEdit.setText(self.saved_export_path)
        browseButton = QPushButton("浏览...")
        exportPathLayout.addWidget(exportPathLabel)
        exportPathLayout.addWidget(self.exportPathLineEdit)
        exportPathLayout.addWidget(browseButton)

        # 全局缩放下拉框（步长改为5，范围5~100）
        scaleLayout = QHBoxLayout()
        scaleLabel = QLabel("默认缩放 (%):")
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
        exportSelectedLayersButton = QPushButton("导出所选图层")

        # 重命名工具
        renameLabel = QLabel("更新名称和元数据")
        renameLineEdit = QLineEdit()
        renameButton = QPushButton("更新")
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

        # 额外：实时检测 export path 下是否包含同名文件，自动增加后缀
        self.exportPathLineEdit.textChanged.connect(self.onExportPathChanged)
        # filename 更改时也会触发唯一化（防止用户直接输入已有名）
        self.filenameLineEdit.textChanged.connect(self.updateFilenameUnique)

    def browseExportPath(self):
        path = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if path:
            self.exportPathLineEdit.setText(path)
            KI.writeSetting("", "batch_exporter_export_path", path)
            self.saved_export_path = path
            # 选择目录后立刻检查文件名
            self.updateFilenameUnique()

    def onExportPathChanged(self, text):
        # 保存设置并检查文件名唯一性
        KI.writeSetting("", "batch_exporter_export_path", text)
        self.saved_export_path = text
        self.updateFilenameUnique()

    def onScaleChanged(self, index):
        scale = self.scaleComboBox.currentData()
        if scale is not None:
            KI.writeSetting("", "batch_exporter_global_scale", str(scale))

    def onFilenameChanged(self, text):
        # 保存 filename 设置（但不要覆盖自动唯一化）
        KI.writeSetting("", "batch_exporter_filename", text)

    def updateFilenameUnique(self):
        """
        根据 exportPathLineEdit 的路径实时检查文件名是否在该文件夹内已存在，
        若已存在则在文件名末尾增加数字后缀（NAME -> NAME1 -> NAME2 ...）。
        仅在路径可读时执行；同时防止信号循环。
        """
        folder = self.exportPathLineEdit.text().strip()
        current = self.filenameLineEdit.text().strip()
        if not folder or not current:
            return
        try:
            unique = make_unique_filename(current, folder)
        except Exception:
            # 若检索失败（目录不存在或不可读），不改动
            return
        if unique != current:
            # 阻止触发 textChanged 的回环
            self.filenameLineEdit.blockSignals(True)
            self.filenameLineEdit.setText(unique)
            self.filenameLineEdit.blockSignals(False)
            KI.writeSetting("", "batch_exporter_filename", unique)
            self.saved_filename = unique

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
            statusBar.showMessage("导出中...", 2000)

        try:
            doc = KI.activeDocument()
            nodes = KI.activeWindow().activeView().selectedNodes()
            if not nodes:
                if statusBar:
                    statusBar.showMessage("未选择图层。", 3000)
                return

            # 在界面已有唯一化后，这里仍传入当前 filename（Infrastructure.save 也会再次保证唯一）
            for node in nodes:
                wn = WNode(CONFIG, node)
                wn.save(export_path, filename)

            if statusBar:
                statusBar.showMessage("导出完成。", 3000)
        except Exception as e:
            if statusBar:
                statusBar.showMessage(f"错误: {e}", 5000)
            raise

    def canvasChanged(self, canvas):
        pass


def renameLayers(cfg, statusBar, lineEdit):
    msg, timeout = (cfg["done"]["msg"].format("重命名成功！"), cfg["done"]["timeout"])
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

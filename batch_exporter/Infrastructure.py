import os
import re
from collections import OrderedDict
from functools import partial
from itertools import groupby, product, starmap, tee
from pathlib import Path

from krita import Krita
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QMessageBox   # 用于弹出覆盖询问

from .Utils import flip, kickstart
from .Utils.Export import exportPath, sanitize
from .Utils.Tree import pathFS

KI = Krita.instance()


def nodeToImage(wnode):
    """
    Returns an QImage 8-bit sRGB
    """
    SRGB_PROFILE = "sRGB-elle-V2-srgbtrc.icc"
    if wnode.trim == False:
        bounds = KI.activeDocument().bounds()
        x = bounds.x()
        y = bounds.y()
        w = bounds.width()
        h = bounds.height()
    else:
        [x, y, w, h] = wnode.bounds

    is_srgb = (
        wnode.node.colorModel() == "RGBA"
        and wnode.node.colorDepth() == "U8"
        and wnode.node.colorProfile().lower() == SRGB_PROFILE.lower()
    )

    if is_srgb:
        pixel_data = wnode.node.projectionPixelData(x, y, w, h).data()
    else:
        temp_node = wnode.node.duplicate()
        temp_node.setColorSpace("RGBA", "U8", SRGB_PROFILE)
        pixel_data = temp_node.projectionPixelData(x, y, w, h).data()

    return QImage(pixel_data, w, h, QImage.Format_ARGB32)


def expandAndFormat(img, margin=0, is_jpg=False):
    """
    Draws the image with transparent background if `is_jpg == False`, otherwise with a white background.
    It's done in a single function, to avoid creating extra images
    """
    if not margin and not is_jpg:
        return img
    corner = QSize(margin, margin)
    white = QColor(255, 255, 255) if is_jpg else QColor(255, 255, 255, 0)
    canvas = QImage(
        img.size() + corner * 2, QImage.Format_RGB32 if is_jpg else QImage.Format_ARGB32
    )
    canvas.fill(white)
    p = QPainter(canvas)
    p.drawImage(margin, margin, img)
    return canvas


def ask_overwrite(filepath):
    """询问用户是否覆盖已有文件，返回 True 表示覆盖，False 表示跳过"""
    reply = QMessageBox.question(
        None,
        "文件已存在",
        f"文件 '{filepath.name}' 已存在，是否覆盖？",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No
    )
    return reply == QMessageBox.Yes


class WNode:
    """
    Wrapper around Krita's Node class, that represents a layer.
    Adds support for export metadata and methods to export the layer
    based on its metadata.
    See the meta property for a list of supported metadata.
    """

    def __init__(self, cfg, node):
        self.cfg = cfg
        self.node = node

    def __bool__(self):
        return bool(self.node)

    @property
    def name(self):
        a = self.cfg["delimiters"]["assign"]
        name = self.node.name()
        name = name.split()
        name = filter(lambda n: a not in n, name)
        name = "_".join(name)
        return sanitize(self.cfg, name)

    @property
    def meta(self):
        a, s = self.cfg["delimiters"].values()
        meta = self.node.name().strip().split(a)
        meta = starmap(lambda fst, snd: (fst[-1], snd.split()[0]), zip(meta[:-1], meta[1:]))
        meta = filter(lambda m: m[0] in self.cfg["meta"].keys(), meta)
        meta = OrderedDict((k, v.lower().split(s)) for k, v in meta)
        meta.update({k: list(map(int, v)) for k, v in meta.items() if k in "ms"})
        meta.setdefault("c", self.cfg["meta"]["c"])  # coa_tools
        meta.setdefault("e", self.cfg["meta"]["e"])  # extension
        meta.setdefault("m", self.cfg["meta"]["m"])  # margin
        meta.setdefault("p", self.cfg["meta"]["p"])  # path
        meta.setdefault("s", self.cfg["meta"]["s"])  # scale
        meta.setdefault("t", self.cfg["meta"]["t"])  # trim
        return meta

    @property
    def path(self):
        return self.meta["p"][0]

    @property
    def coa(self):
        return self.meta["c"][0]

    @property
    def trim(self):
        if self.meta["t"][0].lower() in ["false", "no"]:
            return False
        else:
            return self.meta["t"]

    @property
    def parent(self):
        return WNode(self.cfg, self.node.parentNode())

    @property
    def children(self):
        return [WNode(self.cfg, n) for n in self.node.childNodes()]

    @property
    def type(self):
        return self.node.type()

    @property
    def position(self):
        bounds = self.node.bounds()
        return bounds.x(), bounds.y()

    @property
    def bounds(self):
        bounds = self.node.bounds()
        return bounds.x(), bounds.y(), bounds.width(), bounds.height()

    @property
    def size(self):
        bounds = self.node.bounds()
        return bounds.width(), bounds.height()

    def hasDestination(self):
        return "d=" in self.node.name()

    def isExportable(self):
        return (
            self.isPaintLayer() or self.isGroupLayer() or self.isFileLayer() or self.isVectorLayer()
        )  # yapf: disable

    def isMarked(self):
        return "e=" in self.node.name()

    def isLayer(self):
        return "layer" in self.type

    def isMask(self):
        return "mask" in self.type

    def isPaintLayer(self):
        return self.type == "paintlayer"

    def isGroupLayer(self):
        return self.type == "grouplayer"

    def isFileLayer(self):
        return self.type == "filelayer"

    def isFilterLayer(self):
        return self.type == "filterlayer"

    def isFillLayer(self):
        return self.type == "filllayer"

    def isCloneLayer(self):
        return self.type == "clonelayer"

    def isVectorLayer(self):
        return self.type == "vectorlayer"

    def isTransparencyMask(self):
        return self.type == "transparencyMask"

    def isFilterMask(self):
        return self.type == "filtermask"

    def isTransformMask(self):
        return self.type == "transformmask"

    def isSelectionMask(self):
        return self.type == "selectionmask"

    def isColorizeMask(self):
        return self.type == "colorizemask"

    def rename(self, pattern):
        """
        Renames the layer, scanning for patterns in the user's input trying to preserve metadata.
        Patterns have the form meta_name=value,
        E.g. s=50,100 to tell the tool to export two copies of the layer at 50% and 100% of its size
        This function will only replace or update corresponding metadata.
        If the rename string starts with a name, the layer's name will change to that.
        """
        patterns = pattern.strip().split()
        a = self.cfg["delimiters"]["assign"]

        patterns = map(partial(flip(str.split), a), patterns)

        success, patterns = tee(patterns)
        success = map(lambda p: len(p) == 2, success)
        if not all(success):
            raise ValueError("malformed pattern.")

        key = lambda p: p[0] in self.cfg["meta"].keys()
        patterns = sorted(patterns, key=key)
        patterns = groupby(patterns, key)

        newName = self.node.name()
        for k, ps in patterns:
            for p in ps:
                how = (
                    "replace"
                    if k is False
                    else "add"
                    if p[1] != "" and "{}{}".format(p[0], a) not in newName
                    else "subtract"
                    if p[1] == ""
                    else "update"
                )
                pat = (
                    p
                    if how == "replace"
                    else (r"$", r" {}{}{}".format(p[0], a, p[1]))
                    if how == "add"
                    else (
                        r"\s*({}{})[\w,]+\s*".format(p[0], a),
                        " " if how == "subtract" else r" \g<1>{} ".format(p[1]),
                    )
                )
                newName = re.sub(pat[0], pat[1], newName).strip()
        self.node.setName(newName)

    def save(self, dirname="", filename=""):
        """
        Transform Node to a QImage
        processes the image, names it based on metadata, and saves the image to the disk.
        """
        if not filename:
            filename = "output"  # 保底

        img = nodeToImage(self)
        meta = self.meta
        margin, scale = meta["m"], meta["s"]
        extension, path = meta["e"], meta["p"][0]

        # 路径处理：完全使用传入的 dirname，不再自动添加子文件夹
        dirPath = Path(dirname) if dirname else Path("")
        if not dirPath:
            # 如果路径为空，使用文档目录
            doc = KI.activeDocument()
            dirPath = Path(os.path.dirname(doc.fileName())) if doc else Path(".")
        dirPath.mkdir(parents=True, exist_ok=True)

        meta_s = self.cfg["meta"]["s"][0]

        for scale_val in scale:
            for margin_val in margin:
                for ext in extension:
                    # 生成图片
                    img_scaled = img
                    if scale_val != 100:
                        w = int(img.width() * scale_val / 100)
                        h = int(img.height() * scale_val / 100)
                        img_scaled = img.smoothScaled(w, h)
                    is_jpg = ext in ("jpg", "jpeg")
                    img_final = expandAndFormat(img_scaled, margin=margin_val, is_jpg=is_jpg)

                    # 构建文件路径：使用用户输入的文件名 + 扩展名
                    filepath = dirPath / f"{filename}.{ext}"

                    # 检查文件是否已存在
                    if filepath.exists():
                        if not ask_overwrite(filepath):
                            # 用户选择不覆盖，跳过该文件
                            continue

                    # 保存
                    img_final.save(str(filepath), quality=90 if is_jpg else -1)

    def saveCOA(self, dirname="", filename=""):
        if not filename:
            filename = "output"

        img = nodeToImage(self)
        meta = self.meta
        path, extension = "", meta["e"]

        dirPath = Path(dirname) if dirname else Path(".")
        dirPath.mkdir(parents=True, exist_ok=True)

        ext = extension[0]
        filepath = dirPath / f"{filename}.{ext}"

        if filepath.exists():
            if not ask_overwrite(filepath):
                return ""

        is_jpg = ext in ("jpg", "jpeg")
        if is_jpg:
            img = expandAndFormat(img, is_jpg=True)
        img.save(str(filepath), quality=90 if is_jpg else -1)

        return str(filepath)

    def saveCOASpriteSheet(self, dirname="", filename=""):
        if not filename:
            filename = "output"

        images = self.children
        tiles_x, tiles_y = 1, len(images)
        image_width, image_height = self.size
        sheet_width, sheet_height = (image_width, image_height * tiles_y)

        sheet = QImage(sheet_width, sheet_height, QImage.Format_ARGB32)
        sheet.fill(QColor(255, 255, 255, 0))
        painter = QPainter(sheet)

        p_coord_x, p_coord_y = self.position
        for count, image in enumerate(images):
            coord_x, coord_y = image.position
            coord_rel_x, coord_rel_y = coord_x - p_coord_x, coord_y - p_coord_y
            painter.drawImage(
                coord_rel_x, image_height * count + coord_rel_y, nodeToImage(image),
            )

        meta = self.meta
        path, extension = "", meta["e"]

        dirPath = Path(dirname) if dirname else Path(".")
        dirPath.mkdir(parents=True, exist_ok=True)

        ext = extension[0]
        filepath = dirPath / f"{filename}.{ext}"

        if filepath.exists():
            if not ask_overwrite(filepath):
                return "", {}

        is_jpg = ext in ("jpg", "jpeg")
        if is_jpg:
            sheet = expandAndFormat(sheet, is_jpg=True)
        sheet.save(str(filepath), quality=90 if is_jpg else -1)

        return str(filepath), {"tiles_x": tiles_x, "tiles_y": tiles_y}
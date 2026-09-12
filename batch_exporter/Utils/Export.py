import re
from pathlib import Path
import os


def exportPath(cfg, path, dirname, userDefined):
    return dirname / (Path(path) if userDefined else (cfg["outDir"] / Path(path)))


def sanitize(cfg, path):
    ps = map(lambda p: cfg["sym"].sub("_", p), Path(path).parts)
    return str(Path(*ps))


def make_unique_filename(filename, folder_path):
    """
    如果 folder_path 下已存在 filename，则按规则生成带数字后缀的唯一文件名。
    规则：
      NAME -> NAME1
      NAME1 -> NAME2
      如果 NAME001 存在，会生成 NAME002（不保留前导零宽度）
    参数:
      filename: 含扩展名的文件名字符串，例如 'name.png'
      folder_path: 目标目录路径（str 或 Path）
    返回: 唯一的文件名（仅文件名，不含目录）
    """
    folder = Path(folder_path)
    try:
        existing = set(p.name for p in folder.iterdir() if p.is_file())
    except Exception:
        # 目录不存在或不可读，直接返回原始名字
        return filename

    base, ext = os.path.splitext(filename)  # ext 包含点
    m = re.match(r'^(.*?)(\d+)$', base)
    if m:
        root = m.group(1)
        start_num = int(m.group(2))
    else:
        root = base
        start_num = 0

    if filename not in existing:
        return filename

    i = start_num + 1
    while True:
        candidate = f"{root}{i}{ext}"
        if candidate not in existing:
            return candidate
        i += 1

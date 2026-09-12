import re
from pathlib import Path
import os
from collections import Counter


def exportPath(cfg, path, dirname, userDefined):
    return dirname / (Path(path) if userDefined else (cfg["outDir"] / Path(path)))


def sanitize(cfg, path):
    ps = map(lambda p: cfg["sym"].sub("_", p), Path(path).parts)
    return str(Path(*ps))


def make_unique_filename(filename, folder_path):
    """
    在 folder_path 中为 filename 生成唯一文件名，保留前导零宽度规则。

    行为说明：
    - 当 filename 包含扩展名时（例如 name.png），按该扩展名检测并返回带扩展名的唯一文件名。
    - 当 filename 不包含扩展名时（例如 name），会依据目标文件夹中已有同名文件推断扩展名（优先 png/jpg/其它）并返回带扩展名的唯一文件名（例如 name3.png）。
    - 若存在同名（不含数字）文件 NAME，则产生 NAME1；若存在 NAME1 则产生 NAME2，依此类推。
    - 若存在零前导数字（例如 NAME001），则保留数字宽度（001 -> 002）。

    返回值为带扩展名的字符串（例如 'name.png' 或 'name002.jpg'）。
    """
    folder = Path(folder_path)
    try:
        files = [p for p in folder.iterdir() if p.is_file()]
    except Exception:
        # 目录不存在或不可读，直接返回原始名字（若无扩展名则默认不加）
        return filename

    # 收集以 stem（不含扩展名）为键的所有扩展名
    stems = [p.stem for p in files]
    ext_map = {}
    for p in files:
        ext_map.setdefault(p.stem, []).append(p.suffix.lower())

    # 判断输入是否有扩展
    base_input, input_ext = os.path.splitext(filename)
    input_ext = input_ext.lower()

    # 解析 base 和可能的尾数字
    m_input = re.match(r'^(.*?)(\d+)$', base_input)
    if m_input:
        root = m_input.group(1)
        start_num = int(m_input.group(2))
        input_width = len(m_input.group(2))
    else:
        root = base_input
        start_num = None
        input_width = 0

    # 查找所有匹配 root 或 root+digits 的现有文件，收集最大数字与宽度
    max_num = 0
    max_width = 0
    exists_root = False
    # Also collect candidate extensions for chosen output
    candidate_exts = []
    for p in files:
        stem = p.stem
        if stem == root:
            exists_root = True
            candidate_exts.extend(ext_map.get(stem, []))
        m = re.match(r'^' + re.escape(root) + r'(\d+)$', stem)
        if m:
            num_str = m.group(1)
            num = int(num_str)
            max_num = max(max_num, num)
            max_width = max(max_width, len(num_str))
            candidate_exts.extend(ext_map.get(stem, []))

    # Decide extension to use in returned name
    chosen_ext = input_ext
    if not chosen_ext:
        # pick preferred ext from candidate_exts if any, prefer .png then .jpg/.jpeg
        if candidate_exts:
            c = [e.lower() for e in candidate_exts]
            if '.png' in c:
                chosen_ext = '.png'
            elif '.jpg' in c:
                chosen_ext = '.jpg'
            elif '.jpeg' in c:
                chosen_ext = '.jpeg'
            else:
                chosen_ext = c[0]
        else:
            # default to .png if nothing found
            chosen_ext = '.png'

    # If the exact filename (with ext) does not conflict, return as-is
    if input_ext:
        target = filename
        existing_fullnames = set(p.name for p in files)
        if target not in existing_fullnames:
            return target
    else:
        # no ext in input: if no existing file with stem==base_input and no numbered variants, return with default ext
        if not exists_root and max_num == 0:
            return f"{base_input}{chosen_ext}"

    # Determine width to use for numbering
    if input_width:
        width = input_width
    elif max_width:
        width = max_width
    else:
        width = 0

    # Compute starting point
    if start_num is not None:
        # user provided a starting number
        start = max(start_num, max_num)
    else:
        start = max_num

    next_num = start + 1
    while True:
        if width:
            num_part = str(next_num).zfill(width)
        else:
            num_part = str(next_num)
        candidate_stem = f"{root}{num_part}"
        candidate_name = f"{candidate_stem}{chosen_ext}"
        # ensure candidate not among existing files
        existing_fullnames = set(p.name for p in files)
        if candidate_name not in existing_fullnames:
            return candidate_name
        next_num += 1

import os
import shutil

# 常见的隐藏目录名
common_hidden_dirs = {'.git', '.svn', '.hg', '.bzr', 
                        '.venv', '.env', '.tox', '.nox',
                        '.idea', '.vscode', '.vs', '.settings',
                        '.pycache', '.pytest_cache', '.mypy_cache', '.ruff_cache'}

# 常见的目录扩展名
dir_extensions = {'.tmp', '.temp', '.bak', '.backup', '.old',
                          '.d', '.lib', '.include', '.src', '.source',
                          '.build', '.dist', '.out', '.output',
                          '.egg-info', '.dist-info'}

# 常见无扩展名文件
common_files = {
    'makefile', 'dockerfile', '.gitignore', '.DS_Store', 'jenkinsfile', 'gemfile',
    'readme', 'license', 'changelog', 'authors', 'contributors',
    'install', 'configure', 'setup', 'requirements', 'pipfile',
    'procfile', 'rakefile', 'gruntfile', 'gulpfile', 'webpackfile',
    'sconstruct', 'sconscript'
}


def _is_windows_abs_path(path: str) -> bool:
    """检测是否为 Windows 风格绝对路径（盘符 + 冒号 + 分隔符）"""
    if len(path) >= 3 and path[0].isalpha() and path[1] == ':':
        return path[2] in ('\\', '/')
    return False


def _is_unix_abs_path(path: str) -> bool:
    """检测是否为 Unix 风格绝对路径（以 / 开头且不是 Windows 盘符路径）"""
    return path.startswith('/') and not _is_windows_abs_path(path)


def check_file_path(file_path: str):
    """检查文件路径合法性（不检查存在性），合法返回 None，否则返回错误信息"""
    if not file_path or not isinstance(file_path, str):
        return "ERROR：路径不能为空"
    if not os.path.isabs(file_path):
        if os.sep == '/' and _is_windows_abs_path(file_path):
            return f"ERROR：路径格式不匹配当前平台（当前为 Unix/macOS 平台）"
        if os.sep == '\\' and _is_unix_abs_path(file_path):
            return f"ERROR：路径格式不匹配当前平台（当前为 Windows 平台）"
        return "ERROR：路径必须是绝对路径"
    if '\x00' in file_path:
        return "ERROR：路径包含非法字符"

    # 基于原始路径检查基础名（去除尾部斜杠后），避免 normpath 把 . 和 .. 解析掉
    original_base = os.path.basename(file_path.rstrip(os.sep))
    if original_base in ('.', '..'):
        return f"ERROR：路径必须以文件名结尾，不能以 {original_base} 结尾"

    # 原始路径不能以路径分隔符结尾（先于 normpath 检查，否则 normpath 会去掉它）
    if file_path.endswith(os.sep):
        return "ERROR：文件路径不能以路径分隔符结尾"

    normalized = os.path.normpath(file_path)
    if not normalized or normalized == '.':
        return "ERROR：路径无效"

    return None


def check_dir_path(dir_path: str):
    """检查目录路径合法性（不检查存在性），合法返回 None，否则返回错误信息"""
    if not dir_path or not isinstance(dir_path, str):
        return "ERROR：路径不能为空"
    if not os.path.isabs(dir_path):
        if os.sep == '/' and _is_windows_abs_path(dir_path):
            return f"ERROR：路径格式不匹配当前平台（当前为 Unix/macOS 平台）"
        if os.sep == '\\' and _is_unix_abs_path(dir_path):
            return f"ERROR：路径格式不匹配当前平台（当前为 Windows 平台）"
        return "ERROR：路径必须是绝对路径"
    if '\x00' in dir_path:
        return "ERROR：路径包含非法字符"

    normalized = os.path.normpath(dir_path)
    if not normalized:
        return "ERROR：路径无效"

    # 基于原始路径检查基础名，避免 normpath 解析掉 ..
    original_base = os.path.basename(dir_path.rstrip(os.sep))
    if original_base == '..':
        return "ERROR：路径不能以 .. 结尾"

    return None

def isfile(path: str) -> bool:
    """
    判断字符串是否为文件路径（基于特征，不检查存在性）
    规则：
    1. 不以路径分隔符结尾
    2. 有文件扩展名 或 匹配常见无扩展名文件
    """
    if not path or not isinstance(path, str):
        return False

    normalized = os.path.normpath(path)
    # 标准化后为空
    if not normalized or normalized == '.':
        return False

    # 获取最后一部分
    base = os.path.basename(normalized)
    if not base or base in ('.', '..'):
        return False

    # 有扩展名
    if '.' in base:
        parts = base.split('.')
        if len(parts) >= 2:
            # 排除明显是目录的扩展名
            ext = '.' + parts[-1].lower()
            if ext in dir_extensions:
                return False
            # 其余情况，为文件
            return True

    # 判断是否为常见无扩展名文件
    if base.lower() in common_files:
        return True

    # 无特征，默认返回false
    return False


def isdir(path: str) -> bool:
    """
    判断字符串是否为目录路径（基于特征，不检查存在性）
    规则：
    1. 以路径分隔符结尾
    2. 无文件扩展名（或扩展名在目录白名单中）
    """
    if not path or not isinstance(path, str):
        return False

    normalized = os.path.normpath(path)
    # 标准化后为空
    if not normalized or normalized == '.':
        return False

    # 获取最后一部分
    base = os.path.basename(normalized)
    if not base or base in ('.', '..'):
        return True  # . 和 .. 是目录

    # 隐藏目录
    if base.startswith('.'):
        if base in common_hidden_dirs:
            return True
        # 其他隐藏项默认视为文件
        return False

    if '.' in base:
        parts = base.split('.')
        if len(parts) >= 2:
            # 是否为目录的扩展名
            ext = '.' + parts[-1].lower()
            if ext in dir_extensions:
                return True
            # 其余情况，为文件
            return False

    # 无扩展名, 认为是目录
    return True

def copy(source_path: str, target_path: str):
    """
    拷贝文件

    Args:
        source_path: 源文件路径
        target_path: 目标文件路径
    """
    # 确保目标目录存在
    target_dir = os.path.dirname(target_path)
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)

    # 拷贝文件
    shutil.copy2(source_path, target_path)
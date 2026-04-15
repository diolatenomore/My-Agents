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
    'makefile', 'dockerfile', '.gitignore', 'jenkinsfile', 'gemfile',
    'readme', 'license', 'changelog', 'authors', 'contributors',
    'install', 'configure', 'setup', 'requirements', 'pipfile',
    'procfile', 'rakefile', 'gruntfile', 'gulpfile', 'webpackfile',
    'sconstruct', 'sconscript'
}


def check_file_path(file_path: str):
    pass

def check_dir_path(dir_path: str):
    pass

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

    # 无特征，默认猜测为文件
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